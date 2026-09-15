"""oss_step_begin renders a step as in-flight before oss_step overwrites it (#1511).

Before this change, `oss_step` was a single `printf` on completion: a step that was
running and a step that had not started rendered identically -- as nothing. This
tests the REAL functions extracted verbatim out of `bin/oss-workspace`, the same
convention `_extract_heredoc` already uses in `tests/test_workspace_launcher.py` for
the DERIVE_NAME/READ_NAME/CHECK_NAME blocks: a test that reimplemented the shell
logic would measure its own reimplementation instead (CLAUDE.md's own trap about
`bash -c` strings that reconstruct shell behaviour).
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
    """The real `oss_step_begin`/`oss_step` source text, not a rewrite of it.

    Fails loudly rather than silently testing nothing if the markers move --
    the same shape `_extract_heredoc` uses for the three heredoc blocks.
    """
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


def _run_steps(oss_steps, calls):
    """Source the extracted functions with plain (uncoloured) markers and run `calls`.

    Colours are set to "" rather than real escape codes: the assertions below are
    about STRUCTURE (an in-flight marker present, a carriage return before the
    verdict, exactly one rendered line) not about ANSI colour bytes, and a
    colour-free run keeps the substring checks readable.
    """
    script = "\n".join(
        [
            "e=$(printf '\\033')",
            "r=''; y=''; g=''; w=''; d=''",
            "oss_steps=%s" % oss_steps,
            _extract_step_functions(),
            calls,
        ]
    )
    # NOT universal_newlines=True: Python's line-ending translation turns a bare
    # carriage return into a newline, which is exactly the byte this test exists
    # to see. Captured as raw bytes and decoded by hand instead, so it survives.
    done = subprocess.run(
        [BASH, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace")


def test_begin_renders_an_in_flight_mark_before_the_step_is_known():
    _require_shell()
    out = _run_steps(1, "oss_step_begin plugin 'checking for an update'")
    assert "checking for an update" in out
    assert "..." in out


def test_step_overwrites_the_begin_line_in_place():
    """The paired oss_step call after a begin call must rewrite, not append.

    A carriage return (moves to column 0) followed by the ANSI clear-to-EOL
    sequence has to appear between the in-flight line and the final verdict --
    that IS "in place", as opposed to a second line stacked under the first.
    """
    _require_shell()
    out = _run_steps(
        1,
        "oss_step_begin plugin 'checking for an update'\n"
        "oss_step plugin '0.36.0 -> current' ok",
    )
    # A pipe captures raw bytes, not a rendered screen: the erased text is still
    # IN the string, because "erased" is a terminal-emulation fact this test has
    # no terminal to observe. What is checkable here is the escape sequence that
    # instructs a real terminal to erase it -- a carriage return immediately
    # followed by the ANSI clear-to-EOL code, sitting right before the second,
    # final rendering of the "plugin" line.
    assert "\r\x1b[K" in out, (
        "no carriage-return-then-clear before the rewrite: %r" % out
    )
    assert out.count("plugin") == 2, (
        "expected the in-flight line and the rewritten line, each carrying the "
        "label once: %r" % out
    )
    assert "0.36.0 -> current" in out


def test_a_step_called_with_no_matching_begin_still_renders_as_before():
    """Most oss_step call sites have no paired begin (unchanged, on purpose).

    The unconditional carriage-return-and-clear oss_step now always emits has to
    be a no-op when nothing preceded it on that line, or every un-migrated call
    site's output shape would have silently changed underneath it.
    """
    _require_shell()
    out = _run_steps(1, "oss_step channel 'oss-channel armed' ok")
    assert "oss-channel armed" in out
    assert "..." not in out


def test_gated_off_by_the_same_flag_oss_step_already_used():
    """Positive control for the negative assertion below: oss_steps=1 DOES print,
    so an empty result under oss_steps=0 is the gate firing, not a harness that
    produced nothing at all either way (CLAUDE.md's own rule on paired controls).
    """
    _require_shell()
    on = _run_steps(1, "oss_step_begin plugin 'checking for an update'")
    off = _run_steps(0, "oss_step_begin plugin 'checking for an update'")
    assert on != ""
    assert off == ""


def _run_steps_coloured(calls):
    """Like `_run_steps`, but with REAL dim/reset escape codes rather than the
    empty placeholders every other test in this file uses. Needed for exactly
    one assertion: whether the in-flight mark is actually dim, which a
    colour-free run cannot see either way (found in self-review -- the first
    version of `oss_step_begin` put the dim-on/reset pair around an empty
    argument and left the literal "..." outside it, unstyled).
    """
    script = "\n".join(
        [
            "e=$(printf '\\033')",
            "r=\"${e}[0m\"; d=\"${e}[2m\"; y=''; g=''; w=''",
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


def test_the_in_flight_mark_is_actually_dim():
    """The literal "..." has to sit INSIDE the dim-on/reset pair, not after it.

    A dim-on immediately followed by reset, with the plain "..." only after
    both, would satisfy every other assertion in this file (which run with
    colours emptied out) while rendering the mark in the terminal's default
    style rather than dim -- exactly the bug self-review caught.
    """
    _require_shell()
    out = _run_steps_coloured("oss_step_begin plugin 'checking for an update'")
    dim_on = "\x1b[2m"
    reset = "\x1b[0m"
    assert dim_on + "..." + reset in out, (
        "the in-flight mark is not wrapped in dim/reset: %r" % out
    )
