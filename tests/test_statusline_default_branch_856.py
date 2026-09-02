"""The default branch's own CI state, as a marker beside the repository name (#856).

Nothing on the status line said whether `main` itself is currently green -- the moment
right after this loop's own merge, when the branch has a fresh commit and no concluded
CI run yet, is exactly the case nothing on the line would flag. `gh-branch` answers this
in four states (GREEN, NOT GREEN either because a leg failed or because nothing has
concluded, NO RUN, UNKNOWN); this module reaches the same four states with a cheaper
call (the combined-status endpoint) rather than `gh-branch`'s own per-workflow
bookkeeping, because the render is one glyph, not a table.

Follows #550's own shape throughout: every "must not render confidently" assertion
carries a "must render" control in the same fixture, and the stale-must-fold-to-unknown
case is exercised beside the fresh-and-correct case rather than alone.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# --------------------------------------------------------- _gh_default_branch_state


def test_success_with_legs_is_green(monkeypatch):
    monkeypatch.setattr(
        statusline, "_run",
        lambda *a, **k: json.dumps({"state": "success", "total": 3}),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "green"


def test_failure_is_bad(monkeypatch):
    monkeypatch.setattr(
        statusline, "_run",
        lambda *a, **k: json.dumps({"state": "failure", "total": 3}),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "bad"


def test_error_state_is_also_bad(monkeypatch):
    """`error` is not a documented value of the COMBINED endpoint's top-level
    `state` (that enum is failure/pending/success) -- it is the per-entry
    spelling one level below what this function reads. This pins the
    defensive extra branch: an undocumented top-level `error` still reads as
    `bad` rather than falling through to `None`, the conservative direction
    to guess wrong in."""
    monkeypatch.setattr(
        statusline, "_run",
        lambda *a, **k: json.dumps({"state": "error", "total": 1}),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "bad"


def test_pending_with_legs_reporting_is_running(monkeypatch):
    monkeypatch.setattr(
        statusline, "_run",
        lambda *a, **k: json.dumps({"state": "pending", "total": 2}),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "running"


def test_zero_total_is_no_run_even_though_the_endpoint_calls_it_pending(monkeypatch):
    """GitHub's combined-status endpoint answers `pending` for BOTH "checks are
    running" and "nothing has reported at all" -- exactly #856's own motivating
    case, the instant after a merge. `total_count == 0` is what tells them apart;
    without this the moment this issue was filed for would render as `running`,
    which is a different claim (something IS in flight) from the true one
    (nothing has started)."""
    monkeypatch.setattr(
        statusline, "_run",
        lambda *a, **k: json.dumps({"state": "pending", "total": 0}),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "no-run"


def test_no_answer_from_the_forge_is_none(monkeypatch):
    monkeypatch.setattr(statusline, "_run", lambda *a, **k: None)
    assert statusline._gh_default_branch_state("owner/repo", "main") is None


def test_unparseable_answer_is_none(monkeypatch):
    monkeypatch.setattr(statusline, "_run", lambda *a, **k: "not json")
    assert statusline._gh_default_branch_state("owner/repo", "main") is None


def test_missing_repo_or_branch_never_calls_the_forge(monkeypatch):
    calls = []
    monkeypatch.setattr(statusline, "_run", lambda *a, **k: calls.append(1) or "{}")
    assert statusline._gh_default_branch_state(None, "main") is None
    assert statusline._gh_default_branch_state("owner/repo", None) is None
    assert calls == []


# ------------------------------------------------------------- _default_branch_marker


def test_marker_maps_all_four_states_to_the_documented_glyph():
    symbols = statusline._symbols(ascii_only=False)
    assert statusline._default_branch_marker("green", symbols) == symbols["ok"]
    assert statusline._default_branch_marker("bad", symbols) == symbols["bad"]
    # NOT GREEN with nothing failed (running, or nothing concluded yet) shares one
    # glyph on purpose -- both mean "not settled, look again", never "something
    # is wrong right now", which is reserved for an actual failed leg.
    assert statusline._default_branch_marker("running", symbols) == symbols["run"]
    assert statusline._default_branch_marker("no-run", symbols) == symbols["run"]
    assert statusline._default_branch_marker("unknown", symbols) == symbols["unk"]


def test_marker_is_none_when_nothing_was_ever_asked():
    """A config declaring no default branch to compare against is a deliberate
    absence of the question, not an unanswered one -- render nothing, never `?`,
    matching the channel field's own convention (#613)."""
    symbols = statusline._symbols(ascii_only=False)
    assert statusline._default_branch_marker(None, symbols) is None


def test_marker_survives_the_ascii_fallback():
    symbols = statusline._symbols(ascii_only=True)
    assert statusline._default_branch_marker("green", symbols) == symbols["ok"]
    assert statusline._default_branch_marker("bad", symbols) == symbols["bad"]


# ---------------------------------------------------------------------- render()


def _facts(default_branch_state=None, **overrides):
    facts = {
        "model": "Opus", "percent": 10, "repo_name": "claude-oss",
        "branch": "main", "default_branch": "main", "version": "0.19.0",
        "board": {}, "release": {}, "tick": {"state": "none"}, "last": "12:00",
        "plugins": [], "channel": None, "default_branch_state": default_branch_state,
    }
    facts.update(overrides)
    return facts


def test_render_puts_the_marker_beside_the_repo_name_when_green():
    line = statusline.render(_facts("green"), ascii_only=True)
    assert line.startswith("Opus . 10% | claude-oss" + statusline._symbols(True)["ok"])


def test_render_shows_bad_when_a_leg_failed():
    line = statusline.render(_facts("bad"), ascii_only=True)
    assert "claude-oss" + statusline._symbols(True)["bad"] in line


def test_render_omits_the_marker_when_nothing_was_asked():
    line = statusline.render(_facts(None), ascii_only=True)
    # No marker glyph glued onto the repo name -- plain "claude-oss" is followed
    # immediately by the separator/dot/version, never by ok/bad/run/unk.
    assert "claude-oss" + statusline._symbols(True)["ok"] not in line
    assert "claude-oss" + statusline._symbols(True)["bad"] not in line
    assert "claude-oss" + statusline._symbols(True)["run"] not in line
    assert "claude-oss" + statusline._symbols(True)["unk"] not in line
    assert line.split(" | ")[1].startswith("claude-oss ")


# --------------------------------------------------------------------- gather()


def _cache(default_branch_state, fetched_at, now, stale_after=None):
    document = {"repo": "owner/repo", "fetched_at": fetched_at, "prs": 0, "issues": 0}
    if default_branch_state is not None:
        document["default_branch_state"] = default_branch_state
    if stale_after is not None:
        document["stale_after"] = stale_after
    return document


def test_gather_reads_a_fresh_green_reading_through(tmp_path, monkeypatch):
    now = 1_000_000.0
    cache = _cache("green", now - 1, now)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(
        statusline, "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(statusline, "_scan_transcript", lambda path, n: ([], False, None))
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] == "green"


def test_gather_folds_a_stale_reading_to_unknown_even_though_it_says_green(tmp_path, monkeypatch):
    """The must-not-render-confidently case. A reading older than `REFRESH_AFTER`
    must never render as a confident `ok`, no matter what it says (#515)."""
    now = 1_000_000.0
    cache = _cache("green", now - statusline.REFRESH_AFTER - 1, now)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(
        statusline, "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: True)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(statusline, "_scan_transcript", lambda path, n: ([], False, None))
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] == "unknown"


def test_gather_folds_to_unknown_when_stale_after_says_so_even_inside_the_interval(
    tmp_path, monkeypatch
):
    """The other half of #515/#516: `stale_after` (written by the merge/close hook,
    #516) can mark a reading stale before `REFRESH_AFTER` alone would -- exactly
    the moment this issue is about, right after this loop's own merge."""
    now = 1_000_000.0
    cache = _cache("green", now - 1, now, stale_after=now - 1)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(
        statusline, "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    # board_is_due is the real function here (not stubbed), so `stale_after` is
    # actually what does the work rather than the stub answering for it.
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(statusline, "_scan_transcript", lambda path, n: ([], False, None))
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] == "unknown"


def test_gather_is_none_when_no_default_branch_is_configured(tmp_path, monkeypatch):
    now = 1_000_000.0
    cache = _cache("green", now - 1, now)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "owner/repo"})
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(statusline, "_scan_transcript", lambda path, n: ([], False, None))
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] is None
