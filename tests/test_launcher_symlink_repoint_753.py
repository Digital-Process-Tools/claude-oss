"""#753 point 4 -- `bin/oss-workspace` repoints `~/.local/bin/oss-workspace`
(or wherever the launcher was actually invoked through) at the CURRENTLY
installed copy, never at `$plugin_root`/`$0`'s own resolved target: a stale
link is exactly the case where the OLD launcher is the one running, so a
repoint derived from "wherever I was invoked from" would rewrite the link to
the stale target it already names, every launch, forever (the trap the issue's
own third comment names).

Extracted and run directly rather than through the whole launcher: the embedded
python between `<<'LAUNCHER_REPOINT'` and its closing line has no dependency on
anything else in this file (no `doctor` import, no project state), so running
it as its own script against real temp paths is a faithful test of the actual
mechanism without needing to fabricate two complete plugin installations end to
end just to get `$0` to be a symlink.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

_START = "<<'LAUNCHER_REPOINT'\n"
_END = "\nLAUNCHER_REPOINT\n"


def _extract():
    text = LAUNCHER.read_text(encoding="utf-8")
    start = text.index(_START) + len(_START)
    end = text.index(_END, start)
    return text[start:end]


SCRIPT = _extract()


def _run(link_path, resolved_root):
    return subprocess.run(
        [sys.executable, "-c", SCRIPT, str(link_path), str(resolved_root)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )


def _install(root, version):
    install = root / "cache" / "dpt-plugins" / "oss" / version
    (install / "bin").mkdir(parents=True)
    (install / "bin" / "oss-workspace").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return install


def test_a_correctly_pointed_link_is_left_alone(tmp_path):
    """The must-not-fire control: a link already at the current install must
    report `matched` and must not be rewritten."""
    plugins_root = tmp_path / "plugins"
    current = _install(plugins_root, "9.9.9")
    link = tmp_path / "oss-workspace"
    link.symlink_to(current / "bin" / "oss-workspace")
    before_target = link.resolve()
    result = _run(link, current)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "matched"
    assert link.resolve() == before_target


def test_a_stale_link_is_repointed_at_the_current_install(tmp_path):
    """The must-fire half: a link pointing at a SUPERSEDED install directory is
    rewritten to point at the currently resolved one."""
    plugins_root = tmp_path / "plugins"
    stale = _install(plugins_root, "9.8.0")
    current = _install(plugins_root, "9.9.9")
    link = tmp_path / "oss-workspace"
    link.symlink_to(stale / "bin" / "oss-workspace")
    result = _run(link, current)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "repointed", result.stdout
    assert link.is_symlink()
    assert Path(link.resolve()) == (current / "bin" / "oss-workspace").resolve()


def test_a_resolved_install_missing_its_own_bin_entry_is_left_untouched(tmp_path):
    """The third state: the resolved root exists but has no bin/oss-workspace of
    its own -- never repoint at a target that is not there to point at."""
    plugins_root = tmp_path / "plugins"
    stale = _install(plugins_root, "9.8.0")
    broken = plugins_root / "cache" / "dpt-plugins" / "oss" / "9.9.9"
    broken.mkdir(parents=True)
    link = tmp_path / "oss-workspace"
    link.symlink_to(stale / "bin" / "oss-workspace")
    before_target = link.resolve()
    result = _run(link, broken)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "unwritable", result.stdout
    assert link.resolve() == before_target


def test_a_dangling_link_is_reported_unwritable_not_crashed(tmp_path):
    """`os.path.realpath` on a dangling symlink does not raise -- but the
    comparison against a real install must still land on a real answer, not a
    traceback, and must not delete the link on the way."""
    plugins_root = tmp_path / "plugins"
    current = _install(plugins_root, "9.9.9")
    link = tmp_path / "oss-workspace"
    link.symlink_to(tmp_path / "nowhere" / "oss-workspace")
    result = _run(link, current)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] in ("repointed", "unwritable"), result.stdout
    assert link.is_symlink()
