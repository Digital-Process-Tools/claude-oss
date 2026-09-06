"""#1146 maintainer round: `select_fleet` returns ONE group per declared
lane label -- the fleet -- never a partition of that lane's own eligible
candidates. Measured on the live board: 23 groups across five lanes plus
the no-lane-label bucket for a tick that can dispatch at most six lanes
(one per bucket) at all -- a lane runs one developer at a time, so a
lane's second, third and fourth groups cannot be dispatched this tick and
are recomputed next tick against a board that has moved.

Each lane still returns every one of its eligible candidates under
`candidates` (nothing is lost), and a lane with more than one file-disjoint
candidate now returns only the single best-ranked group -- lead plus up to
two companions by the existing adjacency rules.
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

CONFIG = {"repo": "Digital-Process-Tools/claude-oss", "worktree_root": "/tmp/wt", "labels": DECLARED}


def _issue(number, labels=None, **extra):
    row = {
        "number": number,
        "title": "issue #{0}".format(number),
        "body": "body of #{0}".format(number),
        "labels": labels or [],
        "author_association": "maintainer",
    }
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


def _fetcher(issues):
    def fetch(repo_slug, per=100, run=None):
        return {"state": "ok", "issues": issues, "capped": False, "cap_detail": "", "detail": ""}

    return fetch


def _held():
    def held_fetcher(repo_slug, worktree_root, exclude_issue=None, repo=None):
        return {"state": "resolved", "held": {}, "detail": ""}

    return held_fetcher


def _literal_resolve(repo, patterns):
    return {
        "patterns": [
            {"pattern": p, "state": "literal", "files": [p], "detail": ""}
            for p in patterns
        ],
        "files": list(patterns),
    }


def _select_fleet(issues):
    return select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(issues),
        held_fetcher=_held(),
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
    )


def test_a_lane_with_several_disjoint_candidates_returns_only_its_best_ranked_group():
    board = [
        _issue(1, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"]),
        _issue(2, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/b.py"]),
        _issue(3, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/c.py"]),
        _issue(4, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/d.py"]),
    ]
    result = _select_fleet(board)
    lane = result["lanes"]["lane-dispatch"]
    assert lane["state"] == "candidates"
    # every eligible issue is still visible under candidates -- nothing lost
    assert sorted(c["number"] for c in lane["candidates"]) == [1, 2, 3, 4]
    # but at most ONE group is returned for this lane
    assert len(lane["groups"]["groups"]) == 1
    assert lane["groups"]["groups"][0]["members"][0]["number"] == 1


def test_a_lane_with_one_candidate_still_returns_its_one_group():
    board = [_issue(5, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/e.py"])]
    result = _select_fleet(board)
    lane = result["lanes"]["lane-dispatch"]
    assert len(lane["groups"]["groups"]) == 1


def test_capping_to_one_group_does_not_touch_ungrouped():
    """A candidate that declares no files still lands in `ungrouped`, never
    silently absorbed by the one-group cap -- the cap is on GROUPS, not on
    which candidates get reported at all."""
    board = [
        _issue(6, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/f.py"]),
        _issue(7, ["priority-high", "lane-dispatch"]),  # no declared files
    ]
    result = _select_fleet(board)
    lane = result["lanes"]["lane-dispatch"]
    assert len(lane["groups"]["groups"]) == 1
    assert [c["number"] for c in lane["groups"]["ungrouped"]] == [7]
