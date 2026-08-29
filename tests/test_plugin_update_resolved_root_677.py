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
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


def _set_home(monkeypatch, home):
    """Point os.path.expanduser("~") at `home`, on whichever platform is
    actually running this test (#680's own CI report -- Windows-only).

    posixpath.expanduser reads $HOME. ntpath.expanduser never looks at HOME at
    all -- it reads %USERPROFILE% first, and only falls back to
    %HOMEDRIVE%/%HOMEPATH% when that is absent (cpython's own ntpath.py, read
    directly rather than assumed). A fixture that sets only HOME is a no-op on
    Windows: the CLI still resolves against the real runner's own profile
    (observed in CI, under a runner-account temp directory), which has no
    .claude/plugins/installed_plugins.json entry matching this fixture, so
    resolved_plugin_root correctly, honestly returns None -- and rc == 1 is
    not a Windows platform defect in the production resolver, it is this
    fixture failing to construct the condition it claims to on that platform.

    Setting both env vars is not a guess from a table -- every caller measures
    immediately below whether it actually took, and skips loudly rather than
    asserting on a condition this call did not establish (CLAUDE.md's own rule
    for a permission fixture, applied here to an environment-variable one)."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    resolved = Path(os.path.expanduser("~"))
    if resolved != Path(home):
        pytest.skip(
            "os.path.expanduser('~') resolved to {!r}, not the fixture's {!r}, "
            "after setting both HOME and USERPROFILE -- what goes untested here "
            "is this test's own home-directory fixture on whatever platform "
            "produced this, not the production resolver".format(str(resolved), str(home))
        )


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
    _set_home(monkeypatch, tmp_path)
    # plugin_update.resolved_plugin_root/qualified_name/installed_version all
    # default plugins_root off `~/.claude/plugins` -- point the home directory
    # at tmp_path (on whichever env var this platform's expanduser() actually
    # reads -- see _set_home) and lay the fixture out under it, so the CLI
    # path (which cannot take a plugins_root override) resolves the same
    # fixture.
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
    # .as_posix() on BOTH sides, not str() -- the consumer decides this, not
    # which spelling makes the assertion pass. commands/tick.md's step 1 feeds
    # this output straight into a bash snippet (`[ -d "$RESOLVED_ROOT" ]`, then
    # `"$DOCTOR_ROOT/scripts/doctor.py"`), which runs under Git Bash on
    # Windows -- the same Git-Bash consumer scripts/doctor.py's own
    # _launcher_remedy already writes POSIX-separator paths for, and the exact
    # reason main()'s --print-resolved-root mode emits .as_posix() rather than
    # str() (see the self-review fix in this file's own history, and the
    # dedicated PureWindowsPath regression test below). str() on the expected
    # side compared correctly on POSIX only by coincidence -- both sides
    # happen to already use forward slashes there -- and diverged the moment a
    # real Windows CI leg supplied WindowsPath separators on the actual side,
    # which is the second, separate defect in this fixture #680's CI turned up
    # after the first (the HOME/USERPROFILE fixture) was fixed. Asserting
    # .as_posix() on both sides is platform-honest rather than a one-off
    # patch: it is correct on whichever OS actually runs this test, not tuned
    # to the one this session happens to be on.
    assert out == (home_plugins / "cache" / "dpt-plugins" / "oss" / "9.9.9").as_posix()


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
    # Same reasoning as _set_home's docstring: on Windows, HOME alone is a
    # no-op, so this used to fall through to the real runner's own profile
    # rather than the deliberately-empty tmp_path this test means to point
    # at -- a coincidence (the real profile happening to lack a matching
    # install) standing in for a real assertion, on exactly the platform
    # least likely to be caught locally.
    _set_home(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    rc = plugin_update.main(["--root", str(project), "--print-resolved-root"])
    assert rc == 1
    assert capsys.readouterr().out == ""
