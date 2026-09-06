"""#1146 maintainer round 2: `no-lane-label` is capped to one group the same
way a real lane is (`cap_groups=True`) -- returning zero groups there would
make every unlabelled issue visible but undispatchable through the tool,
forcing the hand-composition the design exists to remove, but nothing about
the absence of a label changes the fact that a lane runs one developer at a
time. Six groups there is the same over-return already fixed for the five
real lanes.
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
    "lane_other": "lane-other",
}

CONFIG = {
    "repo": "Digital-Process-Tools/claude-oss",
    "worktree_root": "/tmp/wt",
    "labels": DECLARED,
}


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


def _literal_resolve(repo, patterns):
    return {
        "patterns": [
            {"pattern": p, "state": "literal", "files": [p], "detail": ""}
            for p in patterns
        ],
        "files": list(patterns),
    }


def test_no_lane_label_returns_only_its_best_ranked_group():
    board = [
        _issue(10, ["priority-high"], lane_patterns=["scripts/x.py"]),
        _issue(11, ["priority-high"], lane_patterns=["scripts/y.py"]),
        _issue(12, ["priority-high"], lane_patterns=["scripts/z.py"]),
    ]
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(board),
        held_fetcher=_held(),
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
    )
    bucket = result["lanes"][select_issues.NO_LANE_LABEL_KEY]
    # every eligible issue is still visible under candidates -- nothing lost
    assert sorted(c["number"] for c in bucket["candidates"]) == [10, 11, 12]
    # but at most ONE group is returned, same rule as a real lane
    assert len(bucket["groups"]["groups"]) == 1


def test_lane_other_solo_group_still_survives_the_cap():
    board = [_issue(13, ["priority-high", "lane-other"])]
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(board),
        held_fetcher=_held(),
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
    )
    bucket = result["lanes"][select_issues.NO_LANE_LABEL_KEY]
    groups = bucket["groups"]["groups"]
    assert len(groups) == 1
    assert groups[0]["state"] == "lane-other"
