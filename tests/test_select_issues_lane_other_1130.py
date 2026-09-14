"""#1130: `lane-other` -- a triaged issue with no owning lane -- must never
render as an untriaged one, and must never be treated as bundleable.

`.oss.json` declares real lanes; the triager's correct behaviour when none
fits is to apply nothing, which makes an examined-and-refused issue
indistinguishable from one nobody has read. `lane-other` is the positive
statement "triaged, no lane owns its files."

A `lane-other` candidate is dispatched solo, always: never given a
companion, never offered as one, never padded toward `_GROUP_TARGET`. It
must come out of grouping as a deliberate group of one with a stated
`short_reason` -- entering grouping and staying alone -- never landing in
`ungrouped`, which means "never entered grouping at all". #1530 replaced
the file-overlap grouping mechanism with lane-label grouping; the solo
rule for `lane-other` is unchanged by that move, since a `lane-other`
issue carries no ordinary lane label to match on either way.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
    "lane_other": "lane-other",
    "lanes": ["lane-dispatch", "lane-doctor"],
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


# --------------------------------------------------------------- production shape


def test_lane_other_issue_and_a_bundleable_pair_both_present():
    """The production shape: a board carrying one `lane-other` issue AND a
    genuinely bundleable pair sharing a lane label. The pair must bundle;
    the `lane-other` issue must come out as a stated singleton, never in
    `ungrouped`, never as a member or lead of the pair's group."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium", "lane-dispatch"]),
            _issue(3, ["priority-medium", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    groups = result["groups"]["groups"]
    ungrouped = result["groups"]["ungrouped"]

    assert ungrouped == []

    solo = [g for g in groups if [m["number"] for m in g["members"]] == [1]]
    assert len(solo) == 1
    solo_group = solo[0]
    assert solo_group["short_reason"]
    assert "lane-other" in solo_group["short_reason"].lower()

    pair = [g for g in groups if {m["number"] for m in g["members"]} == {2, 3}]
    assert len(pair) == 1
    assert {m["number"] for m in pair[0]["members"]} == {2, 3}


def test_lane_other_issue_is_never_offered_as_a_companion():
    """Symmetric half of the rule, paired with the must-fire test above (the
    genuinely bundleable pair DOES bundle): even when a `lane-other` issue
    carries the SAME lane-* label spelling as a lead's own peer search would
    otherwise match, it must never be pulled in as a member -- the
    `is_lane_other` check, not label equality alone, decides membership.

    The `lane-other` issue outranks the lead here (`priority-high` vs.
    `priority-low`) so it is PROCESSED FIRST by `_group_candidates`'s own
    loop -- not because that ordering matters to the rule (it must not: see
    the "regardless of iteration order" claim in `_group_candidates`'s own
    docstring), but so a missing `is_lane_other` guard could not be hidden
    behind the pre-existing `if number in taken: continue` check."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-low", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    numbers_in_rank_order = [c["number"] for c in result["candidates"]]
    assert numbers_in_rank_order[0] == 1

    groups = result["groups"]["groups"]
    for group in groups:
        numbers = [m["number"] for m in group["members"]]
        if 1 in numbers:
            assert numbers == [1]
    lead_group = [g for g in groups if g["members"][0]["number"] == 2][0]
    assert [m["number"] for m in lead_group["members"]] == [2]


def test_a_lane_other_issue_never_gets_a_companion_itself():
    """Even when the board contains another candidate carrying the same
    lane-* label spelling, a `lane-other` lead never receives a companion
    -- solo dispatch, always."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    groups = result["groups"]["groups"]
    lead_group = [g for g in groups if g["members"][0]["number"] == 1][0]
    assert len(lead_group["members"]) == 1


def test_lane_other_singleton_is_distinguishable_from_ungrouped():
    """A `lane-other` singleton and an issue with no determinable lane label
    must render as different states -- the one 'entered grouping and
    stayed alone', the other 'never entered grouping at all'."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium"]),  # no lane label at all: genuinely unknown
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    ungrouped_numbers = {e["number"] for e in result["groups"]["ungrouped"]}
    assert ungrouped_numbers == {2}
    solo_numbers = {
        m["number"] for g in result["groups"]["groups"] for m in g["members"]
    }
    assert solo_numbers == {1}


def test_solo_is_a_bundling_verdict_not_a_ranking_one():
    """A priority-high `lane-other` issue still outranks a bundleable
    priority-low one -- solo dispatch must not touch the ranking axis."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(2, ["priority-low", "lane-dispatch"]),
            _issue(1, ["priority-high", "lane-other"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    numbers_in_rank_order = [c["number"] for c in result["candidates"]]
    assert numbers_in_rank_order[0] == 1
