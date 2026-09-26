"""#1463: `_board_field`'s `eis` group and `_inbound_field`'s `is` group were the
same number, taken twice -- `inbound_reading()`'s own `unruled_issues` is exactly
what `refresh()` already stores as `issues_external`. `_board_field` stops
rendering the duplicate; `refresh()` takes the external-issue read once and feeds
both `document["issues_external"]` (the cache key stays, so an old cache still
parses) and `inbound_reading`'s `unruled_issues`, rather than calling
`_gh_external_issue_count` twice.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _symbols(ascii_only=True):
    return statusline._symbols(ascii_only)


# --------------------------------------------------------------- _board_field


def test_board_field_never_renders_eis_even_when_the_cache_carries_it():
    """The field survives in the cache (`board_from_cache` / `refresh` still
    write `issues_external`) but must not render a second time -- the `inb`
    block is the only renderer of this count now."""
    field = statusline._board_field(
        {"prs": 0, "issues": 14, "issues_external": 2, "checks": None}, _symbols()
    )
    assert field == "0pr ? . 14is"
    assert "eis" not in field


def test_board_field_with_no_issues_external_key_at_all_still_omits_eis():
    field = statusline._board_field(
        {"prs": 0, "issues": 14, "checks": None}, _symbols()
    )
    assert field == "0pr ? . 14is"
    assert "eis" not in field


# ------------------------------------------------------------------ refresh()


def test_refresh_reads_the_external_issue_count_exactly_once(tmp_path, monkeypatch):
    """The must-fire half of this issue: two renders used to cost two forge
    round trips for one fact. Count the calls directly rather than trusting
    the rendered output alone."""
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
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda repo, total: 0)

    calls = []

    def _counted(repo, total, **kwargs):
        calls.append((repo, total))
        return 2

    monkeypatch.setattr(statusline, "_gh_external_issue_count", _counted)

    document = statusline.refresh(root, now=1000.0)

    assert len(calls) == 1, calls
    assert document["issues_external"] == 2
    assert document["inbound"]["unruled_issues"] == 2


def test_a_failed_external_read_is_not_retried_a_second_time(tmp_path, monkeypatch):
    """The failure path must not fall back to a second call either -- `None`
    propagates to both consumers from the one call that came back empty."""
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
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda repo, total: 0)

    calls = []

    def _counted(repo, total, **kwargs):
        calls.append((repo, total))
        return None

    monkeypatch.setattr(statusline, "_gh_external_issue_count", _counted)

    document = statusline.refresh(root, now=1000.0)

    assert len(calls) == 1, calls
    assert document["issues_external"] is None
    assert document["inbound"]["unruled_issues"] is None
    assert document["inbound"]["state"] == "could-not-tell"


# -------------------------------------------------------- inbound_reading()


def test_inbound_reading_called_directly_still_takes_its_own_fresh_count(monkeypatch):
    """`next_action.py`'s `_fresh_inbound_reading` calls this with three
    positional arguments (no precomputed count) -- the sentinel default must
    still trigger the function's own live call in that shape."""
    calls = []

    def _counted(repo, total, **kwargs):
        calls.append((repo, total))
        return 3

    monkeypatch.setattr(statusline, "_gh_external_issue_count", _counted)
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda repo, total: 0)

    reading = statusline.inbound_reading("owner/repo", 5, 2)

    assert len(calls) == 1, calls
    assert reading["unruled_issues"] == 3


def test_inbound_reading_prefers_a_precomputed_count_over_calling_again(monkeypatch):
    calls = []

    def _counted(repo, total, **kwargs):
        calls.append((repo, total))
        return 99

    monkeypatch.setattr(statusline, "_gh_external_issue_count", _counted)
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda repo, total: 0)

    reading = statusline.inbound_reading("owner/repo", 5, 2, unruled_issues=7)

    assert len(calls) == 0, calls
    assert reading["unruled_issues"] == 7


def test_inbound_reading_honours_an_explicit_precomputed_none_without_retrying(
    monkeypatch,
):
    """A precomputed `None` (the read failed once, upstream) must not trigger a
    second live call either -- that would be the exact doubling this issue
    removes, just moved one call later."""
    calls = []

    def _counted(repo, total, **kwargs):
        calls.append((repo, total))
        return 5

    monkeypatch.setattr(statusline, "_gh_external_issue_count", _counted)
    monkeypatch.setattr(statusline, "_gh_external_pr_count", lambda repo, total: 0)

    reading = statusline.inbound_reading("owner/repo", 5, 2, unruled_issues=None)

    assert len(calls) == 0, calls
    assert reading["unruled_issues"] is None
    assert reading["state"] == "could-not-tell"
