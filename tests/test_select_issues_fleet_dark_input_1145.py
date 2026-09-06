"""#1145 review round: a per-lane `select()` call that itself answers
`could-not-select` (a dark preflight or lane pattern scoped to that one
lane label's own issues) used to crash `select_fleet` with an uncaught
`KeyError: 'groups'` -- `_could_not_select()`'s own return has no `groups`
key at all, and `_run_one` attached bodies unconditionally. A crash is
worse than the defect #970 exists to prevent: it does not even reach
`could-not-select`, it reaches nothing.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "lanes": ["lane-dispatch"],
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
}

CONFIG = {
    "repo": "Digital-Process-Tools/claude-oss",
    "worktree_root": "/tmp/wt",
    "labels": DECLARED,
}


def _fetcher(issues):
    def fetch(repo_slug, per=100, run=None):
        return {
            "state": "ok",
            "issues": issues,
            "capped": False,
            "cap_detail": "",
            "detail": "",
        }

    return fetch


def _held():
    def held_fetcher(repo_slug, worktree_root, exclude_issue=None, repo=None):
        return {"state": "resolved", "held": {}, "detail": ""}

    return held_fetcher


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [{"issue": n, "state": "unassigned", "assignees": []} for n in numbers]


def _bad_search(pattern, roots):
    return {"state": "could-not-search", "problem": "boom"}


def test_a_dark_input_scoped_to_one_lane_label_answers_could_not_select_not_a_crash():
    board = [
        {
            "number": 1,
            "title": "t",
            "body": "b",
            "labels": ["priority-high", "lane-dispatch"],
            "author_association": "maintainer",
            "preflight_pattern": "x",
        }
    ]
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(board),
        held_fetcher=_held(),
        checker=_no_op_checker,
        search=_bad_search,
    )
    assert result["lanes"]["lane-dispatch"]["state"] == "could-not-select"
    assert result["state"] == "could-not-select"


def test_a_dark_input_scoped_to_lane_other_also_does_not_crash():
    """#1146 maintainer correction: `lane-other` is a real, sixth lane now
    (not the deleted no-lane-label bucket), and it must survive a dark
    input the identical way any other lane does."""
    declared = dict(DECLARED, lane_other="lane-other")
    config = dict(CONFIG, labels=declared)
    board = [
        {
            "number": 2,
            "title": "t",
            "body": "b",
            "labels": ["priority-high", "lane-other"],
            "author_association": "maintainer",
            "preflight_pattern": "x",
        }
    ]
    result = select_issues.select_fleet(
        config,
        fetcher=_fetcher(board),
        held_fetcher=_held(),
        checker=_no_op_checker,
        search=_bad_search,
    )
    assert result["lanes"]["lane-other"]["state"] == "could-not-select"
    assert result["state"] == "could-not-select"


def test_an_untagged_issue_never_reaches_select_at_all_so_it_cannot_crash():
    """The complement: an issue with no lane label never enters any
    `select()` call, so a dark input on it is not even reachable -- it is
    simply accounted for in `dropped`."""
    board = [
        {
            "number": 3,
            "title": "t",
            "body": "b",
            "labels": ["priority-high"],
            "author_association": "maintainer",
            "preflight_pattern": "x",
        }
    ]
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(board),
        held_fetcher=_held(),
        checker=_no_op_checker,
        search=_bad_search,
    )
    assert result["state"] != "could-not-select"
    assert [d["number"] for d in result["dropped"]] == [3]
