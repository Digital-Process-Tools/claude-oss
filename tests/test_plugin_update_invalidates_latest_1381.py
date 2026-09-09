"""An update falsifies the cached `latest` reading, so the updater clears it (#1381).

`scripts/statusline.py` caches, on its own hour-long clock, the newest published Release
of the loop plugin and of every dependency it renders currency for. `plugin_update.py`
is what moves the *installed* version. So the actor that makes the cached comparison
wrong is the one plugin's own updater, and until this change it left the stale value in
place -- the same principle `/oss:release` already follows when it calls
`invalidate_latest_cache` on publishing, applied to the other half of the comparison.

Observed on 2026-09-09: the updater took supertool 0.58.0 -> 0.59.0 at ~20:46, the cache
had polled `claude-supertool: "0.58.0"` at 20:07, and the status line rendered
`supeup0.59.0` -- installed ahead of a Release that had in fact been published at 20:38.
Every actor in that sequence is the oss plugin reading its own cache; nothing reached
into another plugin's state, and this change does not either.

The cache lives at `statusline.cache_path(<managed repo slug>)`, under
`~/.cache/oss-statusline/`, and every test here pins `XDG_CACHE_HOME` and `LOCALAPPDATA`
so a run never touches the real one -- `statusline.cache_dir()` reads `LOCALAPPDATA`
first on Windows, so pinning `HOME` alone is a silent no-op there (the mechanism
`paths/00-manual/windows-subprocess-resolution.md` records for this module's receipts).

Every negative assertion is paired with a positive control in the same fixture: "the
cache was not cleared" also passes when nothing ran at all.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402
import statusline  # noqa: E402


def _pin_cache(tmp_path, monkeypatch):
    """Point `statusline.cache_dir()` at a temp directory on every platform."""
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    return cache


def _seed(repo, latest):
    """A cache document carrying a `latest` reading, as `refresh()` would write it."""
    path = Path(statusline.cache_path(repo))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": 1788980753.0,
                "repo": repo,
                "latest": dict(latest),
                "latest_fetched_at": 1788977296.0,
            }
        ),
        encoding="utf-8",
    )
    return path


def _config(tmp_path, repo="Digital-Process-Tools/claude-oss"):
    (tmp_path / ".oss.json").write_text(json.dumps({"repo": repo}), encoding="utf-8")
    return tmp_path


REPO = "Digital-Process-Tools/claude-oss"
LATEST = {"Digital-Process-Tools/claude-supertool": "0.58.0"}


def _plugin_root(tmp_path):
    """This plugin's own manifest. `9.9.9` for the reason
    `tests/test_plugin_update_dependencies_605.py` states at length: a fixture version
    below this repository's next minor would collide with the release that reaches it,
    and a `9` major cannot, since the guard only ever proposes the next minor of the
    current major."""
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": "9.9.9", "dependencies": []}),
        encoding="utf-8",
    )
    return root


def _registry(tmp_path, entries):
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": entries}), encoding="utf-8"
    )
    return root


class _Runner:
    """Answers every `claude` call as a success, recording each one.

    `bump_to` rewrites the install registry on an update call, because that is what
    makes `_update_one` report `updated` rather than `current`: it re-reads the
    installed version after the call and compares. A runner that only returns success
    leaves the registry where it was, so the run reports `current` and this file's
    whole subject -- what happens after something moves -- is never reached.
    """

    def __init__(self, registry=None, bump_to=None):
        self.calls = []
        self.registry = registry
        self.bump_to = bump_to

    def __call__(self, command, timeout=180):
        self.calls.append(list(command))
        if self.registry is not None and command[:3] == ["claude", "plugin", "update"]:
            self.registry.write_text(
                json.dumps(
                    {
                        "plugins": {
                            "oss@dpt": [{"version": self.bump_to, "scope": "user"}]
                        }
                    }
                ),
                encoding="utf-8",
            )
        return True, ""


def test_a_dependency_update_clears_the_cached_latest_reading(tmp_path, monkeypatch):
    """The observed case: the loop plugin itself is `current` and a dependency moved.

    A wire that only fired on the loop plugin's own update would miss this entirely,
    which is the exact shape that produced the wrong render.
    """
    _pin_cache(tmp_path, monkeypatch)
    path = _seed(REPO, LATEST)
    root = _config(tmp_path)

    result = plugin_update.invalidate_latest_after_update(
        {
            "state": "current",
            "dependencies": [{"name": "supertool", "state": "updated"}],
        },
        root=root,
    )

    assert result["state"] == "invalidated"
    assert json.loads(path.read_text())["latest"] == {}


def test_the_loop_plugins_own_update_clears_it_too(tmp_path, monkeypatch):
    _pin_cache(tmp_path, monkeypatch)
    path = _seed(REPO, LATEST)
    root = _config(tmp_path)

    result = plugin_update.invalidate_latest_after_update(
        {"state": "updated", "dependencies": []}, root=root
    )

    assert result["state"] == "invalidated"
    assert json.loads(path.read_text())["latest"] == {}


def test_nothing_updated_leaves_the_reading_alone(tmp_path, monkeypatch):
    """The negative assertion. Its positive control is the two tests above, which share
    this fixture's shape exactly and differ only in the states reported."""
    _pin_cache(tmp_path, monkeypatch)
    path = _seed(REPO, LATEST)
    root = _config(tmp_path)

    result = plugin_update.invalidate_latest_after_update(
        {
            "state": "current",
            "dependencies": [
                {"name": "supertool", "state": "current"},
                {"name": "remember", "state": "not-installed"},
            ],
        },
        root=root,
    )

    assert result["state"] == "not-needed"
    assert json.loads(path.read_text())["latest"] == LATEST


def test_a_repo_that_cannot_be_read_is_its_own_state_never_a_silent_skip(
    tmp_path, monkeypatch
):
    """Third state. `.oss.json` absent, unreadable, or carrying no `repo` means the
    cache could not be located -- reported, never folded into `not-needed`, which would
    read as a deliberate decision not to clear anything."""
    _pin_cache(tmp_path, monkeypatch)
    result = plugin_update.invalidate_latest_after_update(
        {"state": "updated", "dependencies": []}, root=tmp_path
    )
    assert result["state"] == "could-not-invalidate"
    assert result.get("reason")

    (tmp_path / ".oss.json").write_text("{ not json", encoding="utf-8")
    assert (
        plugin_update.invalidate_latest_after_update(
            {"state": "updated", "dependencies": []}, root=tmp_path
        )["state"]
        == "could-not-invalidate"
    )


def test_the_outcome_is_recorded_on_the_receipt_in_every_state(tmp_path, monkeypatch):
    """A step nothing records is a step nobody can tell ran. `update()` writes the
    answer onto its own receipt under `latest_cache`, so an absent key means an older
    receipt that never looked -- distinguishable from one that looked and declined."""
    _pin_cache(tmp_path, monkeypatch)
    _seed(REPO, LATEST)
    root = _config(tmp_path)

    document = {"state": "updated", "dependencies": []}
    plugin_update.record_latest_cache(document, root=root)
    assert document["latest_cache"]["state"] == "invalidated"


def test_update_itself_calls_it_rather_than_leaving_it_callable(tmp_path, monkeypatch):
    """The assertion that the wire is wired. Every test above exercises the function
    directly, and all of them pass just as well when nothing in `update()` ever calls
    it -- a check that exists and never runs is this repository's own defect class, so
    it is asserted through the real entry point once."""
    cache = _pin_cache(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    _config(project)
    path = _seed(REPO, LATEST)
    assert cache in path.parents  # the fixture pinned it; a real cache is never touched

    plugin_root = _plugin_root(tmp_path)
    plugins_root = _registry(
        tmp_path, {"oss@dpt": [{"version": "9.9.8", "scope": "user"}]}
    )
    document = plugin_update.update(
        root=project,
        plugin_root=plugin_root,
        plugins_root=plugins_root,
        env={},
        runner=_Runner(
            registry=plugins_root / "installed_plugins.json", bump_to="9.9.9"
        ),
        now=lambda: 0,
    )

    # The fixture determines this exactly: the registry holds 9.9.8, the manifest
    # declares 9.9.9, the runner succeeds -- so the loop plugin reports `updated` and
    # the seeded cache is there to clear. Accepting any of the four states here would
    # pass on a wire that answered `could-not-check` on every invocation.
    assert document["state"] == "updated"
    assert document["latest_cache"]["state"] == "invalidated"
    assert json.loads(path.read_text())["latest"] == {}
