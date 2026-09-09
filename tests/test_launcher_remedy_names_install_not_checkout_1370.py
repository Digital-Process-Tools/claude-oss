"""#1370: `_launcher_remedy` used to build its `ln -sf` target from
`plugin_root` -- which every real call site defaults to `PLUGIN_ROOT`, this
running process's OWN resolved location. Run from a maintainer's own clone
(this repo, or any dev checkout), that is the checkout's current tree, not a
real installed copy -- pinning every future `oss-workspace` launch on that
machine to a feature branch or a half-finished edit. `bin/oss-workspace`'s
own repoint block already refuses to derive a target this way, in as many
words: "NEVER $plugin_root or $entry_path's own resolved target: a stale
link is exactly the case where the OLD launcher is the one running."

The fix: `check_oss_workspace_launcher` resolves the real INSTALL for the
project being diagnosed (`plugin_update.resolved_plugin_root`, the same
accessor #677/#1126 already use for "the copy actually recorded as
installed for THIS project") and hands it to `_launcher_remedy` as
`install_root`. Three states for that parameter:

* not given at all (the sentinel default) -- no project context was ever
  supplied, the shape every pre-#1370 direct caller of `_launcher_remedy`
  uses. Falls back to `plugin_root`, preserving every existing unit test in
  `tests/test_launcher_path_unreadable_and_platform_remedy_333_330.py` and
  friends, which test the windows/POSIX formatting, not this resolution.
* `None` -- resolution was ATTEMPTED (a `project_dir` was given) and came
  back empty. Naming `plugin_root` here would be the exact bug: say so
  instead, and print no `ln -sf` command at all.
* a real path -- the resolved install. Used as the `ln -sf` target instead
  of `plugin_root`.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _plugin_root(tmp_path, content=b"# the running install\n", version="9.9.9"):
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    entry = root / "bin" / "oss-workspace"
    entry.write_bytes(content)
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        '{"name": "oss", "version": "%s"}' % version, encoding="utf-8"
    )
    return root


# ------------------------------------------------------- _launcher_remedy


def test_the_sentinel_default_falls_back_to_plugin_root_unchanged(tmp_path):
    """Must-not-fire control: omitting `install_root` entirely must keep the
    pre-#1370 behaviour, so every existing direct caller of this function
    (the windows/POSIX formatting tests) stays green."""
    plugin_root = _plugin_root(tmp_path)
    remedy = doctor._launcher_remedy(plugin_root, windows=False)
    assert "ln -sf" in remedy
    assert str(plugin_root) in remedy


def test_a_resolved_install_root_is_named_instead_of_plugin_root(tmp_path):
    """Must-fire positive control for the fix itself: when a real install
    root is given, the remedy names IT, never `plugin_root` -- the two are
    different directories here on purpose, mirroring a maintainer's own
    clone (`plugin_root`) versus the real installed copy (`install_root`)."""
    plugin_root = _plugin_root(tmp_path, version="9.9.9")
    install_root = tmp_path / "real-install" / "0.31.0"
    (install_root / "bin").mkdir(parents=True)
    remedy = doctor._launcher_remedy(
        plugin_root, install_root=install_root, windows=False
    )
    assert "ln -sf" in remedy
    assert str(install_root) in remedy
    assert str(plugin_root) not in remedy


def test_a_failed_resolution_names_neither_and_prints_no_command(tmp_path):
    """The other half of the fix: `install_root=None` means resolution was
    ATTEMPTED and failed -- naming `plugin_root` (the invoking checkout)
    here is precisely the bug #1370 reports. No `ln -sf` at all, and
    `plugin_root`'s own path must not appear anywhere in the remedy."""
    plugin_root = _plugin_root(tmp_path)
    remedy = doctor._launcher_remedy(plugin_root, install_root=None, windows=False)
    assert "ln -sf" not in remedy
    assert str(plugin_root) not in remedy
    assert "no installed copy" in remedy.lower()


def test_a_failed_resolution_on_windows_is_still_just_the_no_install_sentence(
    tmp_path,
):
    """The windows arm must not be reached when there is no install to name
    -- there is nothing platform-specific left to say once the target
    itself is unknown."""
    plugin_root = _plugin_root(tmp_path)
    remedy = doctor._launcher_remedy(plugin_root, install_root=None, windows=True)
    assert "ln -sf" not in remedy
    assert "Git Bash" not in remedy
    assert "no installed copy" in remedy.lower()


# ------------------------------------------------- check_oss_workspace_launcher


def test_check_names_the_resolved_install_when_project_dir_is_given(
    tmp_path, monkeypatch
):
    """End-to-end: `check_oss_workspace_launcher` given a `project_dir`
    resolves the real install via `plugin_update.resolved_plugin_root` and
    the printed remedy names it, not `plugin_root` (the checkout this
    process happens to be running from)."""
    plugin_root = _plugin_root(tmp_path)
    project_dir = tmp_path / "some-repo"
    project_dir.mkdir()
    install_root = tmp_path / "real-install" / "0.31.0"
    (install_root / "bin").mkdir(parents=True)

    monkeypatch.setattr(doctor.plugin_update, "plugin_name", lambda root: "oss")
    monkeypatch.setattr(
        doctor.plugin_update,
        "resolved_plugin_root",
        lambda name, proj, plugins_root=None: install_root,
    )

    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root,
        path=str(tmp_path / "empty-path"),
        project_dir=str(project_dir),
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert str(install_root) in message
    assert str(plugin_root) not in message


def test_check_says_no_install_could_be_resolved_rather_than_naming_the_checkout(
    tmp_path, monkeypatch
):
    """The exact scenario the issue reports: run from a maintainer's own
    clone, where no real install can be resolved for this project at all.
    The WARN must not name `plugin_root` (this checkout) as the remedy
    target."""
    plugin_root = _plugin_root(tmp_path)
    project_dir = tmp_path / "some-repo"
    project_dir.mkdir()

    monkeypatch.setattr(doctor.plugin_update, "plugin_name", lambda root: "oss")
    monkeypatch.setattr(
        doctor.plugin_update,
        "resolved_plugin_root",
        lambda name, proj, plugins_root=None: None,
    )

    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root,
        path=str(tmp_path / "empty-path"),
        project_dir=str(project_dir),
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert str(plugin_root) not in message
    assert "no installed copy" in message.lower()


def test_an_environment_gap_names_the_reason_not_a_generic_absence(
    tmp_path, monkeypatch
):
    """Self-review finding (auditor spawn, class A): `install_root is None`
    used to collapse four causes (plugin_update missing, an unreadable
    manifest, a raised OSError, and a genuinely clean resolution finding
    nothing) into one identical message. When the cause is an ENVIRONMENT
    gap -- here, this plugin's own manifest cannot be read -- the message
    must say so rather than reading exactly like the ordinary
    nothing-installed case."""
    plugin_root = _plugin_root(tmp_path)
    # Corrupt this plugin's own manifest so `plugin_update.plugin_name`
    # returns falsy -- an environment gap, not a clean "nothing installed".
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        "not json", encoding="utf-8"
    )
    project_dir = tmp_path / "some-repo"
    project_dir.mkdir()

    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root,
        path=str(tmp_path / "empty-path"),
        project_dir=str(project_dir),
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "manifest could not be read" in message
    assert str(plugin_root) not in message


def test_a_clean_resolution_finding_nothing_names_no_reason(tmp_path, monkeypatch):
    """Must-not-fire control paired with the test above: a resolution that
    ran cleanly and simply found no recorded install (the ordinary case)
    must NOT print an environment-gap sentence it did not earn."""
    plugin_root = _plugin_root(tmp_path)
    project_dir = tmp_path / "some-repo"
    project_dir.mkdir()

    monkeypatch.setattr(doctor.plugin_update, "plugin_name", lambda root: "oss")
    monkeypatch.setattr(
        doctor.plugin_update,
        "resolved_plugin_root",
        lambda name, proj, plugins_root=None: None,
    )

    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root,
        path=str(tmp_path / "empty-path"),
        project_dir=str(project_dir),
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "manifest could not be read" not in message
    assert "could not be imported" not in message
    assert "lookup itself failed" not in message


def test_no_project_dir_at_all_keeps_the_pre_1370_behaviour(tmp_path):
    """Must-not-fire control: a caller that never passes `project_dir` (no
    existing call site outside a test does this any more, but nothing here
    should regress it) keeps naming `plugin_root`, matching every existing
    test of `check_oss_workspace_launcher` that does not pass one."""
    plugin_root = _plugin_root(tmp_path)
    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root, path=str(tmp_path / "empty-path")
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert str(plugin_root) in message
