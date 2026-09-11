"""#1373: a stale statusline cache reading used to be reported by
`/oss:doctor` and then left exactly as stale as it was found -- nothing
refreshed or invalidated it, so `dr` (and `ch`/the default-branch marker)
kept rendering `?` until someone ran `statusline.py --refresh` by hand.

Decision recorded here and in the fix's own PR body: doctor's own check
now forks the identical background refresh a live statusline render would
have forked on its own (`statusline.fork_refresh`, a public wrapper over
the existing `_fork_refresh`), the moment it finds a stale reading --
rather than only naming a command for a human to run. This stays inside
the report-only contract (CLAUDE.md's "a diagnosis is not a repair"): the
fork starts the SAME self-healing refresh the render path already trusts,
it does not rewrite the cache's own diagnosis in place.

Must-fire (a stale cache triggers a fork) paired with must-not-fire
controls (a fresh cache does not fork; a missing `repo` does not fork
either, since there is nowhere to write a refresh to).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_statusline_unknowns as mod  # noqa: E402
import statusline  # noqa: E402


def setup_function(_):
    doctor.FINDINGS.clear()


NOW = 1_000_000.0


def test_stale_default_branch_marker_forks_a_refresh(monkeypatch, tmp_path):
    cache = {
        "fetched_at": NOW - statusline.REFRESH_AFTER - 5,
        "default_branch_state": "green",
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    calls = []
    monkeypatch.setattr(
        statusline,
        "fork_refresh",
        lambda root, repo, now=None, session_id=None: calls.append((root, repo)),
    )

    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )

    assert calls == [(str(tmp_path), "a/b")], calls


def test_fresh_cache_does_not_fork_a_refresh(monkeypatch, tmp_path):
    """Must-not-fire control: nothing is due, so nothing should fork."""
    cache = {
        "fetched_at": NOW - 5,
        "default_branch_state": "green",
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    calls = []
    monkeypatch.setattr(
        statusline,
        "fork_refresh",
        lambda root, repo, now=None, session_id=None: calls.append((root, repo)),
    )

    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )

    assert calls == []


def test_missing_repo_does_not_fork_a_refresh(monkeypatch, tmp_path):
    """Must-not-fire control: `repo_missing` means there is nowhere to
    write a refresh's cache to at all -- forking one would be pointless."""
    calls = []
    monkeypatch.setattr(
        statusline,
        "fork_refresh",
        lambda root, repo, now=None, session_id=None: calls.append((root, repo)),
    )

    mod.check_statusline_unknowns(str(tmp_path), {"repo": ""}, now=NOW)

    assert calls == []


def test_stale_warn_says_forked_when_a_fresh_refresh_actually_started(
    monkeypatch, tmp_path
):
    """#1373's own reviewer round: the WARN text must not claim a fork "just"
    happened unless `statusline.fork_refresh` actually reported starting
    one -- must-fire half of the pair below."""
    cache = {
        "fetched_at": NOW - statusline.REFRESH_AFTER - 5,
        "default_branch_state": "green",
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    monkeypatch.setattr(
        statusline,
        "fork_refresh",
        lambda root, repo, now=None, session_id=None: True,
    )

    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )

    messages = [msg for _, msg in doctor.FINDINGS]
    branch_msg = next(m for m in messages if m.startswith("statusline default-branch"))
    assert "just forked a background refresh itself" in branch_msg, branch_msg
    assert "none was started" not in branch_msg, branch_msg


def test_stale_warn_does_not_claim_a_fork_when_none_started(monkeypatch, tmp_path):
    """Must-not-fire pairing: when `fork_refresh` reports it did NOT start a
    fresh process (busy lock, failed spawn, ...), the WARN must say so
    rather than repeating the "just forked" claim regardless."""
    cache = {
        "fetched_at": NOW - statusline.REFRESH_AFTER - 5,
        "default_branch_state": "green",
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    monkeypatch.setattr(
        statusline,
        "fork_refresh",
        lambda root, repo, now=None, session_id=None: False,
    )

    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )

    messages = [msg for _, msg in doctor.FINDINGS]
    branch_msg = next(m for m in messages if m.startswith("statusline default-branch"))
    assert "none was started" in branch_msg, branch_msg
    assert "just forked a background refresh itself" not in branch_msg, branch_msg
