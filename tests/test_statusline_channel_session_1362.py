"""The channel reading's cache key has no session dimension, so two sessions on
one repository -- one armed via `bin/oss-workspace`, one a bare `claude` -- can
overwrite each other's `raw_state` and each render a measurement taken by the
*other* session as its own (#1362). This is a second, session-scoped instance
of the same defect #613's own `attribution` argument already fixed at the
repository level: a reading that is real, and genuinely somebody's, but not
the reader's own.

Every "must not adopt another session's reading" assertion here is paired with
a "a session reads its own successive readings exactly as before" control in
the same fixture, the shape #550/#551/#613 already established in this
module's own suite.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------- channel_status


def test_channel_status_a_reading_from_another_session_is_cannot_determine():
    """Must-fire: a fresh, attributable, recognised reading taken by a
    DIFFERENT session must not render as this session's own state."""
    now = 1_000.0
    result = statusline.channel_status(
        "forwarding",
        "derivation",
        now - 5,
        now,
        session="session-A",
        current_session="session-B",
    )
    assert result["state"] == "cannot_determine"
    assert result["reason"] == "other-session"


def test_channel_status_the_must_not_fire_control_same_session_is_real():
    """Positive control: the identical reading, read back by the SAME session
    that took it, still renders the real state."""
    now = 1_000.0
    result = statusline.channel_status(
        "forwarding",
        "derivation",
        now - 5,
        now,
        session="session-A",
        current_session="session-A",
    )
    assert result["state"] == "forwarding"
    assert result["reason"] is None


def test_channel_status_an_unknown_session_on_either_side_does_not_fold_to_other_session():
    """Backward compatibility: a cache written before this fix carries no
    `session` key at all, and a caller with no session context of its own
    (`doctor.py`'s re-derivation, which has no session identity to compare
    against) passes `current_session=None`. Neither should manufacture a
    mismatch that was never actually observed -- self-healing at the next
    refresh, the same convention `attribution`'s own migration comment uses."""
    now = 1_000.0
    # No session recorded on the reading at all (old-shape cache).
    result = statusline.channel_status(
        "forwarding",
        "derivation",
        now - 5,
        now,
        session=None,
        current_session="session-B",
    )
    assert result["state"] == "forwarding"
    # A caller with no session identity of its own (doctor.py).
    result = statusline.channel_status(
        "forwarding",
        "derivation",
        now - 5,
        now,
        session="session-A",
        current_session=None,
    )
    assert result["state"] == "forwarding"


# ------------------------------------------------------------------- gather()


def _rig(monkeypatch, tmp_path):
    config = {"repo": "owner/repo", "default_branch": "main"}
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "repo_config", lambda root: config)
    monkeypatch.setattr(statusline, "board_is_due", lambda cache, now: False)
    monkeypatch.setattr(
        statusline, "_fork_refresh", lambda root, repo, session_id=None: None
    )
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.13.0")
    monkeypatch.setattr(
        statusline, "git_release_progress", lambda root: {"state": "unknown"}
    )
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})


def test_gather_two_sessions_on_one_repo_do_not_adopt_each_others_reading(
    tmp_path, monkeypatch
):
    """The issue's own observed shape: session A (armed) takes a `forwarding`
    reading; session B (bare) must not render it as B's own state."""
    _rig(monkeypatch, tmp_path)
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {
            "raw_state": "forwarding",
            "attribution": "derivation",
            "session": "session-A",
        },
        "channel_fetched_at": now - 5,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")

    facts = statusline.gather({"session_id": "session-B"}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "cannot_determine"
    assert facts["channel"]["reason"] == "other-session"


def test_gather_the_must_not_fire_control_same_session_reads_its_own_reading(
    tmp_path, monkeypatch
):
    """Positive control for the test above: the SAME session (A) reading back
    its own reading still sees the real state, unchanged from before this fix."""
    _rig(monkeypatch, tmp_path)
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {
            "raw_state": "forwarding",
            "attribution": "derivation",
            "session": "session-A",
        },
        "channel_fetched_at": now - 5,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")

    facts = statusline.gather({"session_id": "session-A"}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "forwarding"


def test_gather_a_reading_with_no_session_recorded_still_renders_for_anyone(
    tmp_path, monkeypatch
):
    """A cache written before this fix (no `session` key) self-heals: it is
    not treated as "somebody else's" just because nobody is recorded."""
    _rig(monkeypatch, tmp_path)
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": now - 5,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")

    facts = statusline.gather({"session_id": "session-B"}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "forwarding"


# ------------------------------------------------------------------- refresh()


def test_refresh_records_the_session_that_took_the_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(
        statusline,
        "_channel_reading",
        lambda root, config: ("forwarding", "derivation"),
    )
    now = 1_000.0
    document = statusline.refresh(str(tmp_path), now=now, session_id="session-A")
    assert document["channel"]["session"] == "session-A"
    assert document["channel"]["raw_state"] == "forwarding"


def test_refresh_the_must_not_fire_control_no_session_id_records_none(
    tmp_path, monkeypatch
):
    """Positive control: calling `refresh()` with no session id (a manual run,
    or the old call shape) still writes a document -- `session` is simply
    `None`, not a crash and not a fabricated identity."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(
        statusline,
        "_channel_reading",
        lambda root, config: ("forwarding", "derivation"),
    )
    now = 1_000.0
    document = statusline.refresh(str(tmp_path), now=now)
    assert document["channel"]["session"] is None
    assert document["channel"]["raw_state"] == "forwarding"


# ---------------------------------------------------------------- _fork_refresh


def test_fork_refresh_passes_the_session_id_to_the_detached_process(
    tmp_path, monkeypatch
):
    captured = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv

    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline.subprocess, "Popen", _FakePopen)
    statusline._fork_refresh(str(tmp_path), "owner/repo", "session-A")
    assert "--session-id" in captured["argv"]
    i = captured["argv"].index("--session-id")
    assert captured["argv"][i + 1] == "session-A"


def test_fork_refresh_the_must_not_fire_control_no_session_id_omits_the_flag(
    tmp_path, monkeypatch
):
    captured = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv

    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline.subprocess, "Popen", _FakePopen)
    statusline._fork_refresh(str(tmp_path), "owner/repo")
    assert "--session-id" not in captured["argv"]


def test_fork_refresh_a_non_string_session_id_does_not_crash_the_whole_render(
    tmp_path, monkeypatch
):
    """Self-review finding: a malformed statusline payload (e.g. `session_id`
    arriving as an int or a dict, not a string) must not blow up `Popen`'s
    argv construction and take the entire render down with it -- that would
    be strictly worse than the bug this fix closes, which only ever cost one
    field its answer. Forwarding nothing is the safe fallback, the same shape
    `_fork_refresh` already uses for a falsy `session_id`."""
    captured = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv

    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline.subprocess, "Popen", _FakePopen)
    statusline._fork_refresh(str(tmp_path), "owner/repo", 123)
    assert "--session-id" not in captured["argv"]


# ------------------------------------------------------------------------ main


def test_main_refresh_forwards_session_id_from_argv(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        statusline,
        "refresh",
        lambda root, session_id=None: calls.append((root, session_id)),
    )
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo"},
    )
    monkeypatch.setattr(statusline, "_lock_path", lambda repo: tmp_path / "x.lock")
    statusline.main(["--refresh", "--root", str(tmp_path), "--session-id", "session-A"])
    assert calls == [(str(tmp_path), "session-A")]
