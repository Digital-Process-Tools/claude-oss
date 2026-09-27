"""#1772: `oss_fireworks()` "cleared" its canvas by printing 64 spaces per row and
never sent an erase sequence, so on a terminal still holding earlier output every
column past 64, and every row below the canvas, kept the old text.

The function is extracted verbatim out of `bin/oss-workspace` and run under a
real pseudo-terminal (it draws nothing unless stdout is a TTY), and its byte
stream is checked: every frame's clear must be an erase-to-end-of-screen
(`ESC[J`), and no fixed-width padding may stand in for one. POSIX only -- the
`pty` module does not exist on Windows, and the sequences are identical there.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import shell_probe  # noqa: E402

LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

_ATTEMPTS = shell_probe.attempts([LAUNCHER, Path(sys.executable)])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

pty = pytest.importorskip("pty", reason="no pty module on this platform")

START = "oss_fireworks() {"
END = "\noss_fireworks\n"
ERASE_BELOW = b"\x1b[J"


def _render():
    if BASH is None:
        pytest.skip(SHELL_REPORT)
    text = LAUNCHER.read_text(encoding="utf-8")
    if START not in text or END not in text:
        pytest.fail(
            "bin/oss-workspace no longer defines oss_fireworks in the shape this test extracts"
        )
    body = START + text.split(START, 1)[1].split(END, 1)[0]
    script = "\n".join([body, "oss_fireworks", "printf 'DONE'"])
    master, slave = pty.openpty()
    env = dict(os.environ, TERM="xterm-256color")
    env.pop("OSS_WORKSPACE_NO_FIREWORKS", None)
    proc = subprocess.Popen(
        [BASH, "-c", script], stdin=slave, stdout=slave, stderr=slave, env=env
    )
    os.close(slave)
    chunks = []
    while True:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    proc.wait()
    os.close(master)
    return b"".join(chunks)


def test_the_splash_draws_at_all_under_a_terminal():
    """Positive control: an empty render would pass every assertion below."""
    out = _render()
    assert b"DONE" in out
    assert "██████".encode("utf-8") in out


def test_every_frame_clear_erases_to_the_end_of_the_screen():
    out = _render()
    # 12 clr() calls in the animation, each must erase rather than pad.
    assert out.count(ERASE_BELOW) >= 12, out[:400]


def test_no_fixed_width_padding_stands_in_for_an_erase():
    out = _render()
    assert b" " * 64 not in out
