"""#1199 -- the per-group `state` vocabulary select_issues.py/
select_issues_companions.py actually produce (`candidates`/`none`/
`could-not-tell`/`lane-other`) is exported as a real constant from
`select_issues_companions.py`, which both `select_issues.py` and
`lane_setup.py` already import -- so `lane_setup.py`'s own `_GROUP_STATES`
is that shared constant, not a second, independently-typed copy of it.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import lane_setup  # noqa: E402
import select_issues  # noqa: E402
import select_issues_companions  # noqa: E402


def test_companions_states_is_the_three_value_producer_vocabulary():
    assert select_issues_companions.STATES == (
        "candidates",
        "none",
        "could-not-tell",
    )


def test_group_states_adds_lane_other_to_the_companions_vocabulary():
    assert select_issues_companions.GROUP_STATES == (
        "candidates",
        "none",
        "could-not-tell",
        "lane-other",
    )


def test_lane_setup_no_longer_retypes_its_own_copy():
    """The whole point of #1199: `lane_setup._GROUP_STATES` IS the shared
    constant, so a rename or addition to the vocabulary in the producer
    module is automatically reflected here -- nothing to keep in sync by
    hand any more."""
    assert lane_setup._GROUP_STATES is select_issues_companions.GROUP_STATES


def _lane_other_board():
    return [
        {
            "number": 1,
            "title": "t",
            "body": "b",
            "labels": ["priority-high", "lane-dispatch", "lane-other"],
            "author_association": "maintainer",
        }
    ]


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


def _held(repo_slug, worktree_root, exclude_issue=None, repo=None):
    return {"state": "resolved", "held": {}, "detail": ""}


_LANE_OTHER_CONFIG = {
    "repo": "Digital-Process-Tools/claude-oss",
    "worktree_root": "/tmp/wt",
    "labels": {
        "lanes": ["lane-dispatch"],
        "filed_by_loop": "filed-by-loop",
        "priority": ["priority-high", "priority-medium", "priority-low"],
        "lane_other": "lane-other",
    },
}


def test_select_issues_solo_lane_other_group_uses_the_shared_constant():
    """`_group_candidates`'s own #1130 solo-dispatch branch sets the
    literal group state directly (it never calls `suggest_companions`) --
    it must use the same named constant, not a hand-typed string that
    could drift from it."""
    board = _lane_other_board()

    def _fetcher(repo_slug, per=100, run=None):
        return {
            "state": "ok",
            "issues": board,
            "capped": False,
            "cap_detail": "",
            "detail": "",
        }

    result = select_issues.select_fleet(
        _LANE_OTHER_CONFIG,
        fetcher=_fetcher,
        held_fetcher=_held,
        checker=_no_op_checker,
    )
    group = result["lanes"]["lane-other"]["groups"]["groups"][0]
    assert group["state"] == select_issues_companions.STATE_LANE_OTHER


def test_select_issues_solo_lane_other_group_actually_reads_the_constant_at_call_time(
    monkeypatch,
):
    """The positive control for the test above: an equality check against
    `STATE_LANE_OTHER` passes identically whether `_group_candidates` reads
    the shared constant or hardcodes the same string -- both currently
    equal `"lane-other"`. Monkeypatching the module attribute proves
    `select_issues.py` actually looks it up (`select_issues_companions.
    STATE_LANE_OTHER`, an attribute access) rather than having inlined its
    value at import time or hand-typed a literal that merely matches it
    today."""
    board = _lane_other_board()

    def _fetcher(repo_slug, per=100, run=None):
        return {
            "state": "ok",
            "issues": board,
            "capped": False,
            "cap_detail": "",
            "detail": "",
        }

    monkeypatch.setattr(
        select_issues_companions, "STATE_LANE_OTHER", "sentinel-lane-other"
    )
    result = select_issues.select_fleet(
        _LANE_OTHER_CONFIG,
        fetcher=_fetcher,
        held_fetcher=_held,
        checker=_no_op_checker,
    )
    group = result["lanes"]["lane-other"]["groups"]["groups"][0]
    assert group["state"] == "sentinel-lane-other"
