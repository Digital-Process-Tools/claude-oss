"""What arrived from outside, on the statusline itself -- #1405/#1406.

`inbound_reading` is the "one module, two consumers" function #1405's own
design note calls for: `refresh()` caches it on the board's own clock, and
`scripts/next_action.py`'s `_fresh_inbound_reading` calls it directly for a
reading the loop is about to act on. This file exercises the statusline's
own half -- the reading itself, `_gh_external_pr_count`, and the render.

Every "must not fire" case is paired with a "must fire" case in the same
fixture, per this repo's own rule for a negative assertion.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _symbols(ascii_only=True):
    return statusline._symbols(ascii_only)


# --------------------------------------------------------- _gh_external_pr_count


def test_membership_pr_rows_are_not_counted_as_external(monkeypatch):
    lines = "OWNER\nMEMBER\nCOLLABORATOR\nNONE\nCONTRIBUTOR"
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: lines)
    assert statusline._gh_external_pr_count("owner/repo", 5) == 2


def test_pr_null_association_makes_the_whole_count_unreliable(monkeypatch):
    lines = "OWNER\nnull"
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: lines)
    assert statusline._gh_external_pr_count("owner/repo", 2) is None


def test_pr_fewer_rows_than_total_is_unreliable_not_undercounted(monkeypatch):
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: "NONE")
    assert statusline._gh_external_pr_count("owner/repo", 5) is None


def test_pr_no_total_to_check_against_is_unreliable():
    assert statusline._gh_external_pr_count("owner/repo", None) is None


def test_pr_zero_open_is_a_genuine_zero_not_unreliable(monkeypatch):
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: "")
    assert statusline._gh_external_pr_count("owner/repo", 0) == 0


def test_pr_argument_vector_hits_the_pulls_endpoint_not_issues(monkeypatch):
    captured = {}

    def _capture(command, timeout=25):
        captured["command"] = command
        return "OWNER"

    monkeypatch.setattr(statusline, "_run", _capture)
    statusline._gh_external_pr_count("owner/repo", 1)
    command = captured["command"]
    assert command[0] == "gh" and "api" in command
    assert any("owner/repo/pulls" in str(part) for part in command), command
    assert any("author_association" in str(part) for part in command), command
    # Unlike the issues endpoint, there is nothing to filter out here.
    assert not any("pull_request ==" in str(part) for part in command), command


# ------------------------------------------------------------- inbound_reading


def test_both_counts_measured_is_the_measured_state(monkeypatch):
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda r, t: 2)
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda r, t: 1)
    reading = statusline.inbound_reading("owner/repo", 14, 4)
    assert reading == {
        "state": "measured",
        "unruled_issues": 2,
        "unreviewed_prs": 1,
        "unanswered_comments": None,
    }


def test_either_count_failing_is_could_not_tell_not_a_partial_number(monkeypatch):
    """The must-fire control for the test above: one read failing must not
    quietly report the other's real number as though the whole thing
    measured cleanly."""
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda r, t: None)
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda r, t: 1)
    reading = statusline.inbound_reading("owner/repo", 14, 4)
    assert reading["state"] == "could-not-tell"
    assert reading["unruled_issues"] is None
    assert reading["unreviewed_prs"] == 1


def test_unanswered_comments_is_always_none(monkeypatch):
    """#1406's own scope line: no per-thread walk is built yet, and this must
    never silently render as a measured zero."""
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda r, t: 0)
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda r, t: 0)
    reading = statusline.inbound_reading("owner/repo", 0, 0)
    assert reading["unanswered_comments"] is None


# ---------------------------------------------------------------- board_from_cache


def test_board_from_cache_reads_a_measured_inbound_document():
    board = statusline.board_from_cache(
        {
            "prs": 2,
            "issues": 14,
            "fetched_at": 0,
            "inbound": {
                "state": "measured",
                "unruled_issues": 3,
                "unreviewed_prs": 1,
                "unanswered_comments": None,
            },
        }
    )
    assert board["inbound"]["unruled_issues"] == 3
    assert board["inbound"]["unreviewed_prs"] == 1


def test_board_from_cache_with_no_inbound_key_is_none():
    """A cache written before this field existed carries no `inbound` key at
    all -- the same absence a live read that failed would carry, never a
    fresh, measured zero."""
    board = statusline.board_from_cache({"prs": 2, "issues": 14, "fetched_at": 0})
    assert board["inbound"] is None


def test_board_from_cache_with_no_cache_at_all_is_none():
    board = statusline.board_from_cache(None)
    assert board["inbound"] is None


# -------------------------------------------------------------------- _inbound_field


def test_inbound_field_renders_both_counts():
    field = statusline._inbound_field(
        {"unruled_issues": 2, "unreviewed_prs": 1, "unanswered_comments": None}
    )
    assert field == "inb 2is 1pr"


def test_inbound_field_renders_question_marks_for_a_could_not_tell_reading():
    """The assertion that matters, same shape as #595's own `eis` test: an
    unmeasured count must not render as the same digit a real zero would."""
    field = statusline._inbound_field(
        {"unruled_issues": None, "unreviewed_prs": 1, "unanswered_comments": None}
    )
    assert field == "inb ?is 1pr"
    assert "0is" not in field


def test_the_must_fire_control_a_genuine_zero_is_a_measurement():
    field = statusline._inbound_field(
        {"unruled_issues": 0, "unreviewed_prs": 0, "unanswered_comments": None}
    )
    assert field == "inb 0is 0pr"
    assert field != statusline._inbound_field(
        {"unruled_issues": None, "unreviewed_prs": None, "unanswered_comments": None}
    )


def test_inbound_field_with_none_document_is_all_question_marks():
    """A cache with no `inbound` key at all (an old cache, or a repo whose
    refresh has not run since this field shipped) renders `?`, never `0`."""
    assert statusline._inbound_field(None) == "inb ?is ?pr"


# ----------------------------------------------------------------------- refresh()


def test_refresh_populates_inbound_on_the_board_clock(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".oss.json").write_text('{"repo": "owner/repo"}', encoding="utf-8")
    monkeypatch.setattr(statusline, "cache_path", lambda repo: tmp_path / "cache.json")
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 5)
    monkeypatch.setattr(statusline, "check_rollup_counts", lambda rollups, total: None)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: None)
    monkeypatch.setattr(statusline, "_gh_unlabelled_issue_counts", lambda *a, **k: None)
    monkeypatch.setattr(statusline, "_gh_default_branch_state", lambda *a, **k: None)
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "_doctor_reading", lambda root: None)
    monkeypatch.setattr(
        statusline,
        "inbound_reading",
        lambda repo, i, p: {
            "state": "measured",
            "unruled_issues": 1,
            "unreviewed_prs": 0,
            "unanswered_comments": None,
        },
    )
    document = statusline.refresh(root, now=1000.0)
    assert document["inbound"] == {
        "state": "measured",
        "unruled_issues": 1,
        "unreviewed_prs": 0,
        "unanswered_comments": None,
    }
