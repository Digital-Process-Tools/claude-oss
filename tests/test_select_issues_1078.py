"""#1078 -- candidate GENERATION narrows to one lane LABEL before ranking,
declared-file disjointness (`_group_candidates`) stays the ADMISSION check.

Two cases, paired per this repo's own rule that a negative assertion needs a
positive control: a board with a `lane_label` filter must drop issues that
do not carry the label (must-not-pass-through), and a board with no
`lane_label` set at all must behave exactly as before (must-not-filter).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
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


def test_lane_label_narrows_candidate_generation_to_matching_issues():
    payload = {
        "declared": DECLARED,
        "lane_label": "lane-doctor",
        "issues": [
            _issue(1, ["priority-high", "lane-doctor"]),
            _issue(2, ["priority-high", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    numbers = [c["number"] for c in result["candidates"]]
    assert numbers == [1]


def test_no_lane_label_set_behaves_exactly_as_before_positive_control():
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-doctor"]),
            _issue(2, ["priority-high", "lane-dispatch"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    numbers = sorted(c["number"] for c in result["candidates"])
    assert numbers == [1, 2]


def test_lane_label_matching_nothing_is_none_available_not_a_crash():
    payload = {
        "declared": DECLARED,
        "lane_label": "lane-release",
        "issues": [
            _issue(1, ["priority-high", "lane-doctor"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "none-available"
