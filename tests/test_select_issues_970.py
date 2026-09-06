"""#970 -- selection is five scripts and a session doing the joins.

`select_issues.py` composes `dispatch_rank.rank`/`order`, `preflight_check.
search`, `lane_setup.resolve_lane`/`lane_overlap` and `issue_claim.check`
into one call: board in, ranked claimable candidates out, each row carrying
why it survived or did not.

**The three states, and the one that must never render as another.** A tick
that finds no candidate (`none-available`, a real established absence) and a
tick that could not read one of its inputs (`could-not-select`) end
differently now -- `could-not-select` must never render as `none-available`,
which is the whole reason #970 was filed. Every test pairing those two is a
positive/negative control in the same fixture, per this repo's own rule that
a "must not fire" case needs a "must fire" case beside it.
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
    # #993: a non-loop issue needs a readable author association to rank.
    # This suite is about the other joins `select()` composes, not the
    # author axis itself, so a fixture that does not care which value it
    # carries defaults to "maintainer" -- overridable via `extra` for a test
    # that does care.
    row = {"number": number, "labels": labels or [], "author_association": "maintainer"}
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    """A stand-in for `issue_claim.check` that reads every issue as unassigned."""
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


# ---------------------------------------------------------------------------
# could-not-select vs none-available -- the pairing the issue is about
# ---------------------------------------------------------------------------


def test_an_unreadable_board_is_could_not_select_never_none_available():
    result = select_issues.select(
        {
            "declared": DECLARED,
            "board_read_ok": False,
            "board_read_why": "gh-issues timed out",
        }
    )
    assert result["state"] == "could-not-select"
    assert "gh-issues timed out" in result["why"]


def test_a_genuinely_empty_board_is_none_available_the_positive_control():
    """The pair to the test above: a board that WAS read, and is truly empty."""
    result = select_issues.select({"declared": DECLARED, "issues": []})
    assert result["state"] == "none-available"


def test_an_unreadable_assignee_field_forces_could_not_select():
    def checker(numbers, mode, run=None, repo=None):
        return [
            {"issue": n, "state": "could-not-read", "detail": "gh timed out"}
            for n in numbers
        ]

    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=checker)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]
    # #970 review round: an unreadable assignee field must still leave a
    # dropped row behind, carrying the disposition the module's own
    # docstring promises -- not silently discarded the way the overall
    # could-not-select return used to hardcode `dropped: []`.
    assert result["dropped"] == [
        {
            "number": 1,
            "disposition": "assignee-unreadable",
            "why": "assignee read failed: gh timed out",
        }
    ]


def test_an_unmatched_preflight_pattern_still_produces_candidates():
    """The positive control for the could-not-search case below: an ordinary,
    successful preflight read that finds nothing does not block selection."""

    def search(pattern, roots):
        return {
            "state": "not-matched",
            "pattern": pattern,
            "roots": [str(r) for r in roots],
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], preflight_pattern="def fixed_already")],
    }
    result = select_issues.select(payload, checker=_no_op_checker, search=search)
    assert result["state"] == "candidates"
    assert [c["number"] for c in result["candidates"]] == [1]


def test_a_preflight_that_could_not_search_forces_could_not_select():
    def search(pattern, roots):
        return {
            "state": "could-not-search",
            "pattern": pattern,
            "roots": [str(r) for r in roots],
            "problem": "root(s) missing: /nope",
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], preflight_pattern="def fixed_already")],
    }
    result = select_issues.select(payload, checker=_no_op_checker, search=search)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]


# ---------------------------------------------------------------------------
# per-issue disposition
# ---------------------------------------------------------------------------


def test_a_stale_issue_is_dropped_with_its_pattern_named():
    def search(pattern, roots):
        return {
            "state": "matched",
            "pattern": pattern,
            "matches": [{"path": "x.py", "line": 1, "text": "..."}],
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], preflight_pattern="already fixed")],
    }
    result = select_issues.select(payload, checker=_no_op_checker, search=search)
    assert result["state"] == "none-available"
    assert result["dropped"] == [
        {
            "number": 1,
            "disposition": "stale",
            "why": "preflight pattern matched: already fixed",
        }
    ]


def test_an_unrankable_issue_is_dropped_and_named():
    payload = {"declared": {}, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["number"] == 1
    assert result["dropped"][0]["disposition"] == "unrankable"


def test_a_non_loop_issue_with_no_readable_association_is_unrankable_993():
    """#993, one layer up from `dispatch_rank.rank` itself: a payload that
    never wired up `author_association` for a non-loop issue must not be
    silently ranked as though it were the maintainer's own -- it is dropped
    `unrankable`, the same disposition an undeclared label axis produces."""
    payload = {
        "declared": DECLARED,
        "issues": [{"number": 1, "labels": ["priority-high"]}],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "none-available", result
    assert result["dropped"][0]["disposition"] == "unrankable", result
    assert "association" in result["dropped"][0]["why"], result


def test_an_external_issue_outranks_a_maintainer_one_at_the_same_band_993():
    """Positive control for the test above, and #993's own headline claim:
    given a real association reading, an external report does place ahead
    of a maintainer one of the same priority band."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high"], author_association="maintainer"),
            _issue(2, ["priority-high"], author_association="external"),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates", result
    numbers = [c["number"] for c in result["candidates"]]
    assert numbers == [2, 1], numbers


def test_an_assigned_issue_is_dropped_and_named():
    def checker(numbers, mode, run=None, repo=None):
        return [
            {"issue": n, "state": "assigned", "assignees": ["someone"]} for n in numbers
        ]

    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=checker)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["disposition"] == "assigned"


def test_a_lane_collision_is_dropped_and_named():
    def resolve(repo, patterns):
        return {"patterns": [], "files": list(patterns)}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/held.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["disposition"] == "lane-collision"
    assert "scripts/held.py" in result["dropped"][0]["why"]


def test_a_refused_lane_pattern_forces_could_not_select_998():
    """#998: a lane pattern `resolve_lane` could not read at all -- `refused`,
    the same state `_lane_pattern_problem` also produces for a bad literal or
    a glob-and-OSError -- must not read as "this lane resolved to no files,
    therefore no overlap". An unreadable input is dark, not clean."""

    def resolve(repo, patterns):
        return {
            "patterns": [
                {
                    "pattern": patterns[0],
                    "state": "refused",
                    "files": [],
                    "detail": "ValueError: bad pattern",
                }
            ],
            "files": [],
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["[unterminated"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]


def test_eligible_candidates_are_ranked_best_first():
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-low"]),
            _issue(2, ["priority-high"]),
            _issue(3, ["priority-high", "filed-by-loop"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    numbers = [c["number"] for c in result["candidates"]]
    # maintainer/high (2) outranks loop/high (3) outranks maintainer/low (1) --
    # ROWS order (#993: "human" split into external/maintainer; _issue()'s own
    # default author_association is "maintainer").
    assert numbers == [2, 3, 1]
    for c in result["candidates"]:
        assert c["disposition"] == "eligible"


# #1145 review note: this file used to end with a "main() / CLI" section
# exercising `main([])`'s default stdin-payload mode (a closed stdin, an
# ordinary piped board, a non-ASCII label, undecodable stdin). #1145 removes
# that mode outright -- `select_issues.py` fetches its own board now, and
# there is no stdin alternative to fall back to -- so those four tests
# asserted a contract this module no longer offers. Their replacements live
# in tests/test_select_issues_fetch_1145.py, against `select_fleet` and
# `_fetch_board` directly; `select()` itself (tested above, unchanged by
# #1145/#1146/#1147) is still the payload-driven primitive those exercise.
