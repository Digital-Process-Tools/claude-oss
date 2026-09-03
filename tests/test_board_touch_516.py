"""The session tells the status line when it changed the board itself (#516).

#515 shortens the board's refresh interval; this closes the window that is left, which is
the one that matters most -- the seconds after this session merges a pull request or closes
an issue, when somebody is looking straight at the line.

Two constraints shape every assertion below.

**The hook must not fetch.** It runs on the tool-result path of every `Bash` call. It marks
the cache stale and returns; the render path already forks a detached refresh when it sees a
stale cache.

**It must not mark the board stale for *now*.** GitHub's search index lags its own API by
seconds, so a refresh fired the instant a merge returns can re-cache the pre-merge counts
and then sit on them for a full interval -- staler than having done nothing. The mark
carries a settle delay, and the tests hold that the delay is real rather than zero.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import board_touch  # noqa: E402
import statusline  # noqa: E402


# ------------------------------------------------------------------- classification


def test_the_operations_that_change_this_repo_board_are_recognised():
    for command in (
        "./supertool 'gh-pr-merge:514|force'",
        "./supertool 'gh-issue-create:@-'",
        "./supertool 'gh-pr-create:@-'",
        "./supertool 'gh-pr-edit:512:@-'",
        "gh pr merge 514 --squash",
        "gh issue close 511",
        "gh issue create --title x",
        "gh pr create --fill",
        "gh issue reopen 22",
        "gh pr close 33",
    ):
        assert board_touch.changes_the_board(command), command


def test_reading_the_board_does_not_count_as_changing_it():
    """The must-not-fire half. Every one of these runs constantly in this loop, and a hook
    that marked the board stale on each would refresh on every render."""
    for command in (
        "./supertool 'gh-pr:514:status'",
        "./supertool 'gh-prs'",
        "./supertool 'gh-issues'",
        "gh pr list --state open",
        "gh issue view 511",
        "python3 -m pytest tests/ -q",
        "git status",
        "",
        None,
    ):
        assert not board_touch.changes_the_board(command), command


def test_a_merge_named_inside_prose_is_not_a_merge():
    """A command that merely mentions one -- an echo, a commit message, a grep pattern --
    is not the operation. Generous matching is right for the verb and wrong for the noun."""
    assert not board_touch.changes_the_board("git commit -m 'gh pr merge is what closed it'")
    assert not board_touch.changes_the_board("grep -r 'gh-issue-create' docs/")


# --------------------------------------------------------------------- what it does


def _payload(command, cwd):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


def _managed(tmp_path):
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/repo", "default_branch": "main"}), encoding="utf-8"
    )
    return tmp_path


def test_a_board_changing_command_marks_the_cache_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    root = _managed(tmp_path)
    now = 1_000.0
    statusline.cache_path("owner/repo").parent.mkdir(parents=True, exist_ok=True)
    statusline.cache_path("owner/repo").write_text(
        json.dumps({"fetched_at": now, "prs": 1, "issues": 23}), encoding="utf-8"
    )
    assert not statusline.board_is_due(json.loads(statusline.cache_path("owner/repo").read_text()), now)

    board_touch.main(stdin_text=_payload("gh pr merge 514 --squash", root), now=now)

    cache = json.loads(statusline.cache_path("owner/repo").read_text(encoding="utf-8"))
    assert not statusline.board_is_due(cache, now), (
        "marked stale for the instant the merge returned -- the forge's own search index "
        "lags, so the refresh this triggers would re-cache the pre-merge counts"
    )
    assert statusline.board_is_due(cache, now + board_touch.SETTLE_DELAY + 1)
    assert cache["prs"] == 1, "the counts stay readable until something replaces them"


def test_the_must_not_fire_control_a_read_leaves_the_cache_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    root = _managed(tmp_path)
    now = 1_000.0
    path = statusline.cache_path("owner/repo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": now, "prs": 1, "issues": 23}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    board_touch.main(stdin_text=_payload("./supertool 'gh-prs'", root), now=now)

    assert path.read_text(encoding="utf-8") == before


def test_a_directory_this_loop_does_not_manage_is_left_alone(tmp_path, monkeypatch):
    """No `.oss.json` above it: there is no board to mark and nothing to write."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    board_touch.main(stdin_text=_payload("gh pr merge 1 --squash", tmp_path), now=1_000.0)
    assert not (tmp_path / "cache").exists()


def test_the_hook_never_fetches(tmp_path, monkeypatch):
    """It runs after every Bash call. A network call here is `gh` latency in front of all
    of them."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    calls = []
    monkeypatch.setattr(statusline, "_run", lambda *a, **k: calls.append(a) or None)
    board_touch.main(stdin_text=_payload("gh pr merge 514 --squash", _managed(tmp_path)), now=1_000.0)
    assert calls == []


def test_it_survives_everything_a_hook_can_be_handed(tmp_path, monkeypatch):
    """A hook that raises reaches the user as a broken tool call, on every Bash command.
    Each of these is a shape the harness can produce, and none may raise."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    for text in ("", "not json", "[]", "null", json.dumps({"tool_input": None}),
                 json.dumps({"tool_input": {"command": None}}), json.dumps({"cwd": "/nope/nothing"})):
        assert board_touch.main(stdin_text=text, now=1_000.0) == 0, text


def test_a_stale_mark_does_not_survive_the_refresh_it_asked_for(tmp_path, monkeypatch):
    """The mark is consumed, not sticky: a refresh that has run must leave a cache that is
    fresh, or every render from then on forks another one."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "owner/repo"})
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_default_branch_state", lambda repo, branch: None)
    monkeypatch.setattr(statusline, "installed_plugins", lambda: {})
    root = _managed(tmp_path)
    now = 1_000.0
    statusline.cache_path("owner/repo").parent.mkdir(parents=True, exist_ok=True)
    statusline.cache_path("owner/repo").write_text(json.dumps({"fetched_at": now}), encoding="utf-8")
    board_touch.main(stdin_text=_payload("gh pr merge 514 --squash", root), now=now)

    document = statusline.refresh(root, now=now + board_touch.SETTLE_DELAY + 1)
    assert not statusline.board_is_due(document, now + board_touch.SETTLE_DELAY + 2)
