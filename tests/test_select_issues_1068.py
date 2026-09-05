"""#1068 -- selection hands back groups (dispatchable lanes), not a flat list.

`scripts/select_issues.py` (#970) composes ranking, staleness, claim and
collision correctly and returns `candidates` -- a flat, ranked list. #1068
adds a caller of `lane_setup.suggest_companions` inside `select()` itself,
the same way `select()` already composes `resolve_lane` and
`issue_claim.check`: board in, ranked **groups** out, `candidates` left
unchanged for any existing caller.

Rules from the issue and the maintainer's own follow-up comment, each
covered by its own test below:

* an issue declaring no files is returned ungrouped, never guessed into a
  group (#267);
* a group is bounded by declared-file overlap, targeting three members --
  never padded to hit the number;
* each member's own disposition, and each group's own third state
  (`candidates` / `none` / `could-not-tell`), survive into the grouped
  output rather than flattening to one verdict;
* a short group says why -- no overlapping candidate is a different row
  from a capped board read.
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


def _literal_resolve(repo, patterns):
    return {
        "patterns": [{"pattern": p, "state": "literal", "files": [p], "detail": ""} for p in patterns],
        "files": list(patterns),
    }


# ---------------------------------------------------------------------------
# an issue with no declared files is ungrouped, never guessed (#267)
# ---------------------------------------------------------------------------

def test_a_fileless_candidate_is_returned_ungrouped_never_guessed():
    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    assert result["groups"]["groups"] == []
    assert len(result["groups"]["ungrouped"]) == 1
    entry = result["groups"]["ungrouped"][0]
    assert entry["number"] == 1
    assert "no files" in entry["why"] or "not derivable" in entry["why"]


def test_a_candidate_with_declared_files_and_no_overlap_leads_its_own_group():
    """Positive control for the test above: a candidate that DOES declare
    files, with nothing to overlap it, leads a (short) group of one rather
    than landing in `ungrouped` -- those are two different states, per the
    issue's own distinction between "never entered grouping" and "entered,
    and stayed alone"."""
    def companions(repo, own_issue, claimed, board):
        return {"state": "none", "candidates": [], "undetermined": [], "detail": "swept, nothing overlaps"}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/a.py"])],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve, suggest_companions=companions,
    )
    assert result["state"] == "candidates"
    groups = result["groups"]["groups"]
    assert len(groups) == 1
    assert [m["number"] for m in groups[0]["members"]] == [1]
    assert groups[0]["members"][0]["role"] == "lead"
    assert groups[0]["state"] == "none"
    assert groups[0]["short_reason"] == "no further overlapping candidate among the ranked issues"
    assert result["groups"]["ungrouped"] == []


# ---------------------------------------------------------------------------
# a group is bounded by overlap, targeting three, never padded
# ---------------------------------------------------------------------------

def test_overlapping_candidates_are_grouped_up_to_the_target_of_three():
    def companions(repo, own_issue, claimed, board):
        return {
            "state": "candidates",
            "candidates": [{"number": 2, "files": ["scripts/shared.py"]},
                            {"number": 3, "files": ["scripts/shared.py"]}],
            "undetermined": [],
            "detail": "",
        }

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high"], lane_patterns=["scripts/shared.py"]),
            _issue(2, ["priority-high"]),
            _issue(3, ["priority-high"]),
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve, suggest_companions=companions,
    )
    groups = result["groups"]["groups"]
    assert len(groups) == 1
    numbers = [m["number"] for m in groups[0]["members"]]
    assert numbers == [1, 2, 3]
    assert groups[0]["members"][1]["role"] == "member"
    assert groups[0]["members"][1]["overlap"] == ["scripts/shared.py"]
    assert groups[0]["state"] == "candidates"
    assert groups[0]["short_reason"] is None
    # every candidate landed in the one group -- nobody left to lead a second
    assert len(result["candidates"]) == 3


def test_a_fourth_overlapping_candidate_is_not_padded_into_the_group():
    """The maintainer's own rule: three is a target, never a quota. A fourth
    genuinely overlapping candidate is left for its own group rather than
    inflating this one past the target."""
    def companions(repo, own_issue, claimed, board):
        if own_issue == 1:
            return {
                "state": "candidates",
                "candidates": [{"number": n, "files": ["scripts/shared.py"]} for n in (2, 3, 4)],
                "undetermined": [],
                "detail": "",
            }
        return {"state": "none", "candidates": [], "undetermined": [], "detail": ""}

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high"], lane_patterns=["scripts/shared.py"]),
            _issue(2, ["priority-high"]),
            _issue(3, ["priority-high"]),
            _issue(4, ["priority-high"]),
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve, suggest_companions=companions,
    )
    groups = result["groups"]["groups"]
    lead_group = [g for g in groups if g["members"][0]["number"] == 1][0]
    assert [m["number"] for m in lead_group["members"]] == [1, 2, 3]
    assert len(lead_group["members"]) == 3
    # #4 was left out of the first group, and leads its own (or would join a
    # later one) -- either way it must not be silently dropped
    assert 4 not in [m["number"] for m in lead_group["members"]]


# ---------------------------------------------------------------------------
# per-member disposition and per-group state survive, never flattened
# ---------------------------------------------------------------------------

def test_member_disposition_and_group_state_survive_into_grouped_output():
    def companions(repo, own_issue, claimed, board):
        return {
            "state": "candidates",
            "candidates": [{"number": 2, "files": ["scripts/shared.py"]}],
            "undetermined": [],
            "detail": "",
        }

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high"], lane_patterns=["scripts/shared.py"]),
            _issue(2, ["priority-low"]),
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve, suggest_companions=companions,
    )
    member = result["groups"]["groups"][0]["members"][1]
    assert member["disposition"] == "eligible"
    # the member's own rank/band -- computed for issue #2, priority-low, not
    # copied from the lead -- must be intact rather than overwritten
    assert member["band"] != result["groups"]["groups"][0]["members"][0]["band"]


def test_a_capped_board_read_reports_could_not_tell_never_none():
    """The negative half of the maintainer's own distinction: a short group
    because the board read was capped must not render the same way as a
    short group because nothing overlaps."""
    def companions(repo, own_issue, claimed, board):
        return {
            "state": "could-not-tell",
            "candidates": [],
            "undetermined": [],
            "detail": "the board read was capped (per=50)",
        }

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/a.py"])],
        "board_capped": True,
        "board_cap_detail": "per=50",
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve, suggest_companions=companions,
    )
    group = result["groups"]["groups"][0]
    assert group["state"] == "could-not-tell"
    assert "capped" in group["short_reason"]


def test_no_overlap_is_a_different_row_from_a_capped_read_the_positive_control():
    """Positive control for the test above: the "nothing overlaps" short
    reason must read differently from the "capped" one."""
    def companions(repo, own_issue, claimed, board):
        return {"state": "none", "candidates": [], "undetermined": [], "detail": "swept, clear"}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/a.py"])],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve, suggest_companions=companions,
    )
    group = result["groups"]["groups"][0]
    assert group["state"] == "none"
    assert "capped" not in group["short_reason"]
    assert "no further overlapping candidate" in group["short_reason"]


# ---------------------------------------------------------------------------
# suggest_companions keeps its own signature and stays independently callable
# ---------------------------------------------------------------------------

def test_suggest_companions_signature_is_unchanged_and_still_callable_directly():
    """#1068 adds a caller inside select_issues.py; it does not move the
    logic. `suggest_companions` must still be reachable and callable with its
    existing four positional arguments, independent of `select()`."""
    import inspect
    import lane_setup

    sig = inspect.signature(lane_setup.suggest_companions)
    assert list(sig.parameters) == ["repo", "own_issue", "claimed_files", "board"]
    result = lane_setup.suggest_companions(Path("."), 1, [], {"capped": False, "issues": []})
    assert result["state"] == "none"
