"""#1145 -- `select_issues.py` fetches its own board, and reads the lane
inventory itself, rather than requiring a caller-built payload on stdin.

The founding rule (#970) restated for the fetch this adds: a failed board
read or a failed held-set read must produce `could-not-select` for the
whole fleet, **never** `none-available` -- demonstrated live this session
by a hand-built payload with the wrong top-level key answering
`none-available` on a board carrying 24 live candidates. Every "must not
render as X" test below is paired with a "genuinely is X" positive control
in the same fixture, per this repo's own rule.
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


def _ok_fetcher(issues, capped=False, cap_detail=""):
    def fetch(repo_slug, per=100, run=None):
        return {
            "state": "ok",
            "issues": issues,
            "capped": capped,
            "cap_detail": cap_detail,
            "detail": "",
        }

    return fetch


def _failing_fetcher(detail="gh api graphql timed out"):
    def fetch(repo_slug, per=100, run=None):
        return {
            "state": "could-not-fetch",
            "issues": [],
            "capped": False,
            "cap_detail": "",
            "detail": detail,
        }

    return fetch


def _ok_held(held=None):
    def held_fetcher(repo_slug, worktree_root, exclude_issue=None, repo=None):
        return {"state": "resolved", "held": held or {}, "detail": ""}

    return held_fetcher


def _failing_held(detail="gh pr list timed out"):
    def held_fetcher(repo_slug, worktree_root, exclude_issue=None, repo=None):
        return {"state": "could-not-derive", "held": {}, "detail": detail}

    return held_fetcher


# --------------------------------------------------------------------- must-not


def test_a_failed_board_fetch_is_could_not_select_never_none_available():
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_failing_fetcher("gh api graphql timed out"),
        held_fetcher=_ok_held(),
        checker=_no_op_checker,
    )
    assert result["state"] == "could-not-select"
    assert "gh api graphql timed out" in result["why"]
    assert result["board_read_ok"] is False


def test_a_failed_held_set_read_is_could_not_select_for_the_whole_fleet():
    """The demonstrated defect, one input over: the fetch that used to be a
    caller's job is now this module's own, and a mis-shaped or failed read
    of EITHER of its two inputs must never quietly present as an empty,
    clean board."""
    board = [_issue(1, ["priority-high", "lane-dispatch"])]
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_ok_fetcher(board),
        held_fetcher=_failing_held("gh pr list timed out"),
        checker=_no_op_checker,
    )
    assert result["state"] == "could-not-select"
    assert "gh pr list timed out" in result["why"]
    assert result["lanes_read_ok"] is False


# ------------------------------------------------------------------- positive


def test_a_genuinely_empty_board_is_none_available_the_positive_control():
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_ok_fetcher([]),
        held_fetcher=_ok_held(),
        checker=_no_op_checker,
    )
    assert result["state"] == "none-available"


def test_a_clean_fetch_with_real_candidates_reaches_candidates():
    board = [_issue(1, ["priority-high", "lane-dispatch"], lane_patterns=["scripts/a.py"])]
    result = select_issues.select_fleet(
        CONFIG,
        fetcher=_ok_fetcher(board),
        held_fetcher=_ok_held(),
        checker=_no_op_checker,
    )
    assert result["state"] == "candidates"
    assert result["lanes"]["lane-dispatch"]["state"] == "candidates"


def test_a_mis_shaped_graphql_response_is_could_not_fetch_never_ok():
    """The demonstrated live defect, at the fetch's own boundary: a response
    that does not carry the expected shape must never read as a clean,
    empty board."""

    def bad_run(args, timeout=90):
        return True, '{"data": {"repository": {"wrong_key": {}}}}', None

    result = select_issues._fetch_board("Digital-Process-Tools/claude-oss", run=bad_run)
    assert result["state"] == "could-not-fetch"
    assert result["issues"] == []


def test_a_well_shaped_graphql_response_is_ok_the_positive_control():
    def good_run(args, timeout=90):
        return (
            True,
            '{"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": false}, '
            '"nodes": [{"number": 7, "title": "t", "body": "b", "authorAssociation": "OWNER", '
            '"labels": {"nodes": [{"name": "lane-dispatch"}]}}]}}}}',
            None,
        )

    result = select_issues._fetch_board("Digital-Process-Tools/claude-oss", run=good_run)
    assert result["state"] == "ok"
    assert result["issues"][0]["number"] == 7
    assert result["issues"][0]["labels"] == ["lane-dispatch"]
    assert result["capped"] is False


def test_a_capped_page_is_reported_as_such():
    def good_run(args, timeout=90):
        return (
            True,
            '{"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": true}, '
            '"nodes": []}}}}',
            None,
        )

    result = select_issues._fetch_board("Digital-Process-Tools/claude-oss", run=good_run)
    assert result["state"] == "ok"
    assert result["capped"] is True
    assert result["cap_detail"]


def test_a_gh_call_failure_is_could_not_fetch():
    def bad_run(args, timeout=90):
        return False, "", "gh is not on PATH"

    result = select_issues._fetch_board("Digital-Process-Tools/claude-oss", run=bad_run)
    assert result["state"] == "could-not-fetch"
    assert "not on PATH" in result["detail"]
