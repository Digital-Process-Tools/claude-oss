"""#1068 gave `select()` a fourth join: board in, ranked **groups** out,
`candidates` left unchanged for any existing caller. #1530 replaced the
mechanism -- grouping used to run `suggest_companions`, a declared-file
overlap search, per lead; it now bundles candidates that already share the
same `lane-*` GitHub label directly, since a triager's label already
states the partition.

Rules from the issue and #1530's own follow-up, each covered by its own
test below:

* a candidate whose own lane label could not be determined is returned
  ungrouped, never guessed into a group (#267);
* a group is bounded by shared lane label, targeting three members --
  never padded to hit the number;
* each member's own disposition, and each group's own state
  (`candidates` / `none`), survive into the grouped output rather than
  flattening to one verdict;
* a `lane-other` candidate is a third route into `groups`, solo always.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
    "lanes": ["lane-dispatch", "lane-doctor", "lane-prose"],
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


# ---------------------------------------------------------------------------
# a candidate with no determinable lane label is ungrouped, never guessed
# ---------------------------------------------------------------------------


def test_a_candidate_with_no_lane_label_is_returned_ungrouped_never_guessed():
    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    assert result["groups"]["groups"] == []
    assert len(result["groups"]["ungrouped"]) == 1
    entry = result["groups"]["ungrouped"][0]
    assert entry["number"] == 1
    assert "lane label" in entry["why"]


def test_a_candidate_with_a_lane_label_and_no_peer_leads_its_own_group():
    """Positive control for the test above: a candidate that DOES carry a
    lane label, with nobody else sharing it, leads a (short) group of one
    rather than landing in `ungrouped` -- those are two different states,
    per the issue's own distinction between "never entered grouping" and
    "entered, and stayed alone"."""
    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high", "lane-dispatch"])],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    groups = result["groups"]["groups"]
    assert len(groups) == 1
    assert [m["number"] for m in groups[0]["members"]] == [1]
    assert groups[0]["members"][0]["role"] == "lead"
    assert groups[0]["state"] == "none"
    assert "lane-dispatch" in groups[0]["short_reason"]
    assert result["groups"]["ungrouped"] == []


def test_two_different_lane_labels_do_not_group_together_the_negative_control():
    """A candidate carrying a DIFFERENT lane label must not join another
    lead's group, even when it is the only other candidate on the board."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-dispatch"]),
            _issue(2, ["priority-high", "lane-doctor"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    groups = result["groups"]["groups"]
    assert len(groups) == 2
    for group in groups:
        assert len(group["members"]) == 1


# ---------------------------------------------------------------------------
# a group is bounded by shared lane label, targeting three, never padded
# ---------------------------------------------------------------------------


def test_same_label_candidates_are_grouped_up_to_the_target_of_three():
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-dispatch"]),
            _issue(2, ["priority-high", "lane-dispatch"]),
            _issue(3, ["priority-high", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    groups = result["groups"]["groups"]
    assert len(groups) == 1
    numbers = [m["number"] for m in groups[0]["members"]]
    assert numbers == [1, 2, 3]
    assert groups[0]["members"][1]["role"] == "member"
    assert groups[0]["state"] == "candidates"
    assert groups[0]["short_reason"] is None
    # every candidate landed in the one group -- nobody left to lead a second
    assert len(result["candidates"]) == 3


def test_a_fourth_same_label_candidate_is_not_padded_into_the_group():
    """The maintainer's own rule: three is a target, never a quota. A fourth
    genuinely same-label candidate is left for its own group rather than
    inflating this one past the target."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-dispatch"]),
            _issue(2, ["priority-high", "lane-dispatch"]),
            _issue(3, ["priority-high", "lane-dispatch"]),
            _issue(4, ["priority-high", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    groups = result["groups"]["groups"]
    lead_group = [g for g in groups if g["members"][0]["number"] == 1][0]
    assert [m["number"] for m in lead_group["members"]] == [1, 2, 3]
    assert len(lead_group["members"]) == 3
    # #4 was left out of the first group, and leads its own -- either way it
    # must not be silently dropped
    assert 4 not in [m["number"] for m in lead_group["members"]]
    assert any(g["members"][0]["number"] == 4 for g in groups if g is not lead_group)


# ---------------------------------------------------------------------------
# per-member disposition and per-group state survive, never flattened
# ---------------------------------------------------------------------------


def test_member_disposition_and_group_state_survive_into_grouped_output():
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-dispatch"]),
            _issue(2, ["priority-low", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    member = result["groups"]["groups"][0]["members"][1]
    assert member["disposition"] == "eligible"
    # the member's own rank/band -- computed for issue #2, priority-low, not
    # copied from the lead -- must be intact rather than overwritten
    assert member["band"] != result["groups"]["groups"][0]["members"][0]["band"]


# ---------------------------------------------------------------------------
# lane-other stays solo, unaffected by the move to label grouping (#1130)
# ---------------------------------------------------------------------------


def test_a_lane_other_candidate_is_dispatched_solo_never_grouped():
    declared = dict(DECLARED, lane_other="lane-other")
    payload = {
        "declared": declared,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-high", "lane-other"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    groups = result["groups"]["groups"]
    assert len(groups) == 2
    for group in groups:
        assert len(group["members"]) == 1
        assert group["state"] == "lane-other"


# ---------------------------------------------------------------------------
# suggest_companions keeps its own signature and stays independently
# callable, even though `_group_candidates` no longer calls it (#1530)
# ---------------------------------------------------------------------------


def test_suggest_companions_signature_is_unchanged_and_still_callable_directly():
    """#1530 stopped `select()` from calling `suggest_companions` for
    grouping; it does not remove or move the function itself, which stays
    reachable and callable with its existing four positional arguments,
    independent of `select()`."""
    import inspect
    import lane_setup

    sig = inspect.signature(lane_setup.suggest_companions)
    assert list(sig.parameters) == ["repo", "own_issue", "claimed_files", "board"]
    result = lane_setup.suggest_companions(
        Path("."), 1, [], {"capped": False, "issues": []}
    )
    assert result["state"] == "none"
