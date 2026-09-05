"""#1067 -- three lane-collision inputs where a read failure rendered as a
clean answer instead of `could-not-select`.

`scripts/select_issues.py` (#970) exists to stop a tick that could not read
an input from closing like a tick that found nothing. It did that correctly
for the board and for the assignee read, but three inputs on the
lane-collision path still failed it:

1. `held_files` had no unreadable state -- "the live lanes could not be
   enumerated" and "there are no live lanes" arrived as the identical empty
   set.
2. The #998 refused-pattern dark-input guard sat inside
   `if lane_patterns and held_files:`, so it never fired with `held_files`
   empty -- the common case, lane 1 of any tick.
3. A lane pattern that resolves to zero files (`glob-no-match`, not
   `refused`) contributed `files: []` and passed as disjoint from every live
   lane.

Each fix below is paired with a positive control in the same fixture, per
this repo's own rule that a "must not fire" case needs a "must fire" case
beside it.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {"filed_by_loop": "filed-by-loop", "priority": ["priority-high", "priority-medium", "priority-low"]}


def _issue(number, labels=None, **extra):
    row = {"number": number, "labels": labels or [], "author_association": "maintainer"}
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [{"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"} for n in numbers]


# ---------------------------------------------------------------------------
# 1: `lanes_read_ok` / `lanes_read_why` -- held_files gets a real third state
# ---------------------------------------------------------------------------

def test_lanes_read_ok_false_forces_could_not_select_never_none_available():
    """The negative half: a lane inventory that could not be read must never
    render as "no lanes are live"."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"])],
        "lanes_read_ok": False,
        "lanes_read_why": "worktree_root is unreadable: PermissionError",
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "could-not-select"
    assert "worktree_root is unreadable" in result["why"]


def test_lanes_read_ok_absent_is_not_a_failure_the_positive_control():
    """The pair to the test above: a caller that never populated
    `lanes_read_ok` at all (every fixture predating #1067, and a caller with
    no lane inventory to offer) must not be treated as a failed read -- it is
    read as "not attempted", the same posture `board_read_ok`'s own absence
    already gets."""
    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"


def test_lanes_read_ok_true_with_a_real_collision_still_finds_it():
    """`lanes_read_ok: True` alongside a genuine, populated `held_files` must
    still run collision detection normally -- the new check does not
    accidentally short-circuit the existing path."""
    def resolve(repo, patterns):
        return {"patterns": [], "files": list(patterns)}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/held.py"])],
        "held_files": ["scripts/held.py"],
        "lanes_read_ok": True,
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["disposition"] == "lane-collision"


# ---------------------------------------------------------------------------
# 2: the #998 guard must fire regardless of whether held_files is populated
# ---------------------------------------------------------------------------

def test_a_refused_lane_pattern_is_dark_even_with_no_held_files():
    """The gap #1067 found: with `held_files` empty (lane 1 of any tick), a
    refused lane pattern used to never be looked at -- the `and held_files`
    condition skipped the whole block, #998's guard included."""
    def resolve(repo, patterns):
        return {
            "patterns": [
                {"pattern": patterns[0], "state": "refused", "files": [],
                 "detail": "ValueError: bad pattern"}
            ],
            "files": [],
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["[unterminated"])],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]


def test_a_readable_lane_pattern_with_no_held_files_still_finds_candidates():
    """The positive control: an ordinary, well-formed lane pattern with no
    held files at all (nothing to collide with) must still reach
    `candidates` -- the hoist must not turn every lane-pattern-bearing issue
    dark."""
    def resolve(repo, patterns):
        return {
            "patterns": [{"pattern": p, "state": "literal", "files": [p], "detail": ""} for p in patterns],
            "files": list(patterns),
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/free.py"])],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "candidates"
    assert [c["number"] for c in result["candidates"]] == [1]


# ---------------------------------------------------------------------------
# 3: a lane pattern that resolves to nothing is dark, not disjoint
# ---------------------------------------------------------------------------

def test_a_lane_pattern_resolving_to_nothing_is_dark_not_disjoint():
    """A well-formed, checked lane pattern that names zero files on disk
    (`glob-no-match`) must not pass as disjoint from every live lane -- there
    is no file set here to have compared."""
    def resolve(repo, patterns):
        return {
            "patterns": [{"pattern": patterns[0], "state": "glob-no-match", "files": [], "detail": ""}],
            "files": [],
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["formatters/**/*.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]
    assert "resolved to no files" in result["why"]


def test_a_lane_pattern_that_resolves_to_real_files_is_the_positive_control():
    """The pair to the test above: a lane pattern that DOES resolve to real
    files, and does not overlap what is held, is a genuine disjoint result
    and must still produce a candidate."""
    def resolve(repo, patterns):
        return {
            "patterns": [{"pattern": p, "state": "literal", "files": [p], "detail": ""} for p in patterns],
            "files": list(patterns),
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/free.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "candidates"
    assert [c["number"] for c in result["candidates"]] == [1]
