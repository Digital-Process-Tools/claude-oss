"""Streaming per-plugin progress into the `plugin` step's own gap (#1648).

`bin/oss-workspace`'s `plugin` step pairs `oss_step_begin`/`oss_step` like every
other migrated step (#1511, #1609) -- EXCEPT that this call site deliberately
BREAKS the "nothing else reaches the terminal in between" rule those two
functions' own docstring states, because streaming progress into exactly that
gap is the point of #1648. This file tests the REAL functions extracted
verbatim out of `bin/oss-workspace`, the identical convention
`test_workspace_step_progress_1511.py` already uses, rather than reimplementing
the shell logic (CLAUDE.md's own trap about a `bash -c` string that
reconstructs shell behaviour measuring its own reimplementation instead).

What has to hold, regardless of how many progress lines land in between: the
in-flight "checking..." mark must be TERMINATED (a real newline, not left
dangling for the first progress line to glue onto), and the final `oss_step`
call's own `\r` + clear-to-EOL must land on an EMPTY line -- a no-op, never an
erasure of a real progress line that streamed in between.
"""

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


def _require_shell():
    if BASH is None:
        pytest.skip(SHELL_REPORT)


START_MARKER = "oss_step_begin() {"
END_MARKER = "\nCHANNEL_FLAG="


def _extract_step_functions():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    if START_MARKER not in launcher or END_MARKER not in launcher:
        pytest.fail(
            "bin/oss-workspace no longer carries oss_step_begin/oss_step in the "
            "shape this test extracts -- a block that went unchecked must not "
            "read as one that agreed"
        )
    tail = launcher.split(START_MARKER, 1)[1]
    body = tail.split(END_MARKER, 1)[0]
    return START_MARKER + body


def _run_steps(calls):
    script = "\n".join(
        [
            "e=$(printf '\\033')",
            "r=''; y=''; g=''; w=''; d=''",
            "oss_steps=1",
            _extract_step_functions(),
            calls,
        ]
    )
    done = subprocess.run(
        [BASH, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace")


def _streamed_plugin_block():
    """Reproduces the shape of the real `bin/oss-workspace` call site: begin,
    a terminating newline, several progress lines each ending in their own
    "\n" (standing in for what `plugin_update.main()` writes to fd 3), then
    the paired `oss_step` call."""
    return "\n".join(
        [
            "oss_step_begin plugin 'checking'",
            "printf '\\n'",
            "printf '    checking oss...\\n'",
            "printf '    oss: current\\n'",
            "printf '    checking supertool...\\n'",
            "printf '    supertool: current\\n'",
            "oss_step plugin 'current' ok",
        ]
    )


def test_the_in_flight_mark_is_terminated_not_left_dangling():
    """The "checking..." in-flight mark must be on its own, complete line --
    never glued to the first progress line that follows it. `oss_step_begin`
    pads its label to a fixed width before the literal "...", so the
    assertion matches on "...\n" (the mark's own terminator) rather than the
    padded "checking" word itself."""
    _require_shell()
    rendered = _run_steps(_streamed_plugin_block())
    assert "...checking" not in rendered, rendered
    assert "...\n    checking oss...\n" in rendered, rendered


def test_every_progress_line_survives_on_its_own_line():
    """Nothing streamed in the gap is erased or garbled by the paired
    `oss_step` call's own cursor-clearing escape sequence."""
    _require_shell()
    rendered = _run_steps(_streamed_plugin_block())
    assert "    checking oss...\n" in rendered, rendered
    assert "    oss: current\n" in rendered, rendered
    assert "    checking supertool...\n" in rendered, rendered
    assert "    supertool: current\n" in rendered, rendered


def test_the_final_step_line_renders_with_no_visible_garbage_after_streaming():
    """The paired `oss_step` call's own `\r` + clear-to-EOL lands on an EMPTY
    line (the cursor position after the last progress line's own trailing
    "\n") -- a no-op clear -- so the final "plugin ... current" line is
    reachable, on its own line, with nothing but the expected escape codes
    between it and the last progress line."""
    _require_shell()
    rendered = _run_steps(_streamed_plugin_block())
    tail = rendered.split("supertool: current\n", 1)[1]
    # Only the expected carriage-return + clear-to-EOL sequence (or nothing,
    # if colour codes are empty strings) may sit before the final line's own
    # "plugin" marker -- never stray progress text or a mangled fragment.
    stripped = tail.lstrip("\r").split("\x1b[K", 1)
    remainder = stripped[-1]
    assert "plugin" in remainder, rendered
    assert remainder.count("plugin") == 1, rendered
    assert "current" in remainder, rendered
