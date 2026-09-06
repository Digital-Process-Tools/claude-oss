"""#1146 -- `select_issues.select_fleet` returns one group per lane, never
a partition of the whole board -- iterating `.oss.json`'s `labels.lanes`
(plus `labels.lane_other`, a real sixth lane, #1130) instead of grouping
every issue on the board into 18 near-useless buckets.

An issue carrying no `lane-*` label at all is NOT a lane -- see
tests/test_select_issues_lane_other_sixth_lane_1146.py for that half of
the design (the `dropped` accounting, #1130's own settlement).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "lanes": ["lane-dispatch", "lane-doctor"],
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
    "lane_other": "lane-other",
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


# --------------------------------------------------------------- must-fire


def test_one_key_per_declared_lane_label_plus_lane_other():
    board = [
        _issue(1, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"]),
        _issue(2, ["priority-high", "lane-doctor"], lane_patterns=["scripts/b.py"]),
    ]
    result = _select_fleet(board)
    assert set(result["lanes"].keys()) == {"lane-dispatch", "lane-doctor", "lane-other"}


def test_a_lane_label_with_no_eligible_work_is_a_stated_absence_not_a_missing_key():
    board = [_issue(1, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"])]
    result = _select_fleet(board)
    assert "lane-doctor" in result["lanes"]
    assert result["lanes"]["lane-doctor"]["state"] == "none-available"


# ------------------------------------------------------------ positive control


def test_a_declared_lane_full_of_ineligible_work_stays_a_named_lane_none_available():
    """Positive control for the stated-absence test above: a lane label
    that IS on the board, but every one of its issues is already assigned,
    still gets its own key (never dropped for having nothing usable)."""
    board = [_issue(6, ["priority-high", "lane-doctor"], lane_patterns=["scripts/e.py"])]

    def assigned_checker(numbers, mode, run=None, repo=None):
        return [
            {"issue": n, "state": "assigned", "assignees": ["someone"]}
            for n in numbers
        ]

    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(board),
        held_fetcher=_held(),
        checker=assigned_checker,
        resolve_lane=_literal_resolve,
    )
    assert "lane-doctor" in result["lanes"]
    assert result["lanes"]["lane-doctor"]["state"] == "none-available"
