"""#1112 -- a lane_label matching nothing must be distinguishable from a
genuinely empty board. Both currently render as `none-available` with no
way to tell them apart; this asserts the receipt names the filter and how
many rows it removed.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {"priority": ["priority-high", "priority-medium", "priority-low"]}


def _issue(number, labels=None, **extra):
    row = {"number": number, "labels": labels or [], "author_association": "maintainer"}
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


def test_lane_label_matching_nothing_names_the_filter_and_count():
    payload = {
        "declared": DECLARED,
        "lane_label": "lane-release",
        "issues": [_issue(1, ["priority-high", "lane-doctor"])],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "none-available"
    assert result["lane_label_filter"] == {"label": "lane-release", "removed": 1}


def test_genuinely_empty_board_positive_control():
    payload = {"declared": DECLARED, "issues": []}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "none-available"
    assert result.get("lane_label_filter") is None
