"""#1768: `bin/oss-workspace` opened `claude "/oss:run"` in a repository where the
oss plugin was not enabled at all, and the very first launch ended on
`Unknown command: /oss:run`.

The launcher's own steps run from the copy its symlink points into, so every one
of them succeeds whether or not the plugin applies to the repository being
opened. Only `installed_plugins.json` can say whether it does, so the launcher now
asks `plugin_update.py --print-enablement` first, in three states: `installed`,
`not-installed`, `could-not-tell`.

Two halves are tested: `plugin_update.enablement()` against fixture registries,
and the launcher's own block, extracted verbatim out of `bin/oss-workspace` the
same way `test_workspace_plugin_progress_1648.py` extracts `oss_step`, run with a
stub python (the enablement line) and a stub `claude` on PATH that records how it
was called.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import plugin_update  # noqa: E402
import shell_probe  # noqa: E402

LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

_ATTEMPTS = shell_probe.attempts([LAUNCHER, Path(sys.executable)])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

START_MARKER = "# --- is this plugin enabled for this repository at all (#1768) ---"
END_MARKER = "# --- end of the enablement check (#1768) ---"


# ---------------------------------------------------------------- enablement()


def _plugin_root(tmp_path):
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "dependencies": ["supertool"]}), encoding="utf-8"
    )
    return root


def _registry(tmp_path, plugins):
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8"
    )
    return root


def _project(tmp_path, name="repo"):
    path = tmp_path / name
    path.mkdir()
    return path


def test_a_plugin_installed_only_for_other_projects_is_not_installed_here(tmp_path):
    """The observed case: every oss record is project/local scope for another
    directory. A user-scope dependency does not make the plugin itself present."""
    project = _project(tmp_path)
    other = _project(tmp_path, "other")
    plugins_root = _registry(
        tmp_path,
        {
            "oss@dpt-plugins": [
                {"scope": "project", "projectPath": str(other), "version": "0.42.0"},
                {"scope": "local", "projectPath": str(other), "version": "0.42.0"},
            ],
            "supertool@dpt-plugins": [{"scope": "user", "version": "0.64.0"}],
        },
    )
    assert plugin_update.enablement(project, _plugin_root(tmp_path), plugins_root) == (
        "not-installed",
        "oss@dpt-plugins",
    )


def test_a_project_record_for_this_repository_is_installed(tmp_path):
    """Positive control for the test above: one record names this project."""
    project = _project(tmp_path)
    other = _project(tmp_path, "other")
    plugins_root = _registry(
        tmp_path,
        {
            "oss@dpt-plugins": [
                {"scope": "project", "projectPath": str(other), "version": "0.42.0"},
                {"scope": "project", "projectPath": str(project), "version": "0.42.0"},
            ],
        },
    )
    assert plugin_update.enablement(project, _plugin_root(tmp_path), plugins_root) == (
        "installed",
        "oss@dpt-plugins",
    )


def test_a_user_scope_record_is_installed_everywhere(tmp_path):
    project = _project(tmp_path)
    plugins_root = _registry(tmp_path, {"oss@dpt-plugins": [{"scope": "user"}]})
    assert plugin_update.enablement(project, _plugin_root(tmp_path), plugins_root) == (
        "installed",
        "oss@dpt-plugins",
    )


def test_a_plugin_absent_from_the_registry_keeps_its_bare_name(tmp_path):
    """Nothing on the machine names a marketplace for it, so none is invented."""
    project = _project(tmp_path)
    plugins_root = _registry(tmp_path, {})
    assert plugin_update.enablement(project, _plugin_root(tmp_path), plugins_root) == (
        "not-installed",
        "oss",
    )


def test_no_registry_file_at_all_is_not_installed(tmp_path):
    """A machine that has never installed a plugin: the first launch this issue
    is about. An absent file is an answer, not a read failure."""
    project = _project(tmp_path)
    plugins_root = tmp_path / "plugins"
    assert plugin_update.enablement(project, _plugin_root(tmp_path), plugins_root) == (
        "not-installed",
        "oss",
    )


def test_claude_config_dir_registry_is_read_when_plugins_root_is_not_given(
    tmp_path, monkeypatch
):
    """#1788: `enablement()` (and every other reader sharing `_default_
    plugins_root`) must resolve the registry Claude Code itself actually
    wrote, not an unconditional `~/.claude/plugins` -- a machine with
    `$CLAUDE_CONFIG_DIR` set keeps its registry elsewhere, and reading the
    wrong path finds no file, which used to render identically to a genuine
    not-installed answer.

    `HOME` is pinned to an empty directory alongside `$CLAUDE_CONFIG_DIR` so
    a real `~/.claude/plugins` on the machine running this test can never
    supply the record instead and mask the bug this test exists to catch."""
    project = _project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    # ntpath.expanduser reads USERPROFILE before it ever looks at HOME, so
    # HOME alone is a no-op for "~" resolution on Windows -- pin both, the
    # same pairing the existing subprocess-shaped test on this file already
    # uses (`env = dict(os.environ, HOME=..., USERPROFILE=...)` above).
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    config_dir = tmp_path / "elsewhere"
    config_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    plugins_root = config_dir / "plugins"
    plugins_root.mkdir()
    (plugins_root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "oss@dpt-plugins": [
                        {"scope": "project", "projectPath": str(project)}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    assert plugin_update.enablement(project, _plugin_root(tmp_path)) == (
        "installed",
        "oss@dpt-plugins",
    )


def test_no_claude_config_dir_falls_back_to_home_dot_claude(tmp_path, monkeypatch):
    """Positive control for the test above: with `$CLAUDE_CONFIG_DIR` unset,
    resolution still falls back to `~/.claude/plugins` exactly as before --
    the fix must not stop reading the default location for the common case
    where the variable was never set at all."""
    project = _project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    # Same Windows pairing as the sibling test above: ntpath.expanduser
    # reads USERPROFILE before HOME.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    plugins_root = home / ".claude" / "plugins"
    plugins_root.mkdir(parents=True)
    (plugins_root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "oss@dpt-plugins": [
                        {"scope": "project", "projectPath": str(project)}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    assert plugin_update.enablement(project, _plugin_root(tmp_path)) == (
        "installed",
        "oss@dpt-plugins",
    )


def test_an_unreadable_registry_is_could_not_tell_not_not_installed(tmp_path):
    project = _project(tmp_path)
    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    (plugins_root / "installed_plugins.json").write_text("{not json", encoding="utf-8")
    assert plugin_update.enablement(project, _plugin_root(tmp_path), plugins_root) == (
        "could-not-tell",
        "oss",
    )


def test_print_enablement_prints_one_tab_separated_line(tmp_path):
    project = _project(tmp_path)
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"oss@dpt-plugins": [{"scope": "user"}]}}),
        encoding="utf-8",
    )
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "plugin_update.py"),
            "--root",
            str(project),
            "--print-enablement",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.decode("utf-8").splitlines() == ["installed\toss@dpt-plugins"]


# ------------------------------------------------------------- launcher block


def _require_shell():
    if BASH is None:
        pytest.skip(SHELL_REPORT)


def _extract_block():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    if START_MARKER not in launcher or END_MARKER not in launcher:
        pytest.fail(
            "bin/oss-workspace no longer carries the #1768 enablement block in the "
            "shape this test extracts -- a block that went unchecked must not read "
            "as one that agreed"
        )
    return START_MARKER + launcher.split(START_MARKER, 1)[1].split(END_MARKER, 1)[0]


def _executable(path, body):
    # write_bytes, not write_text(newline=...): that keyword is 3.10+, and the
    # floor is 3.9. Bytes also keep LF on Windows, which a shebang needs.
    path.write_bytes(body.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run_block(tmp_path, enablement, tty=False, answer="", install_ok=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "claude-calls"
    _executable(
        bin_dir / "claude",
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "{}"\nexit {}\n'.format(
            calls.as_posix(), 0 if install_ok else 1
        ),
    )
    fixture = tmp_path / "enablement.txt"
    fixture.write_bytes(enablement.encode("utf-8"))
    fake_python = _executable(
        tmp_path / "fake-python", '#!/bin/sh\ncat "{}"\n'.format(fixture.as_posix())
    )
    script = "\n".join(
        [
            "set -eu",
            "oss_steps=0",
            "oss_step_begin() { :; }",
            "oss_step() { :; }",
            "enable_is_tty() { return %d; }" % (0 if tty else 1),
            "python_bin='{}'".format(fake_python.as_posix()),
            "plugin_root=/nonexistent",
            "repo_root='{}'".format(tmp_path.as_posix()),
            'prompt="/oss:run"',
            _extract_block(),
            "echo REACHED",
        ]
    )
    # The stub directory goes in through the environment, joined with this
    # platform's own separator, the way tests/launcher_env.py does it: written
    # into the script as `C:/...:$PATH`, Git Bash splits the drive letter off at
    # the colon and never finds the stub (exit 127 on the Windows leg).
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
    done = subprocess.run(
        [BASH, "-c", script],
        input=answer.encode("utf-8"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return (
        done.returncode,
        done.stdout.decode("utf-8", "replace"),
        done.stderr.decode("utf-8", "replace"),
        recorded,
    )


def test_installed_passes_through_silently_without_calling_claude(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(tmp_path, "installed\toss@dpt-plugins\n")
    assert code == 0, err
    assert "REACHED" in out
    assert err == ""
    assert calls == []


def test_not_installed_without_a_terminal_refuses_and_names_the_command(tmp_path):
    """The reported case, non-interactive: no session is opened on a command
    that does not exist, and the exact install line is printed."""
    _require_shell()
    code, out, err, calls = _run_block(tmp_path, "not-installed\toss@dpt-plugins\n")
    assert code != 0
    assert "REACHED" not in out
    assert "claude plugin install oss@dpt-plugins --scope project" in err
    assert calls == []


def test_not_installed_at_a_terminal_installs_on_yes(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(
        tmp_path, "not-installed\toss@dpt-plugins\n", tty=True, answer="y\n"
    )
    assert code == 0, err
    assert "REACHED" in out
    assert calls == ["plugin install oss@dpt-plugins --scope project"]


def test_an_empty_answer_at_a_terminal_is_yes(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(
        tmp_path, "not-installed\toss@dpt-plugins\n", tty=True, answer="\n"
    )
    assert code == 0, err
    assert calls == ["plugin install oss@dpt-plugins --scope project"]


def test_end_of_input_at_a_terminal_is_no(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(
        tmp_path, "not-installed\toss@dpt-plugins\n", tty=True, answer=""
    )
    assert code != 0
    assert "REACHED" not in out
    assert calls == []


def test_not_installed_at_a_terminal_refuses_on_no(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(
        tmp_path, "not-installed\toss@dpt-plugins\n", tty=True, answer="n\n"
    )
    assert code != 0
    assert "REACHED" not in out
    assert "claude plugin install oss@dpt-plugins --scope project" in err
    assert calls == []


def test_a_failed_install_refuses_rather_than_opening(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(
        tmp_path,
        "not-installed\toss@dpt-plugins\n",
        tty=True,
        answer="y\n",
        install_ok=False,
    )
    assert code != 0
    assert "REACHED" not in out
    assert calls == ["plugin install oss@dpt-plugins --scope project"]


def test_a_name_that_is_not_a_plugin_key_is_never_executed(tmp_path):
    _require_shell()
    code, out, err, calls = _run_block(
        tmp_path, "not-installed\toss; touch pwned\n", tty=True, answer="y\n"
    )
    assert code == 0, err
    assert "REACHED" in out
    assert "could not tell" in err
    assert calls == []


def test_could_not_tell_warns_and_proceeds(tmp_path):
    """The third state is not a refusal: the registry could not be read, which
    is not evidence the plugin is missing."""
    _require_shell()
    code, out, err, calls = _run_block(tmp_path, "could-not-tell\toss\n")
    assert code == 0, err
    assert "REACHED" in out
    assert "could not tell" in err
    assert calls == []


def test_an_empty_answer_from_the_check_is_could_not_tell_not_installed(tmp_path):
    """A check that printed nothing never looked; it must not read as a clean
    pass, and must not refuse either."""
    _require_shell()
    code, out, err, calls = _run_block(tmp_path, "")
    assert code == 0, err
    assert "REACHED" in out
    assert "could not tell" in err
    assert "printed nothing" in err
    assert calls == []
