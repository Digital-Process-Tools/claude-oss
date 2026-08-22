"""#405 -- the stdin route cannot reach `could-not-read`, the file route can.

`review_return.py`'s two input routes do not fail alike. `Path(source).
read_bytes()` is wrapped and answers `could-not-read` at exit 6. The `-`
branch three lines above it calls `sys.stdin.buffer.read()` unguarded, and
`sys.stdin` is `None` when the harness hands the process a closed or
unopenable standard input -- so `.buffer` raises before any of the module's
handling runs, and the process exits 1 with no `VERDICT:` line at all. Exit 1
is not in `EXIT_CODES` and is not one of the six the docstring documents for a
shell to read.

That route is the one `agents/developer.md` mandates, and #404's fix keeps it
mandated rather than routing around it -- so this guard is live, not latent.

**The negative assertion carries a positive control in the same file.** A
module that answered `could-not-read` for everything would satisfy "a closed
stdin does not raise" perfectly, so the closed-stdin case is paired with an
ordinary piped message that must still reach a decisive verdict.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "review_return.py"

ORDINARY_MESSAGE = """FINDINGS: 1

1. `scripts/doctor.py` returns the same value for an empty scan and an
unreadable one."""


def test_stdin_that_is_none_reaches_could_not_read():
    """Drive the exact condition: a child whose `sys.stdin` is None.

    Closing fd 0 in the child is what a harness does, and it is what the
    issue's own reproduction does (`0<&-`). Python then sets `sys.stdin` to
    `None` rather than to a stream, which is the condition under test.
    """
    driver = (
        "import os, runpy, sys\n"
        "os.close(0)\n"
        "sys.stdin = None\n"
        "sys.argv = ['review_return.py', '-']\n"
        "try:\n"
        "    runpy.run_path({0!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    raise SystemExit(exc.code)\n"
    ).format(str(SCRIPT))
    proc = subprocess.run(
        [sys.executable, "-c", driver],
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")

    assert "Traceback" not in err, (
        "the mandated route still raises instead of answering. stderr:\n" + err
    )
    assert out.startswith("VERDICT: could-not-read"), (
        "a script that could not read the message and a script that read an "
        "empty one still differ only by a traceback nobody parses.\n"
        "stdout:\n{0}\nstderr:\n{1}".format(out, err)
    )
    assert proc.returncode == 6, (
        "exit {0} is not one of the six documented exit codes.\n"
        "stdout:\n{1}\nstderr:\n{2}".format(proc.returncode, out, err)
    )


def test_an_ordinary_piped_message_still_classifies():
    """The control: the fix cannot pass by declaring everything unreadable."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "-"],
        input=ORDINARY_MESSAGE.encode("utf-8"),
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    assert out.startswith("VERDICT: states-findings"), out
    assert proc.returncode == 0, out


def test_an_empty_but_open_stdin_is_still_returned_nothing():
    """Read and found nothing is not the same as could not read.

    This is the pair that makes the guard a third state rather than a rename:
    an open stdin carrying no bytes must stay `returned-nothing`.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "-"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    assert out.startswith("VERDICT: returned-nothing"), out
    assert proc.returncode == 4, out
