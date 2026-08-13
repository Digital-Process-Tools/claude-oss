"""The bash launcher in front of doctor.py.

It exists for the case where the interpreter is missing or is a stub. That case is
the whole reason not to write `python3 ...` directly into a command file, so it is
the case the tests have to cover -- with a real stub on PATH, not a mock.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "doctor.sh"

# Resolved once, absolutely. Several tests below replace PATH to hide the Python
# interpreter from the launcher; looking bash up through that same PATH would hide
# bash too, and the failure would read as a launcher bug rather than a test bug.
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None,
    reason="no bash on this machine; on Windows CI this runs under Git Bash",
)


def run(cwd, env=None):
    environment = dict(os.environ)
    environment.update(env or {})
    return subprocess.run(
        [BASH, str(LAUNCHER)],
        cwd=str(cwd),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _make_stub(directory, name, body):
    """A fake interpreter that resolves on PATH and does not do the job."""
    path = directory / name
    path.write_text("#!/bin/sh\n{}\n".format(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_runs_and_exits_zero(tmp_path):
    done = run(tmp_path)
    assert done.returncode == 0
    assert "VERDICT" in done.stdout


def test_exits_zero_and_says_so_when_no_interpreter_exists(tmp_path):
    """An empty PATH is the extreme case: it must still print, and must state that
    the diagnostic could not run rather than implying the repo is fine.
    """
    done = run(tmp_path, env={"PATH": str(tmp_path / "empty")})
    assert done.returncode == 0
    assert "VERDICT: could not run" in done.stdout
    assert "says nothing about the repo" in done.stdout


def test_a_stub_interpreter_is_not_accepted(tmp_path):
    """This is the Windows App Execution Alias shape: `python3` exists, resolves,
    and fails when run. A `-c pass` probe would accept it; comparing a sentinel for
    equality does not.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("python3", "python"):
        _make_stub(bindir, name, "exit 9")
    done = run(tmp_path, env={"PATH": str(bindir)})
    assert done.returncode == 0
    assert "VERDICT: could not run" in done.stdout


def test_a_silent_stub_is_not_accepted(tmp_path):
    """Worse shape: exits 0 and prints nothing. Equality against the sentinel is what
    rejects it -- a returncode check would pass this straight through.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("python3", "python"):
        _make_stub(bindir, name, "exit 0")
    done = run(tmp_path, env={"PATH": str(bindir)})
    assert "VERDICT: could not run" in done.stdout


def test_reports_a_missing_doctor_without_crashing(tmp_path):
    """CLAUDE_PLUGIN_ROOT pointing somewhere with no scripts/doctor.py is an
    incomplete checkout, and must read as one.
    """
    done = run(tmp_path, env={"CLAUDE_PLUGIN_ROOT": str(tmp_path)})
    assert done.returncode == 0
    assert "doctor.py not found" in done.stdout
    assert "VERDICT: could not run" in done.stdout


def test_the_root_derivation_handles_a_windows_style_path(tmp_path):
    """The Windows legs failed on this and every POSIX leg was green.

    Under Git Bash `$0` arrives with backslashes, so `${0%/*}` strips nothing and the
    fallback resolved the plugin root against the CALLER's directory. A real Windows
    argv0 cannot be produced here, so the expansion itself is exercised -- the same
    three lines the script runs.
    """
    script = (
        'self=$1; d=${self%/*}; [ "$d" = "$self" ] && d=${self%\\\\\\\\*};'
        ' [ "$d" = "$self" ] && d=.; printf %s "$d"'
    )
    done = subprocess.run(
        [BASH, "-c", script, "sh", "D:\\\\a\\\\repo\\\\scripts\\\\doctor.sh"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    assert done.stdout == "D:\\\\a\\\\repo\\\\scripts"


def test_both_shipped_scripts_strip_either_separator():
    """Asserted on the source too: the branch is one edit from being tidied away,
    and the platform that needs it is the one nobody runs locally.
    """
    for path in (REPO_ROOT / "scripts" / "doctor.sh", REPO_ROOT / "bin" / "oss-workspace"):
        text = path.read_text(encoding="utf-8")
        assert "%\\\\*}" in text, "{} no longer strips a backslash separator".format(path.name)


def test_launcher_never_invokes_bare_python3_as_a_command(tmp_path):
    """The rule is easy to reintroduce in an edit, so it is asserted on the source."""
    text = LAUNCHER.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "candidate" in stripped or "SENTINEL" in stripped:
            continue
        assert not stripped.startswith("python3 "), line
