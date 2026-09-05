"""#590 follow-up: a vanished current working directory must not take the
whole module down.

Deriving `REPO` from `Path.cwd()` (#590) means every invocation reads the
process's own cwd at import time, before `argparse` has even parsed
`--dir`/`--changelog` -- fold included, which never uses `REPO` at all.
`os.getcwd()` raises `FileNotFoundError` when that directory has been
removed out from under the process, which is a real race in this loop's own
worktree lifecycle (see `CLAUDE.md`'s red-check-worktree note), not a
hypothetical one. Before the guard this module-level statement crashed the
import with an unhandled traceback -- exit 1, empty stdout, indistinguishable
from a shell simply failing to launch. After it, the same condition prints a
stated `skipped` receipt, matching the module's own documented "1 skipped
... stated either way" contract.

Removing a directory while it is the process's own cwd is a POSIX operation;
Windows locks a directory that is any process's current directory against
removal, so the reproduction below cannot be constructed there. Skipped
loudly on that platform rather than asserting nothing, per this repo's own
rule that a permission/OS fixture is measured, not assumed.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

_REPRO = (
    "import os, sys, tempfile\n"
    "d = tempfile.mkdtemp()\n"
    "os.chdir(d)\n"
    "os.rmdir(d)\n"
    "os.execv(sys.executable, [sys.executable, {0!r}, '--check'])\n"
)


def _vanished_cwd_reachable():
    """Attempt the exact construction the test relies on, once, and report
    whether this platform permits it -- never assumed from `os.name`."""
    d = tempfile.mkdtemp()
    try:
        cwd_before = os.getcwd()
        os.chdir(d)
        try:
            os.rmdir(d)
        except OSError as exc:
            return False, "{0}: {1}".format(type(exc).__name__, exc)
        try:
            os.getcwd()
        except OSError:
            return True, None
        return False, "os.getcwd() still answered after its directory was removed"
    finally:
        os.chdir(cwd_before)


def test_a_vanished_cwd_reports_skipped_rather_than_crashing():
    reachable, why = _vanished_cwd_reachable()
    if not reachable:
        import pytest

        pytest.skip(
            "could not remove this process's own cwd on this platform "
            "({0}) -- what went untested: a deleted-cwd module import "
            "on this OS".format(why)
        )

    result = subprocess.run(
        [sys.executable, "-c", _REPRO.format(str(SCRIPT))],
        capture_output=True,
        text=True,
    )
    # Before the guard: an unhandled FileNotFoundError killed the import,
    # exit 1, nothing at all on stdout -- indistinguishable from a shell
    # that never launched the process. After it: a stated `skipped` receipt.
    assert "Traceback" not in result.stderr
    assert "assemble" in result.stdout
    assert "skipped" in result.stdout
    assert "could not read the current working directory" in result.stdout
