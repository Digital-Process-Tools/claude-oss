"""A triage pass marks the board cache stale when it ends (#1313).

`/oss:release` invalidates the status line's `latest` cache the moment a Release is
created, because publishing is the event that falsifies that reading
(`release_publish._invalidate_cache_after_publish`, #549). A triage pass is the same
kind of event for the *board* half of the cache: it can relabel issues, which changes
the unlabelled-issue count the status line renders, and nothing called
`statusline.mark_board_stale` for that event before now.

`scripts/board_touch.py`'s `PostToolUse` hook already marks the board stale on a
matching `gh issue edit --add-label` call made *during* a pass (its own regex covers
`edit`) -- this is a second, deliberate call at the pass's own end, so the mark does
not depend on every future labelling route matching that regex, and fires exactly once
per pass rather than once per label write.

`statusline.main()` gained a `--mark-stale [--root PATH]` CLI branch for this, mirroring
the existing `--refresh [--root PATH]` branch immediately above it -- a single, scriptable
call `commands/triage.md`'s own orchestrating session runs once, after the triager's
report comes back, rather than a mechanism embedded in the triager's own Bash grant (the
triager has no reliable single "the pass ended" moment of its own to hang a call on; the
orchestrating session does, right where it already reads the report).

Two states exercised, must-fire and must-not-fire, in the same fixture per this repo's
own convention (a negative assertion needs a positive control):

- `--mark-stale` on a repo that resolves via `.oss.json` DOES write `stale_after` --
  the must-fire case.
- Plain `statusline.main([])` with no cache-changing flag, and `--refresh` (a component
  that reads/recomputes the board rather than ending a pass that changed it), must NOT
  write `stale_after` -- the must-not-fire cases, so a harness that fires on nothing
  cannot pass this file by accident.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _repo(tmp_path, repo="owner/name"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".oss.json").write_text(json.dumps({"repo": repo}), encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------- must-fire: --mark-stale


def test_mark_stale_flag_marks_the_board_cache_stale(tmp_path, monkeypatch):
    cache_home = tmp_path / "cache"
    monkeypatch.setattr(statusline, "cache_dir", lambda: cache_home)
    repo_dir = _repo(tmp_path / "repo")

    rc = statusline.main(["--mark-stale", "--root", str(repo_dir)])

    assert rc == 0
    document = json.loads(
        statusline.cache_path("owner/name").read_text(encoding="utf-8")
    )
    assert isinstance(document.get("stale_after"), (int, float))


def test_mark_stale_flag_is_silent_and_zero_exit_when_no_repo_resolves(
    tmp_path, monkeypatch
):
    """A no-repo `--root` must never reach `mark_board_stale` at all -- checking that the
    (mocked, irrelevant) cache directory stayed empty does not discriminate this from the
    generic stdin-driven render path `main()` falls through to when the whole `--mark-stale`
    branch is deleted; that path never touches `cache_home` either, for unrelated reasons
    (self-review finding: the assertion below spies on the call directly instead, #1313)."""
    cache_home = tmp_path / "cache"
    monkeypatch.setattr(statusline, "cache_dir", lambda: cache_home)
    calls = []
    monkeypatch.setattr(
        statusline, "mark_board_stale", lambda *a, **k: calls.append((a, k))
    )
    # no .oss.json under this root -- repo_config().get("repo") is falsy
    rc = statusline.main(["--mark-stale", "--root", str(tmp_path)])

    assert rc == 0
    assert calls == []


# --------------------------------------------------------- must-not-fire: everything else


def test_plain_invocation_with_no_flag_does_not_touch_the_cache(tmp_path, monkeypatch):
    cache_home = tmp_path / "cache"
    monkeypatch.setattr(statusline, "cache_dir", lambda: cache_home)
    repo_dir = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo_dir)
    monkeypatch.setattr(sys, "stdin", None)

    statusline.main([])

    assert not cache_home.exists() or not list(cache_home.glob("*.json"))


def test_refresh_alone_is_not_the_same_event_and_does_not_write_stale_after(
    tmp_path, monkeypatch
):
    """`--refresh` recomputes the board; it is not "a triage pass ended". If it wrote
    `stale_after` on its own document, this test (and the must-fire test above) would
    both pass even if the new `--mark-stale` branch were deleted -- the control that
    keeps the must-fire test honest."""
    cache_home = tmp_path / "cache"
    monkeypatch.setattr(statusline, "cache_dir", lambda: cache_home)
    repo_dir = _repo(tmp_path / "repo")

    def _fake_refresh(root, now=None):
        # stand in for the real network-hitting refresh -- writes a plain, non-stale
        # cache document the same shape `refresh()` itself would write.
        path = statusline.cache_path("owner/name")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": 1.0}), encoding="utf-8")

    monkeypatch.setattr(statusline, "refresh", _fake_refresh)
    monkeypatch.setattr(statusline, "_lock_path", lambda repo: tmp_path / "lock")

    rc = statusline.main(
        ["--mark-stale".replace("--mark-stale", "--refresh"), "--root", str(repo_dir)]
    )

    assert rc == 0
    document = json.loads(
        statusline.cache_path("owner/name").read_text(encoding="utf-8")
    )
    assert "stale_after" not in document
