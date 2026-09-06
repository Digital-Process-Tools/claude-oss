"""#1146 maintainer correction: `lane-other` IS the sixth lane -- a real,
declared label meaning "triaged, no lane owns these files" (#1130) -- and
`no-lane-label` (an issue carrying no `lane-*` label at all, meaning
"nobody has triaged this yet") is NOT a lane and is never dispatched.

#1130's own measurement was that these two populations render identically
on an unlabelled board -- five deliberate refusals and one nobody had
read -- and #1146's first cut re-merged them by giving them a shared
pseudo-lane. The fix: iterate the declared lane labels PLUS
`labels.lane_other` (read from config, never hardcoded); an issue with no
lane label at all is dropped, with its own disposition, in the same
top-level `dropped` accounting -- no pseudo-lane, no group, no body.
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


def _select_fleet(issues):
    return select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(issues),
        held_fetcher=_held(),
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
    )


# --------------------------------------------------------------- must-fire


def test_lane_other_is_the_sixth_lane_key_read_from_config():
    board = [_issue(1, ["priority-high", "lane-other"])]
    result = _select_fleet(board)
    assert set(result["lanes"].keys()) == {"lane-dispatch", "lane-doctor", "lane-other"}
    assert not hasattr(select_issues, "NO_LANE_LABEL_KEY")


def test_lane_other_with_no_issue_is_a_stated_absence_not_a_missing_key():
    board = [
        _issue(1, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"])
    ]
    result = _select_fleet(board)
    assert "lane-other" in result["lanes"]
    assert result["lanes"]["lane-other"]["state"] == "none-available"


def test_lane_other_dispatches_solo_never_a_companion():
    board = [
        _issue(4, ["priority-high", "lane-other"]),
        _issue(5, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/d.py"]),
    ]
    result = _select_fleet(board)
    groups = result["lanes"]["lane-other"]["groups"]["groups"]
    assert len(groups) == 1
    assert groups[0]["state"] == "lane-other"
    assert [m["number"] for m in groups[0]["members"]] == [4]


def test_an_untagged_issue_is_not_a_lane_not_a_group_not_a_body_but_is_dropped_with_a_reason():
    board = [_issue(3, ["priority-high"])]  # no lane-* label at all
    result = _select_fleet(board)
    # never a lane key of its own
    assert set(result["lanes"].keys()) == {"lane-dispatch", "lane-doctor", "lane-other"}
    # never counted into any declared lane's candidates just for being on the board
    for label, lane in result["lanes"].items():
        assert lane["state"] == "none-available"
        for group in lane["groups"]["groups"]:
            for member in group["members"]:
                assert member["number"] != 3
    # accounted for, with its own disposition -- never silently gone
    dropped = result["dropped"]
    assert len(dropped) == 1
    assert dropped[0]["number"] == 3
    assert dropped[0]["disposition"] == "no-lane-label"
    assert dropped[0]["why"]


def test_lane_other_issue_is_not_double_counted_in_dropped():
    board = [_issue(4, ["priority-high", "lane-other"])]
    result = _select_fleet(board)
    assert result["dropped"] == []


# ------------------------------------------------------------ positive control


def test_a_declared_lane_with_real_work_is_unaffected_by_the_dropped_accounting():
    board = [
        _issue(1, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"]),
        _issue(2, ["priority-high"]),  # untagged, alongside real work
    ]
    result = _select_fleet(board)
    assert result["lanes"]["lane-dispatch"]["state"] == "candidates"
    assert [c["number"] for c in result["lanes"]["lane-dispatch"]["candidates"]] == [1]
    assert [d["number"] for d in result["dropped"]] == [2]


def test_a_failed_fetch_still_reports_an_empty_dropped_list_not_a_missing_key():
    def failing_fetcher(repo_slug, per=100, run=None):
        return {
            "state": "could-not-fetch",
            "issues": [],
            "capped": False,
            "cap_detail": "",
            "detail": "boom",
        }

    result = select_issues.select_fleet(
        CONFIG, fetcher=failing_fetcher, held_fetcher=_held(), checker=_no_op_checker
    )
    assert result["state"] == "could-not-select"
    assert result["dropped"] == []
