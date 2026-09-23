"""`newest_cached_version` -- the newest version directory sitting under this
plugin's own cache tree, independent of which version any project is
currently pinned to (#1721).

`installed_version` answers "what THIS project has recorded"; `resolved_plugin_root`
builds a path from that answer. Neither one can tell a releaser whether the
root gate 3 just measured is the newest copy on the machine or a copy an
update elsewhere has already superseded -- that is the gap #1721 reports:
gate 3 audited with one copy, measured another, and a third was already
installed, with nothing naming that a stale root was even possible.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import plugin_update  # noqa: E402


def _plugins_root(tmp_path, versions, marketplace="dpt-plugins", name="oss"):
    root = tmp_path / "plugins"
    for version in versions:
        (root / "cache" / marketplace / name / version).mkdir(
            parents=True, exist_ok=True
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps(
            {"plugins": {"{}@{}".format(name, marketplace): [{"version": versions[0]}]}}
        ),
        encoding="utf-8",
    )
    return root


def test_returns_the_highest_version_directory_present(tmp_path):
    """MUST FIRE: several cached versions, several sort orders -- the highest
    by version-tuple comparison wins, not lexical/dict/mtime order."""
    plugins_root = _plugins_root(tmp_path, ["0.9.0", "0.10.0", "0.2.0"])
    newest = plugin_update.newest_cached_version("oss", plugins_root=plugins_root)
    assert newest == "0.10.0"


def test_none_when_the_marketplace_cannot_be_resolved(tmp_path):
    """MUST NOT FIRE: an unqualified/local install has no marketplace, and this
    cache layout does not describe it -- must not guess."""
    root = tmp_path / "plugins"
    (root / "cache").mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"oss": [{"version": "9.9.9"}]}}), encoding="utf-8"
    )
    newest = plugin_update.newest_cached_version("oss", plugins_root=root)
    assert newest is None


def test_none_when_the_cache_directory_does_not_exist(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"oss@dpt-plugins": [{"version": "9.9.9"}]}}),
        encoding="utf-8",
    )
    # deliberately no cache/dpt-plugins/oss/ directory created at all
    newest = plugin_update.newest_cached_version("oss", plugins_root=root)
    assert newest is None


def test_ignores_non_version_shaped_entries(tmp_path):
    """A stray file or a directory that does not parse as a version must not
    win by falling through some default comparison."""
    plugins_root = _plugins_root(tmp_path, ["0.5.0"])
    (plugins_root / "cache" / "dpt-plugins" / "oss" / "scratch").mkdir()
    (plugins_root / "cache" / "dpt-plugins" / "oss" / ".DS_Store").touch()
    newest = plugin_update.newest_cached_version("oss", plugins_root=plugins_root)
    assert newest == "0.5.0"


def test_single_cached_version_is_its_own_newest(tmp_path):
    plugins_root = _plugins_root(tmp_path, ["1.2.3"])
    newest = plugin_update.newest_cached_version("oss", plugins_root=plugins_root)
    assert newest == "1.2.3"


def test_cli_print_newest_cached_version_prints_the_highest_version(
    tmp_path, capsys, monkeypatch
):
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": "0.14.0"}), encoding="utf-8"
    )
    monkeypatch.chdir(plugin_dir)
    monkeypatch.setattr(
        plugin_update,
        "newest_cached_version",
        lambda name, plugins_root=None: "9.9.9" if name == "oss" else None,
    )
    rc = plugin_update.main(["--print-newest-cached-version"])
    assert rc == 0
    assert capsys.readouterr().out == "9.9.9"


def test_cli_print_newest_cached_version_fails_loudly_when_it_cannot_resolve(
    tmp_path, capsys, monkeypatch
):
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": "0.14.0"}), encoding="utf-8"
    )
    monkeypatch.chdir(plugin_dir)
    monkeypatch.setattr(
        plugin_update, "newest_cached_version", lambda name, plugins_root=None: None
    )
    rc = plugin_update.main(["--print-newest-cached-version"])
    assert rc == 1
    assert capsys.readouterr().out == ""
