"""#677 -- resolve the copy actually recorded as installed for this project,
rather than a version-pinned `${CLAUDE_PLUGIN_ROOT}` that can never see its
own version move.

`resolved_plugin_root` is the "copy that answers" candidate #677's own report
names: it reads `installed_plugins.json` (via `installed_version`) for the
version actually recorded for THIS project, and the marketplace (via
`qualified_name`), and assembles the on-disk cache directory those two
together name -- returning `None`, never a guessed path, whenever any piece of
that is unavailable. `None` here is a caller's cue to fall back to the pinned
path and say so (route "pinned-root"), not a value to paper over.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


def _plugins_root(tmp_path, version, marketplace="dpt-plugins", name="oss"):
    root = tmp_path / "plugins"
    (root / "cache" / marketplace / name / version).mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps(
            {"plugins": {"{}@{}".format(name, marketplace): [{"version": version}]}}
        ),
        encoding="utf-8",
    )
    return root


def test_resolves_to_the_installed_versions_cache_directory(tmp_path):
    """MUST FIRE: the ordinary case -- a version IS recorded and the directory
    it names really is on disk."""
    plugins_root = _plugins_root(tmp_path, "9.9.9")
    resolved = plugin_update.resolved_plugin_root(
        "oss", str(tmp_path / "project"), plugins_root=plugins_root
    )
    assert resolved == plugins_root / "cache" / "dpt-plugins" / "oss" / "9.9.9"


def test_none_when_no_version_is_recorded_for_this_project(tmp_path):
    """MUST NOT FIRE: no entry applies to this project (installed_version's own
    None case) -- must not guess a path from nothing."""
    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir(parents=True, exist_ok=True)
    (plugins_root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {}}), encoding="utf-8"
    )
    resolved = plugin_update.resolved_plugin_root(
        "oss", str(tmp_path / "project"), plugins_root=plugins_root
    )
    assert resolved is None


def test_none_when_the_named_directory_does_not_exist_on_disk(tmp_path):
    """A version IS recorded, but the cache directory it names is not
    there -- must not hand back a path that doesn't resolve to anything."""
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"oss@dpt-plugins": [{"version": "9.9.9"}]}}),
        encoding="utf-8",
    )
    # deliberately no cache/dpt-plugins/oss/9.9.9 directory created
    resolved = plugin_update.resolved_plugin_root(
        "oss", str(tmp_path / "project"), plugins_root=root
    )
    assert resolved is None


def test_none_when_the_install_is_unqualified(tmp_path):
    """No marketplace on record (a local/dev install) -- this cache layout
    does not describe it, so this must not guess one."""
    root = tmp_path / "plugins"
    (root / "cache").mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"oss": [{"version": "9.9.9"}]}}),
        encoding="utf-8",
    )
    resolved = plugin_update.resolved_plugin_root(
        "oss", str(tmp_path / "project"), plugins_root=root
    )
    assert resolved is None


def test_cli_print_resolved_root_prints_the_path(tmp_path, capsys, monkeypatch):
    plugins_root = _plugins_root(tmp_path, "9.9.9")
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": "0.14.0"}), encoding="utf-8"
    )
    monkeypatch.setattr(plugin_update, "receipt_dir", lambda: tmp_path / "receipt-dir")
    monkeypatch.chdir(plugin_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    # plugin_update.resolved_plugin_root/qualified_name/installed_version all
    # default plugins_root off `~/.claude/plugins` -- point HOME at tmp_path
    # and lay the fixture out under it so the CLI path (which cannot take a
    # plugins_root override) resolves the same fixture.
    home_plugins = tmp_path / ".claude" / "plugins"
    home_plugins.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copytree(plugins_root, home_plugins)

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    rc = plugin_update.main(
        ["--root", str(project), "--print-resolved-root"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert out == str(home_plugins / "cache" / "dpt-plugins" / "oss" / "9.9.9")


def test_cli_print_resolved_root_prints_posix_separators_on_a_windows_path(monkeypatch, capsys):
    """Self-review finding: the printed path is consumed by a bash snippet in
    commands/tick.md that runs inside Git Bash on Windows, where a native
    WindowsPath prints backslashes. `scripts/doctor.py`'s own `_launcher_remedy`
    already established `.as_posix()` as this repo's convention for exactly this
    situation -- this is the positive control that the CLI mode follows it,
    built with `PureWindowsPath` so it is a real assertion on ANY host platform
    rather than one that can only fail on a Windows runner."""
    from pathlib import PureWindowsPath

    monkeypatch.setattr(plugin_update, "plugin_name", lambda: "oss")
    monkeypatch.setattr(
        plugin_update,
        "resolved_plugin_root",
        lambda name, root, plugins_root=None: PureWindowsPath(
            r"C:\Users\x\.claude\plugins\cache\dpt-plugins\oss\9.9.9"
        ),
    )
    rc = plugin_update.main(["--root", r"C:\project", "--print-resolved-root"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\\" not in out
    assert out == "C:/Users/x/.claude/plugins/cache/dpt-plugins/oss/9.9.9"


def test_cli_print_resolved_root_fails_loudly_when_it_cannot_resolve(tmp_path, capsys, monkeypatch):
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": "0.14.0"}), encoding="utf-8"
    )
    monkeypatch.chdir(plugin_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    rc = plugin_update.main(["--root", str(project), "--print-resolved-root"])
    assert rc == 1
    assert capsys.readouterr().out == ""
