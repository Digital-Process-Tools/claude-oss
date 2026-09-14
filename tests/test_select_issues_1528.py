"""#1528 -- lane labels already declare the file partition: a same-lane
overlap must be reported as information a caller can act on, never used to
silently exclude a candidate from selection.

Before this fix, `select()` dropped a candidate outright the moment its
declared files touched anything in the fleet's held set, with disposition
`lane-collision` -- the whole analysis (which files, held by whom) was
computed and then thrown away along with the candidate itself. That is the
issue's own worked example, reproduced here without a live board: two
issues resolving to the same lane label, one of them already running, and
the other one silently never offered as a candidate at all.

The fix keeps the candidate in `candidates`, still `eligible`, and attaches
an `overlap` field naming the held files and (when the payload carries a
`held` map) who already holds them. `overlap` is `None` for the ordinary,
disjoint case -- the positive control every "must report overlap" case
needs beside it, per this repo's own rule that a negative assertion needs a
positive one in the same fixture.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
}


def _issue(number, labels=None, **extra):
    row = {"number": number, "labels": labels or [], "author_association": "maintainer"}
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


def _resolve(repo, patterns):
    return {"patterns": [], "files": list(patterns)}


def test_overlap_is_reported_not_dropped():
    """The issue's own headline claim: a candidate whose files are already
    held stays a candidate, with the overlap named -- it is no longer
    excluded outright."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1526, ["priority-high"], lane_patterns=["CLAUDE.md"])],
        "held_files": ["CLAUDE.md", "agents/developer.md"],
        "held": {
            "CLAUDE.md": ["lane #1499"],
            "agents/developer.md": ["lane #1499"],
        },
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    assert result["state"] == "candidates", result
    assert result["dropped"] == []
    numbers = [c["number"] for c in result["candidates"]]
    assert 1526 in numbers
    candidate = result["candidates"][0]
    assert candidate["disposition"] == "eligible"
    assert candidate["overlap"] == {
        "files": ["CLAUDE.md"],
        "holders": ["lane #1499"],
    }


def test_no_overlap_reports_none_the_positive_control():
    """Pair to the test above: a candidate that names no held file must
    report `overlap: None`, never an empty-but-present structure that could
    be mistaken for "checked, nothing found" by a caller that only tests
    truthiness."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/free.py"])],
        "held_files": ["scripts/held.py"],
        "held": {"scripts/held.py": ["lane #99"]},
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    assert result["state"] == "candidates", result
    assert result["candidates"][0]["overlap"] is None


def test_lane_collision_disposition_no_longer_produced():
    """`lane-collision` used to be a real disposition in `dropped` -- the
    mechanism this issue removes. Nothing in `select()` produces it any
    more; an overlapping candidate is `eligible` with `overlap` set."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/held.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    dispositions = [d["disposition"] for d in result["dropped"]]
    assert "lane-collision" not in dispositions
    assert result["candidates"][0]["overlap"]["files"] == ["scripts/held.py"]


def test_overlap_holders_absent_when_no_held_map_given():
    """A caller offering only `held_files` (every test/caller written before
    this field existed) still gets the overlapping files named -- just with
    an empty `holders` list rather than a crash or a guess."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/held.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    assert result["candidates"][0]["overlap"] == {
        "files": ["scripts/held.py"],
        "holders": [],
    }
