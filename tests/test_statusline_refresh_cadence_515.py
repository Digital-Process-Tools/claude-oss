"""Two clocks for two questions, so the board can be fresh without paying for the rest (#515).

Observed: the line read `1pr … 23is` against a tracker holding `0pr · 20is`, with the cache
372 seconds old and a 300-second TTL. Nothing had failed -- the number was as fresh as one
TTL allowed, and that TTL covered both the three calls about this repo's board and the four
about what version each installed plugin's source repository declares.

So the board now refreshes on a short clock and the published versions on a long one, with
the previous answer carried forward in between. The assertions below are mostly about the
carry: a refresh of one half must not reset the other half's age, and a version carried
forward from an earlier run must stay a real measurement rather than becoming a fresh one.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------------ which half is due


def test_the_board_is_due_on_the_short_clock():
    cache = {"fetched_at": 100.0, "latest_fetched_at": 100.0}
    assert statusline.board_is_due(cache, now=100.0 + statusline.REFRESH_AFTER + 1)
    assert not statusline.board_is_due(cache, now=100.0 + statusline.REFRESH_AFTER - 1)


def test_the_published_versions_are_due_on_the_long_one():
    cache = {"fetched_at": 100.0, "latest_fetched_at": 100.0}
    assert not statusline.latest_is_due(cache, now=100.0 + statusline.REFRESH_AFTER + 1)
    assert statusline.latest_is_due(cache, now=100.0 + statusline.LATEST_REFRESH_AFTER + 1)


def test_the_short_clock_is_shorter_than_the_long_one():
    """The split is the point; equal intervals would be the single TTL again wearing two
    names, and every assertion above would still pass."""
    assert statusline.REFRESH_AFTER < statusline.LATEST_REFRESH_AFTER


def test_a_cache_with_no_stamps_at_all_is_due_on_both():
    for cache in ({}, None):
        assert statusline.board_is_due(cache, now=0.0)
        assert statusline.latest_is_due(cache, now=0.0)


def test_a_cache_from_before_the_split_is_due_for_versions_rather_than_assumed_fresh():
    """A cache written by the previous release carries `fetched_at` and no
    `latest_fetched_at`. Reading the missing stamp as "just now" would freeze the version
    column for an hour on every upgrade; reading it as the one stamp that IS there is the
    honest answer -- that is when those versions were fetched."""
    cache = {"fetched_at": 100.0, "latest": {"owner/repo": "1.0.0"}}
    assert statusline.latest_is_due(cache, now=100.0 + statusline.LATEST_REFRESH_AFTER + 1)
    assert not statusline.latest_is_due(cache, now=100.0 + 1)


# ------------------------------------------------------------------------ the carry


def _refresh(tmp_path, monkeypatch, answers, cache=None):
    """Run a real `refresh` against a fake forge and a cache directory of our own."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "owner/repo"})
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: answers["counts"][kind])
    monkeypatch.setattr(
        statusline, "_gh_external_issue_count", lambda repo, total: answers.get("external", 0)
    )
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: answers["rollups"])
    monkeypatch.setattr(
        statusline, "installed_plugins",
        lambda project_root, plugins_root=None: {
            "oss": {"version": "0.1.0", "repository": "https://github.com/owner/repo"}
        },
    )
    asked = []

    def latest(slug):
        asked.append(slug)
        return answers["latest"]

    monkeypatch.setattr(statusline, "_latest_release", latest)
    if cache is not None:
        statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    document = statusline.refresh(".", now=answers["now"])
    return document, asked


ANSWERS = {"counts": {"pr": 0, "issue": 20}, "rollups": [], "latest": "2.0.0", "now": 1_000.0}


def test_a_board_refresh_carries_the_versions_forward_without_asking_again(tmp_path, monkeypatch):
    cache = {
        "fetched_at": 1.0,
        "latest_fetched_at": ANSWERS["now"] - 10,
        "latest": {"owner/repo": "1.0.0"},
    }
    document, asked = _refresh(tmp_path, monkeypatch, ANSWERS, cache)
    assert document["prs"] == 0 and document["issues"] == 20
    assert asked == [], "the published version was fetched again inside its own interval"
    assert document["latest"] == {"owner/repo": "1.0.0"}
    assert document["latest_fetched_at"] == cache["latest_fetched_at"], (
        "carrying a value forward must carry its age with it, or it reads as freshly measured"
    )


def test_the_must_fire_control_an_expired_version_stamp_is_asked_again(tmp_path, monkeypatch):
    cache = {
        "fetched_at": 1.0,
        "latest_fetched_at": ANSWERS["now"] - statusline.LATEST_REFRESH_AFTER - 1,
        "latest": {"owner/repo": "1.0.0"},
    }
    document, asked = _refresh(tmp_path, monkeypatch, ANSWERS, cache)
    assert asked == ["owner/repo"]
    assert document["latest"] == {"owner/repo": "2.0.0"}
    assert document["latest_fetched_at"] == ANSWERS["now"]


def test_the_board_stamp_moves_on_every_refresh(tmp_path, monkeypatch):
    cache = {"fetched_at": 1.0, "latest_fetched_at": ANSWERS["now"] - 10, "latest": {}}
    document, _ = _refresh(tmp_path, monkeypatch, ANSWERS, cache)
    assert document["fetched_at"] == ANSWERS["now"]


def test_a_version_lookup_that_fails_does_not_erase_the_one_being_carried(tmp_path, monkeypatch):
    """A network that answered once and cannot now is not a plugin with no published
    version. The old reading is kept, with its own old stamp, so the next render still has
    a comparison to make."""
    answers = dict(ANSWERS, latest=None)
    cache = {
        "fetched_at": 1.0,
        "latest_fetched_at": ANSWERS["now"] - statusline.LATEST_REFRESH_AFTER - 1,
        "latest": {"owner/repo": "1.0.0"},
    }
    document, asked = _refresh(tmp_path, monkeypatch, answers, cache)
    assert asked == ["owner/repo"]
    assert document["latest"] == {"owner/repo": "1.0.0"}
    assert document["latest_fetched_at"] == cache["latest_fetched_at"], (
        "a failed fetch must not stamp the carried value as freshly measured"
    )


def test_a_first_run_with_no_cache_asks_for_everything(tmp_path, monkeypatch):
    document, asked = _refresh(tmp_path, monkeypatch, ANSWERS)
    assert asked == ["owner/repo"]
    assert document["latest"] == {"owner/repo": "2.0.0"}
    assert document["fetched_at"] == document["latest_fetched_at"] == ANSWERS["now"]
