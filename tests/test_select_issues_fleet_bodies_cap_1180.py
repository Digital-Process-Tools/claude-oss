"""#1180 -- the default fleet print omits bodies (they push the payload
over the harness's output cap), and a bounded second call fetches just the
bodies of the groups the caller actually kept.
"""

import json
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


def _select_fleet(issues, **kwargs):
    return select_issues.select_fleet(
        CONFIG,
        fetcher=_fetcher(issues),
        held_fetcher=_held(),
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        **kwargs,
    )


# --------------------------------------------------------------- must-fire


def test_include_bodies_false_omits_body_fields_from_members():
    board = [
        _issue(
            1,
            "a body nobody needs to see by default",
            ["priority-high", "lane-dispatch"],
            lane_patterns=["scripts/a.py"],
        )
    ]
    result = _select_fleet(board, include_bodies=False)
    member = result["lanes"]["lane-dispatch"]["groups"]["groups"][0]["members"][0]
    assert "body" not in member
    assert "body_truncated" not in member
    assert "body_length" not in member


def test_omitting_bodies_shrinks_the_serialized_payload():
    long_body = "x" * 5000
    board = [
        _issue(
            n,
            long_body,
            ["priority-high", "lane-dispatch"],
            lane_patterns=["scripts/{0}.py".format(n)],
        )
        for n in range(1, 4)
    ]
    with_bodies = _select_fleet(board, include_bodies=True)
    without_bodies = _select_fleet(board, include_bodies=False)
    size_with = len(json.dumps(with_bodies))
    size_without = len(json.dumps(without_bodies))
    assert size_without < size_with
    # the whole point: even one attached, capped (BODY_CAP) body dominates
    # the payload relative to the rest of a group's own fields
    assert size_with - size_without > 1500


# ------------------------------------------------------------ positive control


def test_include_bodies_defaults_true_so_existing_callers_are_unaffected():
    board = [
        _issue(
            2,
            "still here by default",
            ["priority-high", "lane-dispatch"],
            lane_patterns=["scripts/b.py"],
        )
    ]
    result = _select_fleet(board)
    member = result["lanes"]["lane-dispatch"]["groups"]["groups"][0]["members"][0]
    assert "body" in member
    assert member["body_length"] == len("still here by default")


# ----------------------------------------------------------- CLI wiring


def test_main_default_mode_calls_select_fleet_with_bodies_disabled(
    monkeypatch, tmp_path
):
    (tmp_path / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "Digital-Process-Tools/claude-oss",
                "default_branch": "main",
                "labels": DECLARED,
            }
        )
    )
    calls = {}

    def fake_select_fleet(config, repo_root=".", **kwargs):
        calls["kwargs"] = kwargs
        return {"state": "none-available", "why": None}

    monkeypatch.setattr(select_issues, "select_fleet", fake_select_fleet)
    select_issues.main(["--repo", str(tmp_path)])
    assert calls["kwargs"].get("include_bodies") is False


# ----------------------------------------------------------- --bodies mode


def test_issue_bodies_fetches_exactly_the_requested_numbers():
    board = [
        _issue(1, "body one"),
        _issue(2, "body two"),
    ]
    result = select_issues._issue_bodies(CONFIG, [1, 2], fetcher=_fetcher(board))
    assert result["state"] == "ok"
    assert result["not_found"] == []
    assert "body one" in result["bodies"]["1"]["body"]
    assert "body two" in result["bodies"]["2"]["body"]
    assert result["bodies"]["1"]["body"].startswith(
        select_issues.BODY_FENCE_OPEN_PREFIX
    )


def test_issue_bodies_reports_a_requested_number_not_on_the_board():
    board = [_issue(1, "body one")]
    result = select_issues._issue_bodies(CONFIG, [1, 99], fetcher=_fetcher(board))
    assert result["state"] == "ok"
    assert result["not_found"] == [99]
    assert "99" not in result["bodies"]


def test_issue_bodies_reports_could_not_fetch_when_the_board_read_fails():
    def failing_fetch(repo_slug, per=100, run=None):
        return {
            "state": "could-not-fetch",
            "issues": [],
            "capped": False,
            "cap_detail": "",
            "detail": "gh is not on PATH",
        }

    result = select_issues._issue_bodies(CONFIG, [1], fetcher=failing_fetch)
    assert result["state"] == "could-not-fetch"
    assert result["bodies"] == {}
    assert "gh is not on PATH" in result["detail"]
