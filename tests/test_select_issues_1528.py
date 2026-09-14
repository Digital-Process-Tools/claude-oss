"""#1528 -- lane labels already declare the file partition: a candidate whose
own declared files overlap the fleet's already-held file set must not be
dropped outright any more.

Narrowed scope (maintainer directive, mid-lane): the per-candidate `overlap`
field this fix originally built (naming which files, and who holds them) is
removed again in this same lane's own follow-up commit. #1530 is deleting
the whole per-issue file-set declaration apparatus this field would have
fed (`lane_patterns`, its label fallback, the held-set derivation) in a
separate lane, so this one does not invest in a field only to have it
deleted again. The one thing that survives is the actual deliverable: the
candidate is no longer excluded.
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


def test_an_overlapping_candidate_is_not_dropped():
    """The issue's own headline claim, and the actual deliverable of this
    lane: a candidate whose declared files overlap the fleet's held set
    stays a candidate rather than being excluded outright. The issue's own
    worked example: #1526's files (`CLAUDE.md`, ...) are already held by
    lane #1499 -- both resolve to `lane-prose` -- and #1526 must still be
    offered as a candidate."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1526, ["priority-high"], lane_patterns=["CLAUDE.md"])],
        "held_files": ["CLAUDE.md", "agents/developer.md"],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    assert result["state"] == "candidates", result
    assert result["dropped"] == []
    numbers = [c["number"] for c in result["candidates"]]
    assert 1526 in numbers
    assert result["candidates"][0]["disposition"] == "eligible"


def test_a_disjoint_candidate_is_unaffected_the_positive_control():
    """Pair to the test above: a candidate with no overlap at all must
    still select cleanly -- proving the fix did not accidentally start
    admitting every candidate regardless of the other, unrelated filters
    (assigned, stale, unrankable) this module still enforces."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/free.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    assert result["state"] == "candidates", result
    assert result["dropped"] == []
    assert result["candidates"][0]["number"] == 1


def test_lane_collision_disposition_no_longer_produced():
    """`lane-collision` used to be a real disposition in `dropped` -- the
    mechanism this issue removes. Nothing in `select()` produces it any
    more, for any input."""
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
    assert result["state"] == "candidates"


def test_no_overlap_field_is_attached_to_a_candidate():
    """This lane's own narrowed scope, pinned: `select()` must not surface
    an `overlap` key on a candidate at all -- that surface was removed in
    this same lane's follow-up commit rather than shipped, per the
    maintainer's directive that #1530 owns building any replacement."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1526, ["priority-high"], lane_patterns=["CLAUDE.md"])],
        "held_files": ["CLAUDE.md"],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_resolve
    )
    assert "overlap" not in result["candidates"][0]
