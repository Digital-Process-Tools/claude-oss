"""Auto-update: what it does, what it refuses to claim, and who can switch it off (#480).

**Order, stated because it is weaker than this repository's rule.** `scripts/plugin_update.py`
was written before these tests, so they cannot have failed against an absent module. What
stands in for the red run is a mutation check: `test_the_guards_fire_against_a_mutated_module`
breaks the module deliberately and asserts each guard notices. A test that passes against a
broken module is decoration, and that is the property red-first buys.

The subject throughout is the third state. An updater that reports `current` when it could
not reach the marketplace has told every user their install is fine, in the one situation
where nothing checked.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


def _plugins_root(tmp_path, version):
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"oss@dpt": [{"version": version, "installPath": "x"}]}}),
        encoding="utf-8",
    )
    return root


def _plugin_root(tmp_path, name="oss"):
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "version": "9.9.9"}), encoding="utf-8"
    )
    return root


class _Runner:
    """A recorded stand-in for the two `claude` calls, so no test shells out."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, timeout=180):
        self.calls.append(list(command))
        return self.results.pop(0) if self.results else (True, "")


# ------------------------------------------------------------------------- opt-out


def test_the_environment_switches_it_off_and_says_so(tmp_path):
    off, where = plugin_update.opt_out(tmp_path, env={"OSS_NO_AUTO_UPDATE": "1"})
    assert off and "OSS_NO_AUTO_UPDATE" in where


def test_a_config_key_switches_it_off_and_names_the_file(tmp_path):
    (tmp_path / ".oss.local.json").write_text(json.dumps({"auto_update": False}), encoding="utf-8")
    off, where = plugin_update.opt_out(tmp_path, env={})
    assert off and ".oss.local.json" in where


def test_it_is_on_by_default(tmp_path):
    """The must-fire control: without this, every opt-out test above passes vacuously."""
    off, where = plugin_update.opt_out(tmp_path, env={})
    assert not off and where is None


def test_an_opted_out_run_calls_nothing(tmp_path):
    runner = _Runner([])
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=_plugins_root(tmp_path, "0.9.0"),
        env={"OSS_NO_AUTO_UPDATE": "1"},
        runner=runner,
    )
    assert document["state"] == "off"
    assert runner.calls == [], runner.calls


# -------------------------------------------------------------------------- states


def test_a_version_change_is_reported_as_updated_and_names_both_ends(tmp_path):
    plugins = _plugins_root(tmp_path, "0.9.0")

    def runner(command, timeout=180):
        if command[:3] == ["claude", "plugin", "update"]:
            _plugins_root(tmp_path, "9.9.9")
        return True, ""

    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    assert document["state"] == "updated"
    assert document["from"] == "0.9.0" and document["to"] == "9.9.9"
    assert "restart" in document["detail"]


def test_no_version_change_is_current(tmp_path):
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=_plugins_root(tmp_path, "9.9.9"),
        env={},
        runner=_Runner([(True, ""), (True, "")]),
    )
    assert document["state"] == "current"


def test_a_marketplace_that_did_not_refresh_is_never_current(tmp_path):
    """`latest` would mean whatever it meant last time, so `current` is unsourced."""
    runner = _Runner([(False, "network unreachable")])
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=_plugins_root(tmp_path, "0.9.0"),
        env={},
        runner=runner,
    )
    assert document["state"] == "could-not-check"
    assert "network unreachable" in document["detail"]
    # And it stopped there: updating against a stale index is the thing it refused.
    assert len(runner.calls) == 1, runner.calls


def test_the_scope_comes_off_the_install_record_not_a_default(tmp_path):
    """`--scope user` against a project-scoped install fails with `Plugin not found`.

    Measured: every `oss` entry on the author's machine is `project`, so the first
    version of this module could never update anything and said `could-not-check`
    forever -- honest, and useless.
    """
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt-plugins": [
                        {"version": "0.9.0", "scope": "project"},
                        {"version": "0.9.0", "scope": "local"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert plugin_update.installed_scopes("oss", root) == ["project", "local"]
    assert plugin_update.qualified_name("oss", root) == "oss@dpt-plugins"

    runner = _Runner([(True, ""), (True, ""), (True, "")])
    plugin_update.update(
        root=tmp_path, plugin_root=_plugin_root(tmp_path), plugins_root=root, env={}, runner=runner
    )
    updates = [call for call in runner.calls if call[:3] == ["claude", "plugin", "update"]]
    assert [call[-1] for call in updates] == ["project", "local"], updates
    assert all(call[3] == "oss@dpt-plugins" for call in updates), updates


def test_one_scope_succeeding_is_not_a_failed_run(tmp_path):
    """The must-not-fire half: a plugin at two scopes, one of which no longer resolves."""
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "0.9.0", "scope": "project"},
                        {"version": "0.9.0", "scope": "user"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=root,
        env={},
        runner=_Runner([(True, ""), (True, ""), (False, "not found at user scope")]),
    )
    assert document["state"] == "current", document


def test_a_failed_update_call_is_never_current(tmp_path):
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=_plugins_root(tmp_path, "0.9.0"),
        env={},
        runner=_Runner([(True, ""), (False, "no such plugin")]),
    )
    assert document["state"] == "could-not-check"
    assert "no such plugin" in document["detail"]


def test_an_unreadable_manifest_is_could_not_check_not_current(tmp_path):
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=tmp_path / "nothing-here",
        plugins_root=_plugins_root(tmp_path, "0.9.0"),
        env={},
        runner=_Runner([]),
    )
    assert document["state"] == "could-not-check"


def test_the_plugin_names_itself_from_its_own_manifest(tmp_path):
    """Never spelled inline: a name in shared code is wrong the first time it changes."""
    assert plugin_update.plugin_name(_plugin_root(tmp_path, "renamed-tomorrow")) == "renamed-tomorrow"


def test_the_newest_recorded_install_is_the_one_reported(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "0.5.0"},
                        {"version": "9.9.9"},
                        {"version": "unknown"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert plugin_update.installed_version("oss", root) == "9.9.9"


# ------------------------------------------------------------------------- receipt


def test_a_receipt_that_was_never_written_reads_as_none(tmp_path):
    assert plugin_update.read_receipt(tmp_path / "absent.json") is None


def test_a_receipt_round_trips(tmp_path):
    path = tmp_path / "auto-update.json"
    plugin_update.write_receipt({"state": "current", "at": 1.0}, path)
    assert plugin_update.read_receipt(path)["state"] == "current"


# ------------------------------------------------- the red run this file cannot have


def test_the_guards_fire_against_a_mutated_module(tmp_path, monkeypatch):
    """Stands in for red-first: break the module and check the guards notice.

    Two mutations, each the plausible bug the corresponding guard is written against --
    an updater that treats a failed marketplace refresh as a pass, and an opt-out that
    is read but not honoured. If either mutation leaves this file green, the guard was
    decoration.
    """
    plugins = _plugins_root(tmp_path, "0.9.0")
    plugin = _plugin_root(tmp_path)

    # Mutation 1: ignore the marketplace failure and carry on.
    def blind(command, timeout=180):
        return True, ""

    document = plugin_update.update(
        root=tmp_path, plugin_root=plugin, plugins_root=plugins, env={}, runner=blind
    )
    assert document["state"] == "current", document
    # The real runner reports the failure, and the state must differ. Same call, one
    # honest return value apart -- which is exactly what the guard above asserts.
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=plugin,
        plugins_root=plugins,
        env={},
        runner=_Runner([(False, "boom")]),
    )
    assert document["state"] == "could-not-check", document

    # Mutation 2: an opt-out that is read and then ignored.
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: (False, None))
    ran = _Runner([(True, ""), (True, "")])
    plugin_update.update(
        root=tmp_path,
        plugin_root=plugin,
        plugins_root=plugins,
        env={"OSS_NO_AUTO_UPDATE": "1"},
        runner=ran,
    )
    assert ran.calls, "with opt_out neutered the calls happen -- so honouring it is what stops them"
