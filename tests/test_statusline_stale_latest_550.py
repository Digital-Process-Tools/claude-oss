"""Two defects filed together as one lane slot, one file (#550).

1. `gather()` read the cached `latest` dict and discarded `latest_fetched_at`, so
   `version_status` decided `current`/`behind`/`ahead` with zero knowledge of when
   the reading was taken -- the same defect `refresh()`'s own docstring warns
   against, one function later. A comparison older than its own refresh interval
   (`LATEST_REFRESH_AFTER`) now folds into `unknown`, the same "nobody could make
   this comparison" bucket `_plugins_field` already renders as `?` -- no new
   vocabulary, per the issue's own suggested direction.

2. The `behind` and `ahead` unicode glyphs were one codepoint apart and
   distinguished reliably only by colour, printing different fields -- so
   misreading the glyph also misread which version the number referred to. They
   now differ in shape.

The incident this sibling to #549 investigates was a FRESH reading (52 minutes
old against a 60 minute interval) that was simply wrong, not a stale one -- so
every test below that exercises `gather()` carries both a stale-and-therefore-`?`
case AND a fresh-but-wrong case in the same fixture. Covering only the stale
branch would prove nothing about what was actually observed.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------- version_status/plugin_facts


def test_a_stale_comparison_is_unknown_regardless_of_what_it_would_otherwise_say():
    assert statusline.version_status("0.9.0", "0.10.0", stale=True)["state"] == "unknown"
    assert statusline.version_status("0.11.0", "0.10.0", stale=True)["state"] == "unknown"
    assert statusline.version_status("0.10.0", "0.10.0", stale=True)["state"] == "unknown"


def test_the_must_fire_control_a_fresh_comparison_is_unaffected():
    """Positive control for the assertion above: `stale=False` (the default) must
    keep deciding the comparison normally, or the parameter is not doing anything."""
    assert statusline.version_status("0.9.0", "0.10.0")["state"] == "behind"
    assert statusline.version_status("0.10.0", "0.10.0")["state"] == "current"
    assert statusline.version_status("0.9.0", "0.10.0", stale=False)["state"] == "behind"


def test_plugin_facts_threads_stale_down_to_every_plugin():
    installed = {
        "oss": {
            "version": "0.10.0",
            "repository": "https://github.com/owner/repo",
            "dependencies": [],
        },
    }
    latest_by_repo = {"owner/repo": "0.11.0"}
    stale = statusline.plugin_facts("oss", installed, latest_by_repo, stale=True)
    assert stale[0][1]["state"] == "unknown"
    fresh = statusline.plugin_facts("oss", installed, latest_by_repo, stale=False)
    assert fresh[0][1]["state"] == "behind"


# -------------------------------------------------------------------------- gather()


def _rig(monkeypatch, tmp_path, installed_version="0.13.0"):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline, "repo_config", lambda root: {"repo": "owner/repo", "default_branch": "main"}
    )
    monkeypatch.setattr(statusline, "board_is_due", lambda cache, now: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: installed_version)
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {"state": "unknown"})
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


def test_gather_marks_a_comparison_stale_once_its_own_interval_has_passed(tmp_path, monkeypatch):
    """Must-fire: a `latest` reading well past `LATEST_REFRESH_AFTER` renders `?`
    rather than a false `behind`/`ahead`."""
    _rig(monkeypatch, tmp_path, installed_version="0.13.0")
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "latest_fetched_at": now - statusline.LATEST_REFRESH_AFTER - 1,
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["plugins"][0][1]["state"] == "unknown"


def test_the_incident_itself_is_a_fresh_reading_that_is_simply_wrong(tmp_path, monkeypatch):
    """Must-not-fire control, and the whole point of pairing this file with #549:
    a reading 52 minutes old against a 60 minute interval is NOT due, so it still
    renders as a real -- and, in the incident, wrong -- comparison rather than `?`.
    Staleness alone was never going to catch this; #549 closes it by invalidating
    the cache at the moment a publish falsifies it."""
    _rig(monkeypatch, tmp_path, installed_version="0.13.0")
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "latest_fetched_at": now - (52 * 60),
        "latest": {"owner/repo": "0.12.0"},
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["plugins"][0][1]["state"] == "ahead"
    assert facts["plugins"][0][1]["installed"] == "0.13.0"


# ------------------------------------------------------------------------- glyphs


def test_the_behind_and_ahead_glyphs_are_not_one_codepoint_apart():
    symbols = statusline._symbols(False)
    behind, ahead = symbols["behind"].strip(), symbols["ahead"].strip()
    assert behind != ahead
    assert abs(ord(behind) - ord(ahead)) > 1, (
        "behind={!r} ahead={!r} are still adjacent codepoints, which is what made "
        "the incident's misread possible".format(behind, ahead)
    )


def test_the_ascii_markers_stay_unambiguous():
    """The ASCII branch was already unambiguous (`>` vs `+`) and must stay that way --
    this issue is about the Unicode branch only."""
    symbols = statusline._symbols(True)
    assert symbols["behind"] == ">"
    assert symbols["ahead"] == "+"
