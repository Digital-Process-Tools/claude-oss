"""`/oss:release` publishes the Release and leaves the status line's cached
`latest` pointing at the version it just superseded, for up to `LATEST_REFRESH_AFTER`
(#549). The publish IS the event that falsifies the cache; this is the one actor
that knows at the moment it becomes true, so it invalidates rather than waiting
out a clock that cannot see it.

Reuses `statusline.cache_path`/`cache_dir` through the helper #550 exposed
(`statusline.invalidate_latest_cache`) -- this file never re-derives the cache
path, per the lane's own file-ownership split.

Third state, exercised: `invalidated` / `nothing-to-invalidate` /
`could-not-invalidate` must render as three different things, not two.
"""

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_publish  # noqa: E402
import statusline  # noqa: E402


CHANGELOG = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.3.0] - 2026-08-14

### Fixed

- The thing that was fixed (#58).
"""


def _config(**release):
    block = {
        "tag_pattern": "v{version}",
        "commit_subject": None,
        "merge_method": "squash",
    }
    block.update(release)
    return {"repo": "owner/name", "release": block}


def _repo(tmp_path, changelog=CHANGELOG, **release):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    block = {"tag_pattern": "v{version}"}
    block.update(release)
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/name", "release": block}), encoding="utf-8"
    )
    return tmp_path


def _write_cache(repo, document):
    _write_cache_raw(repo, json.dumps(document))


def _write_cache_raw(repo, raw):
    path = statusline.cache_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


posix_only = pytest.mark.skipif(
    os.name == "nt",
    reason="the fake gh is a shebang script; the platform-independent half below "
    "covers the invalidation helper itself on every platform",
)


def _fake_gh(tmp_path, exit_code=0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    impl = tmp_path / "gh_impl.py"
    impl.write_text(
        "import sys\nsys.exit({0})\n".format(exit_code),
        encoding="utf-8",
    )
    script = tmp_path / "gh"
    script.write_text(
        "#!{0}\nimport runpy\nrunpy.run_path({1!r}, run_name='__main__')\n".format(
            sys.executable, str(impl)
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ------------------------------------------------------- the helper itself, any platform


def test_a_created_release_invalidates_an_existing_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    _write_cache(
        "owner/name",
        {
            "fetched_at": 1.0,
            "latest_fetched_at": 1.0,
            "latest": {"owner/name": "0.12.0"},
        },
    )
    result = release_publish._invalidate_cache_after_publish("owner/name")
    assert result["state"] == "invalidated"
    document = json.loads(
        statusline.cache_path("owner/name").read_text(encoding="utf-8")
    )
    # Emptied/re-stamped, not deleted -- a bare delete left the document reading
    # as a legacy pre-#515 cache, whose `latest_is_due` fallback compares against
    # the unrelated `fetched_at` board stamp and can read "recently fetched"
    # almost immediately, silently undoing the invalidation (self-review finding,
    # see statusline.invalidate_latest_cache's own docstring and
    # test_invalidating_leaves_the_cache_immediately_due_again in
    # test_statusline_stale_latest_550.py for the full reproduction).
    assert document["latest"] == {}
    # `_invalidate_cache_after_publish` used the real clock (no `now` override on
    # this path), so due-ness is checked against the real clock too, immediately
    # after -- the two calls are close enough in wall-clock time that "one second
    # past due, relative to when invalidation happened" still holds.
    assert statusline.latest_is_due(document, now=time.time())


def test_the_must_not_fire_control_no_cache_is_nothing_to_invalidate(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    result = release_publish._invalidate_cache_after_publish("owner/name")
    assert result["state"] == "nothing-to-invalidate"


def test_an_unreadable_cache_is_could_not_invalidate_never_agreement(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    _write_cache_raw("owner/name", "{not json")
    result = release_publish._invalidate_cache_after_publish("owner/name")
    assert result["state"] == "could-not-invalidate"


def test_a_missing_statusline_module_is_could_not_invalidate_not_a_crash(monkeypatch):
    monkeypatch.setattr(release_publish, "statusline", None)
    result = release_publish._invalidate_cache_after_publish("owner/name")
    assert result["state"] == "could-not-invalidate"


# ------------------------------------------------------------- wired through main()


@posix_only
def test_a_successful_publish_reports_the_cache_was_invalidated(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    _write_cache(
        "owner/name",
        {
            "fetched_at": 1.0,
            "latest_fetched_at": 1.0,
            "latest": {"owner/name": "0.12.0"},
        },
    )
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    gh = _fake_gh(tmp_path / "bin")
    code = release_publish.main(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--gh",
            str(gh),
            "--execute",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == release_publish.STATE_CREATED, payload
    assert payload["cache_invalidation"]["state"] == "invalidated", payload
    assert code == release_publish.EXIT_OK


@posix_only
def test_a_failed_publish_never_touches_the_cache(tmp_path, monkeypatch, capsys):
    """Must-not-fire control: `execute` reaching `could-not-create` must not
    invalidate a cache that is still an accurate reading -- nothing was published."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    _write_cache(
        "owner/name",
        {
            "fetched_at": 1.0,
            "latest_fetched_at": 1.0,
            "latest": {"owner/name": "0.12.0"},
        },
    )
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    gh = _fake_gh(tmp_path / "bin", exit_code=1)
    release_publish.main(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--gh",
            str(gh),
            "--execute",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == release_publish.STATE_COULD_NOT_CREATE, payload
    assert "cache_invalidation" not in payload
    document = json.loads(
        statusline.cache_path("owner/name").read_text(encoding="utf-8")
    )
    assert document["latest"] == {"owner/name": "0.12.0"}


def test_a_dry_run_never_touches_the_cache(tmp_path, monkeypatch, capsys):
    """Must-not-fire control, platform-independent: without `--execute` nothing was
    published, so nothing may be invalidated."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    _write_cache(
        "owner/name",
        {
            "fetched_at": 1.0,
            "latest_fetched_at": 1.0,
            "latest": {"owner/name": "0.12.0"},
        },
    )
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    release_publish.main(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--gh",
            "gh",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == release_publish.STATE_CREATE
    assert "cache_invalidation" not in payload
    document = json.loads(
        statusline.cache_path("owner/name").read_text(encoding="utf-8")
    )
    assert document["latest"] == {"owner/name": "0.12.0"}


def test_a_skipped_release_never_touches_the_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path / "cache")
    _write_cache(
        "owner/name",
        {
            "fetched_at": 1.0,
            "latest_fetched_at": 1.0,
            "latest": {"owner/name": "0.12.0"},
        },
    )
    repo = _repo(tmp_path / "repo", create_release=False)
    release_publish.main(
        ["--repo", str(repo), "--version", "0.3.0", "--tag", "v0.3.0", "--json"]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == release_publish.STATE_SKIPPED
    assert "cache_invalidation" not in payload


def test_the_receipt_names_the_cache_state_when_present():
    receipt = release_publish.receipt(
        {
            "state": release_publish.STATE_CREATED,
            "tag": "v0.3.0",
            "repo": "owner/name",
            "cache_invalidation": {"state": "invalidated", "detail": "cleared"},
        }
    )
    assert "invalidated" in receipt


def test_the_receipt_says_nothing_about_the_cache_when_it_was_never_touched():
    receipt = release_publish.receipt(
        {"state": release_publish.STATE_CREATE, "tag": "v0.3.0", "repo": "owner/name"}
    )
    assert "cache" not in receipt.lower()
