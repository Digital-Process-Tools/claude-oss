"""A `latest` comparison merely DUE must not fold to `unknown` before it is
actually stale (#1464).

`gather()` used to fold the `latest` plugin-version comparison to `unknown` the
INSTANT `latest_fetched_at`'s age crossed `LATEST_REFRESH_AFTER` (3600s) -- even
though the background refresh a due reading provokes can take up to ~60s to
land. For that whole gap the statusline showed `plug 0check 4unknown` on data
that was correct a second earlier and is correct again a minute later.

The fix (#1464): `gather()` keeps rendering the last-known comparison while a
refresh is merely due, and only folds to `unknown` when (a) a refresh was
attempted and failed since the last success (`latest_refresh_failed_at` newer
than the last `latest_fetched_at`), or (b) the reading is well past due --
past `LATEST_UNKNOWN_AFTER`, `2 * LATEST_REFRESH_AFTER`. A `latest` entry that
was never fetched at all is unaffected by any of this -- see
`test_statusline_stale_latest_550.py`'s own `version_status`/`plugin_facts`
coverage for that path, which this file does not repeat.

Every "must not fold" case here is paired with a "must fold" case in the same
fixture shape, per this repo's own rule against a negative assertion with no
positive control.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _rig(monkeypatch, tmp_path, installed_version="0.13.0"):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "board_is_due", lambda cache, now: False)
    monkeypatch.setattr(
        statusline, "_fork_refresh", lambda root, repo, session_id=None: None
    )
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: installed_version)
    monkeypatch.setattr(
        statusline, "git_release_progress", lambda root: {"state": "unknown"}
    )
    monkeypatch.setattr(
        statusline,
        "installed_plugins",
        lambda root: {
            "oss": {
                "version": installed_version,
                "repository": "https://github.com/owner/repo",
                "dependencies": [],
            }
        },
    )


# --------------------------------------------------------------- latest_is_unknown


def test_a_reading_merely_due_is_not_yet_unknown():
    """Must-not-fire: strictly between 1x and 2x the refresh interval, no recorded
    failure -- still the last-known state, not `unknown`."""
    cache = {
        "fetched_at": 1000.0,
        "latest_fetched_at": 1000.0,
        "latest": {"owner/repo": "0.12.0"},
    }
    now = 1000.0 + statusline.LATEST_REFRESH_AFTER + 30
    assert not statusline.latest_is_unknown(cache, now)


def test_a_reading_past_the_unknown_boundary_is_unknown():
    """Must-fire control for the case above: past `LATEST_UNKNOWN_AFTER`
    (2x the refresh interval), with no fresher reading and no recorded
    failure, the benefit of the doubt runs out."""
    cache = {
        "fetched_at": 1000.0,
        "latest_fetched_at": 1000.0,
        "latest": {"owner/repo": "0.12.0"},
    }
    now = 1000.0 + statusline.LATEST_UNKNOWN_AFTER + 1
    assert statusline.latest_is_unknown(cache, now)


def test_a_recorded_failed_refresh_folds_early_even_within_the_grace_window():
    """Must-fire: a refresh was attempted and failed since the last success --
    that is no longer "merely due", it is known-unconfirmable right now, so it
    folds even though the age alone would still be inside the grace window."""
    cache = {
        "fetched_at": 1000.0,
        "latest_fetched_at": 1000.0,
        "latest_refresh_failed_at": 1000.0 + statusline.LATEST_REFRESH_AFTER + 5,
        "latest": {"owner/repo": "0.12.0"},
    }
    now = 1000.0 + statusline.LATEST_REFRESH_AFTER + 30
    assert statusline.latest_is_unknown(cache, now)


def test_a_failed_refresh_older_than_the_last_success_does_not_fold():
    """Must-not-fire control for the case above: a failure recorded BEFORE the
    most recent successful fetch is stale news, superseded by the success that
    came after it, so it must not fold a reading that is otherwise fine."""
    cache = {
        "fetched_at": 2000.0,
        "latest_fetched_at": 2000.0,
        "latest_refresh_failed_at": 1000.0,
        "latest": {"owner/repo": "0.12.0"},
    }
    now = 2000.0 + statusline.LATEST_REFRESH_AFTER + 30
    assert not statusline.latest_is_unknown(cache, now)


# ------------------------------------------------------------------------- gather()


def test_gather_keeps_the_last_known_state_while_merely_due(tmp_path, monkeypatch):
    """Must-not-fire, end to end: `gather()` itself must not render `unknown`
    for a reading that is merely due."""
    _rig(monkeypatch, tmp_path, installed_version="0.13.0")
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "latest_fetched_at": now - statusline.LATEST_REFRESH_AFTER - 30,
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["plugins"][0][1]["state"] == "ahead"


def test_gather_folds_to_unknown_once_well_past_due(tmp_path, monkeypatch):
    """Must-fire control for the case above: past `LATEST_UNKNOWN_AFTER`,
    `gather()` still folds to `unknown`."""
    _rig(monkeypatch, tmp_path, installed_version="0.13.0")
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "latest_fetched_at": now - statusline.LATEST_UNKNOWN_AFTER - 1,
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["plugins"][0][1]["state"] == "unknown"


def test_gather_folds_to_unknown_on_a_recorded_failed_refresh(tmp_path, monkeypatch):
    """Must-fire control: a recorded failed refresh folds `gather()`'s own
    output even while merely due, not only once far stale."""
    _rig(monkeypatch, tmp_path, installed_version="0.13.0")
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "latest_fetched_at": now - statusline.LATEST_REFRESH_AFTER - 30,
        "latest_refresh_failed_at": now - 20,
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["plugins"][0][1]["state"] == "unknown"


# ------------------------------------------------------------------------ refresh()


def test_refresh_records_a_failure_when_a_due_ask_gets_nothing_back(
    monkeypatch, tmp_path
):
    """A failed refresh must record that it failed, rather than silently
    leaving the old stamp in place -- indistinguishable from "not due yet"."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": None},
    )
    monkeypatch.setattr(
        statusline,
        "installed_plugins",
        lambda root: {
            "oss": {
                "version": "0.13.0",
                "repository": "https://github.com/owner/repo",
                "dependencies": [],
            }
        },
    )
    monkeypatch.setattr(statusline, "_latest_release", lambda slug: None)
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: None)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, n: None)
    monkeypatch.setattr(
        statusline, "_gh_unlabelled_issue_counts", lambda repo, n, pl, ll: None
    )
    monkeypatch.setattr(statusline, "check_rollup_counts", lambda rollups, prs: None)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: None)
    monkeypatch.setattr(statusline, "inbound_reading", lambda repo, i, p: None)
    monkeypatch.setattr(statusline, "_gh_default_branch_state", lambda repo, b: None)
    monkeypatch.setattr(
        statusline, "_channel_reading", lambda root, config: (None, None)
    )
    monkeypatch.setattr(statusline, "_doctor_reading", lambda root: None)
    now = 1000.0 + statusline.LATEST_REFRESH_AFTER + 1
    previous = {
        "fetched_at": 1000.0,
        "latest_fetched_at": 1000.0,
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").parent.mkdir(parents=True, exist_ok=True)
    statusline.cache_path("owner/repo").write_text(
        json.dumps(previous), encoding="utf-8"
    )
    document = statusline.refresh("root", now=now)
    assert document["latest_refresh_failed_at"] == now
    assert document["latest"] == {"owner/repo": "0.12.0"}
    assert document["latest_fetched_at"] == 1000.0


def test_refresh_clears_a_prior_failure_on_a_successful_ask(monkeypatch, tmp_path):
    """Must-not-fire control for the case above: a successful fetch clears any
    previously-recorded failure, rather than leaving a stale failure marker
    that would keep folding a now-good reading to `unknown`."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": None},
    )
    monkeypatch.setattr(
        statusline,
        "installed_plugins",
        lambda root: {
            "oss": {
                "version": "0.13.0",
                "repository": "https://github.com/owner/repo",
                "dependencies": [],
            }
        },
    )
    monkeypatch.setattr(statusline, "_latest_release", lambda slug: "0.14.0")
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: None)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, n: None)
    monkeypatch.setattr(
        statusline, "_gh_unlabelled_issue_counts", lambda repo, n, pl, ll: None
    )
    monkeypatch.setattr(statusline, "check_rollup_counts", lambda rollups, prs: None)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: None)
    monkeypatch.setattr(statusline, "inbound_reading", lambda repo, i, p: None)
    monkeypatch.setattr(statusline, "_gh_default_branch_state", lambda repo, b: None)
    monkeypatch.setattr(
        statusline, "_channel_reading", lambda root, config: (None, None)
    )
    monkeypatch.setattr(statusline, "_doctor_reading", lambda root: None)
    now = 1000.0 + statusline.LATEST_REFRESH_AFTER + 1
    previous = {
        "fetched_at": 1000.0,
        "latest_fetched_at": 1000.0,
        "latest_refresh_failed_at": 900.0,
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").parent.mkdir(parents=True, exist_ok=True)
    statusline.cache_path("owner/repo").write_text(
        json.dumps(previous), encoding="utf-8"
    )
    document = statusline.refresh("root", now=now)
    assert document["latest_refresh_failed_at"] is None
    assert document["latest"] == {"owner/repo": "0.14.0"}
    assert document["latest_fetched_at"] == now
