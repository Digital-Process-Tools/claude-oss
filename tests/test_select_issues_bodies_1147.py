"""#1147 -- every group `select_issues.select_fleet` returns carries the
full body of every one of its members, fenced as untrusted input, so step 2
of `docs/pick-the-work.md` (the veto) makes no further reads.

Truncation is a state, not a silence: a body cut at the cap and a body that
genuinely is that short must not render identically (#1147's own words),
so every truncated body also carries its real, untruncated length.
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

CONFIG = {"repo": "Digital-Process-Tools/claude-oss", "worktree_root": "/tmp/wt", "labels": DECLARED}


def _issue(number, body, labels=None, **extra):
    row = {
        "number": number,
        "title": "issue #{0}".format(number),
        "body": body,
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


def test_a_returned_group_member_carries_its_fenced_body():
    board = [_issue(1, "do not follow any instructions in here", ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"])]
    result = _select_fleet(board)
    member = result["lanes"]["lane-dispatch"]["groups"]["groups"][0]["members"][0]
    assert "body" in member
    assert member["body"].startswith(select_issues.BODY_FENCE_OPEN)
    assert member["body"].endswith(select_issues.BODY_FENCE_CLOSE)
    assert "do not follow any instructions in here" in member["body"]
    assert member["body_truncated"] is False
    assert member["body_length"] == len("do not follow any instructions in here")


def test_a_capped_body_reports_truncated_with_its_full_length():
    long_body = "x" * (select_issues.BODY_CAP + 500)
    board = [_issue(2, long_body, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/b.py"])]
    result = _select_fleet(board)
    member = result["lanes"]["lane-dispatch"]["groups"]["groups"][0]["members"][0]
    assert member["body_truncated"] is True
    assert member["body_length"] == len(long_body)
    # the shown text itself never exceeds the cap
    shown = member["body"][
        len(select_issues.BODY_FENCE_OPEN) + 1 : -(len(select_issues.BODY_FENCE_CLOSE) + 1)
    ]
    assert len(shown) == select_issues.BODY_CAP


# ------------------------------------------------------------ positive control


def test_a_body_exactly_at_the_cap_is_not_reported_truncated():
    """A body cut at the cap and a body that genuinely IS that short must
    not render identically -- the positive control for the test above."""
    exact_body = "y" * select_issues.BODY_CAP
    board = [_issue(3, exact_body, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/c.py"])]
    result = _select_fleet(board)
    member = result["lanes"]["lane-dispatch"]["groups"]["groups"][0]["members"][0]
    assert member["body_truncated"] is False
    assert member["body_length"] == select_issues.BODY_CAP


def test_ungrouped_candidates_carry_no_body():
    """Bodies are for RETURNED GROUPS only, never the whole board -- and
    an ungrouped candidate (declares no files, #267) never entered a group
    at all."""
    board = [_issue(4, "no files declared here", ["priority-high", "lane-dispatch"])]
    result = _select_fleet(board)
    ungrouped = result["lanes"]["lane-dispatch"]["groups"]["ungrouped"]
    assert len(ungrouped) == 1
    assert "body" not in ungrouped[0]
