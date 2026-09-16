"""oss_step_begin renders a step as in-flight before oss_step overwrites it (#1511).

Before this change, `oss_step` was a single `printf` on completion: a step that was
running and a step that had not started rendered identically -- as nothing. This
tests the REAL functions extracted verbatim out of `bin/oss-workspace`, the same
convention `_extract_heredoc` already uses in `tests/test_workspace_launcher.py` for
the DERIVE_NAME/READ_NAME/CHECK_NAME blocks: a test that reimplemented the shell
logic would measure its own reimplementation instead (CLAUDE.md's own trap about
`bash -c` strings that reconstruct shell behaviour).
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


# --- #1609: oss_step_begin wired to the plugin currency check itself ---
#
# The issue's own "no new rendering, no change to any of the eight outcomes"
# claim does not hold on inspection: four of the eight `plugin` branches echo
# diagnostic prose to stderr BEFORE their `oss_step plugin ...` call, which is
# exactly the hazard the comment above oss_step_begin's own definition warns
# about -- an echo landing glued onto the begin line's unterminated "..."
# instead of overwriting it first. The fix reorders all eight branches so
# `oss_step plugin` always runs before any echo of its own; these tests pin
# that ordering directly, on the REAL block extracted out of bin/oss-workspace,
# not a reimplementation of it (same reasoning as `_extract_step_functions`
# above).
#
# stdout and stderr are merged (stderr=subprocess.STDOUT) rather than
# captured on separate pipes: on a real terminal both streams share one fd,
# so what actually interleaves is write ORDER, and separate pipes cannot see
# that at all -- they would pass regardless of which line ran first.

PLUGIN_START_MARKER = 'oss_step_begin plugin "checking"'
PLUGIN_END_MARKER = "\n\n# --- repoint this launcher"


def _extract_plugin_block():
    """The real plugin-currency-check block, verbatim, not a rewrite of it."""
    launcher = LAUNCHER.read_text(encoding="utf-8")
    if PLUGIN_START_MARKER not in launcher or PLUGIN_END_MARKER not in launcher:
        pytest.fail(
            "bin/oss-workspace no longer carries the plugin-currency block in "
            "the shape this test extracts -- a block that went unchecked must "
            "not read as one that agreed"
        )
    tail = launcher.split(PLUGIN_START_MARKER, 1)[1]
    body = tail.split(PLUGIN_END_MARKER, 1)[0]
    return PLUGIN_START_MARKER + body


@pytest.fixture
def fake_python_bin(tmp_path):
    """A stand-in for `python_bin` that ignores its real arguments (the path
    to plugin_update.py, --root, --caller, --print-state) and instead prints
    $FAKE_PLUGIN_LINE and exits $FAKE_PLUGIN_STATUS -- both read from the
    environment so each branch below can drive it without a second script.
    """
    script = tmp_path / "fake-python"
    script.write_text(
        "#!/bin/sh\n"
        'printf %s "${FAKE_PLUGIN_LINE:-}"\n'
        'exit "${FAKE_PLUGIN_STATUS:-0}"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return str(script)


def _posix_shell_literal(path):
    """Embed a filesystem path INTO constructed shell script text, safely.

    Every other path in this file reaches a subprocess via subprocess.run's
    own argv, which passes it through literally regardless of separator.
    `fake_python_bin` is different: its path is spliced into the SOURCE TEXT
    of a script later run as `bash -c script`, and on Windows `tmp_path`
    renders with backslashes (`C:\\Users\\...`). Unquoted in shell text, each
    backslash is the shell's own escape character and is stripped before the
    next character -- `C:\\Users\\runneradmin\\...` becomes
    `C:UsersrunneradminAppDataLocalTemp...`, the exact mangled path observed
    on the windows-latest CI leg (#1609): the fake python shim then does not
    exist at the (wrong) path bash tries to exec, and every plugin-block test
    driven through it fails with "command not found" before it ever reaches
    the diagnostic text being asserted on. Forward slashes are what MSYS
    bash's own path translation expects, and single-quoting keeps them (and
    any literal backslash in a UNC path) from being reinterpreted a second
    time.
    """
    text = str(path).replace("\\", "/")
    return "'" + text.replace("'", "'\\''") + "'"


def _run_plugin_block(python_bin, status, line, extra_env=None):
    """Run the real plugin block with python_bin/status/line fixed, merging
    stdout and stderr in write order the way a shared terminal fd would.
    """
    script = "\n".join(
        [
            "e=$(printf '\\033')",
            "r=''; y=''; g=''; w=''; d=''",
            "oss_steps=1",
            _extract_step_functions(),
            "python_bin=%s" % _posix_shell_literal(python_bin),
            "plugin_root=/nonexistent",
            "repo_root=/nonexistent",
            "prompt=/oss:run",
            _extract_plugin_block(),
        ]
    )
    env = dict(os.environ)
    env["FAKE_PLUGIN_STATUS"] = str(status)
    env["FAKE_PLUGIN_LINE"] = line
    if extra_env:
        env.update(extra_env)
    done = subprocess.run(
        [BASH, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    return done.stdout.decode("utf-8", "replace")


def _assert_step_precedes_echo(out, echo_needle):
    """The core #1609 assertion: the begin line's overwrite (`\r\x1b[K`)
    must land in the stream BEFORE the branch's own diagnostic echo -- proof
    that `oss_step plugin ...` ran first and the echo landed on a fresh line
    rather than glued onto the still-open "..." mark.
    """
    overwrite_at = out.find("\r\x1b[K")
    echo_at = out.find(echo_needle)
    assert overwrite_at != -1, "no begin-line overwrite in output: %r" % out
    assert echo_at != -1, "expected diagnostic text not found: %r" % out
    assert overwrite_at < echo_at, (
        "the diagnostic echo landed before the step overwrote the in-flight "
        'line -- it would glue onto the begin line\'s unterminated "..." '
        "instead of printing on a line of its own: %r" % out
    )


def test_plugin_nonzero_exit_step_precedes_echo(fake_python_bin):
    _require_shell()
    out = _run_plugin_block(fake_python_bin, 7, "")
    _assert_step_precedes_echo(out, "could not check whether the oss plugin is current")


def test_plugin_updated_step_precedes_echo(fake_python_bin):
    _require_shell()
    tab = "\t"
    line = tab.join(["updated", "0.36.0", "0.37.0", ""])
    out = _run_plugin_block(fake_python_bin, 0, line)
    _assert_step_precedes_echo(out, "the oss plugin was updated from")


def test_plugin_could_not_check_step_precedes_echo(fake_python_bin):
    _require_shell()
    tab = "\t"
    line = tab.join(["could-not-check", "", "", "network unreachable"])
    out = _run_plugin_block(fake_python_bin, 0, line)
    _assert_step_precedes_echo(
        out, "could not check whether the oss plugin is current: network unreachable"
    )


def test_plugin_no_python_step_precedes_echo():
    _require_shell()
    out = _run_plugin_block("", 0, "")
    _assert_step_precedes_echo(
        out, "no working python was found, so the oss plugin could"
    )


def test_plugin_begin_mark_is_gone_from_the_final_output():
    """The control the issue itself asks for: assert the in-flight line is
    GONE from the final output, not merely that it appeared. A begin without
    a matching overwrite leaves a permanent dim line claiming a step is still
    running, which is worse than the silence it replaces.
    """
    _require_shell()
    out = _run_plugin_block("", 0, "")
    # oss_step's own printf always starts "\r%s[K", which erases the begin
    # line's rendered text on any real terminal -- so the dangling
    # UNTERMINATED begin mark ("..." with no following overwrite anywhere in
    # the stream) is what would signal the leftover-line failure. Since this
    # branch's echo is now proven (above) to land after the overwrite, a
    # bare count check pins that exactly one overwrite happened, not zero and
    # not the begin printf alone surviving unpaired.
    assert out.count("\r\x1b[K") == 1, (
        "expected exactly one step overwrite (the paired oss_step call), "
        "not a dangling begin with nothing to erase it: %r" % out
    )


def test_plugin_current_and_off_branches_already_had_no_echo_and_stay_that_way(
    fake_python_bin,
):
    """The two single-line branches (current, off) never had a hazard --
    pinned here as a control so a future edit that adds an echo to either is
    caught by the same ordering assertion the hazard branches use.
    """
    _require_shell()
    tab = "\t"
    out = _run_plugin_block(fake_python_bin, 0, tab.join(["current", "", "0.37.0", ""]))
    assert "\r\x1b[K" in out
    assert "0.37.0" in out


def test_plugin_could_not_check_detail_survives_empty_from_and_to(fake_python_bin):
    """A regression pin for the parsing bug found while writing the tests
    above: `could-not-check` documents from plugin_update.py ordinarily
    carry an EMPTY from/to (per its own `_flat()`), and a tab-delimited
    `IFS=<tab> read` silently collapses that run of empty fields and shifts
    `detail` out of existence -- the real reason a maintainer would want to
    see never reaches the terminal. `cut` on the same delimiter must not.
    """
    _require_shell()
    tab = "\t"
    line = tab.join(["could-not-check", "", "", "network unreachable"])
    out = _run_plugin_block(fake_python_bin, 0, line)
    assert "network unreachable" in out, (
        "the could-not-check detail was lost by the tab-field parse: %r" % out
    )
    assert "(no reason was reported" not in out


def test_plugin_line_with_no_delimiter_at_all_does_not_leak_into_detail(
    fake_python_bin,
):
    """Regression pin for a review finding: `cut -fN` (no `-s`) on a line with
    NO delimiter at all prints the WHOLE line back for every requested field,
    so a malformed/truncated `auto_update_line` -- a crash, a stray stderr
    line merged in by this call's own `2>&1` -- would leak the raw text into
    `auto_update_detail` as though it were the real reason, entirely bypassing
    the empty-reason fallback. `cut -s` must suppress a delimiter-less line
    instead, landing in the `""` (state unparseable) branch rather than
    `*)` (unrecognised state) with the garbage duplicated across every field.
    """
    _require_shell()
    out = _run_plugin_block(fake_python_bin, 0, "not a tab-delimited line at all")
    assert "not a tab-delimited line at all" not in out, (
        "the malformed line leaked into a field instead of being suppressed: %r" % out
    )
    assert "check printed nothing" in out


# The two remaining `plugin` branches also echo after their own `oss_step`
# call -- a review finding: the four tests above cover the four hazard
# branches this issue's own fix reorders, but the `""` (unparseable) and
# `*)` (unrecognised state) branches, which had the safe order ALREADY and
# were never hazards, were not pinned by name. A future edit that re-glues
# either one's echo onto the in-flight mark -- the exact hazard #1511 exists
# to prevent -- would have passed this suite green with neither covered.


def test_plugin_empty_state_field_step_precedes_echo(fake_python_bin):
    _require_shell()
    tab = "\t"
    # Three tabs, no content: cut -s gives four empty fields, landing in the
    # `""` (state unparseable) case rather than `could-not-check`'s "" field
    # arrangement above.
    line = tab.join(["", "", "", ""])
    out = _run_plugin_block(fake_python_bin, 0, line)
    _assert_step_precedes_echo(
        out, "the plugin update check printed nothing this launcher could parse"
    )


def test_plugin_unrecognised_state_step_precedes_echo(fake_python_bin):
    _require_shell()
    tab = "\t"
    line = tab.join(["mystery-state", "0.1", "0.2", "unused"])
    out = _run_plugin_block(fake_python_bin, 0, line)
    _assert_step_precedes_echo(
        out, "reported a state this launcher does not recognise (mystery-state)"
    )
