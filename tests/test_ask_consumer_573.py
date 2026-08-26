"""#573 -- the ASK_CONSUMER heredoc opener at `bin/oss-workspace:622` still ends in
`|| true` with no captured status, so a `RecursionError` out of `json.load` on a
deeply nested (but validly-formed) consumer registry never reaches `cannot_ask()`.

#546 hardened the shapes *inside* the block so a malformed registry (wrong JSON type,
wrong structure) reaches `cannot_ask()` cleanly. It left the *opener* alone. A
`RecursionError` is neither `OSError` nor `ValueError`, so it is not caught by the
`except (OSError, ValueError)` around `json.load` -- Python prints a traceback and
exits nonzero, and the `|| true` on the heredoc invocation swallows that exit status,
so the launcher goes on as though the probe had answered ACCEPTED or REJECTED rather
than reporting the third state, COULD NOT ASK, that this block exists to report
loudly.

Driven at the SHELL level, not through `_extract_heredoc`'s python-only extraction:
that helper strips the `<<'ASK_CONSUMER' || true` wrapper along with the heredoc body,
so it cannot see the very swallow this issue is about. This test extracts the whole
`if ... fi` block -- wrapper included -- and runs it under `sh`, which is what
`bin/oss-workspace` itself runs it under.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

BLOCK_START = "if [ -n \"${SUPERTOOL_WATCH_NAME:-}\" ] && [ -n \"$python_bin\" ]; then"
ASK_CONSUMER_CLOSE = "\nASK_CONSUMER\n"
#: The block's own closing "fi" doubled up once the fix lands (one "fi" for the
#: crashed-probe status check the fix adds, one for the outer SUPERTOOL_WATCH_NAME
#: guard) -- so the end of the block is the SECOND "fi" line after ASK_CONSUMER
#: closes, not the first.


def _extract_ask_consumer_block():
    """The whole shell `if`/heredoc/`fi` wrapper around ASK_CONSUMER, verbatim.

    Unlike `tests/test_ask_consumer_546.py`'s `_extract_heredoc`, this keeps the
    heredoc opener line (`<<'ASK_CONSUMER' ...`) and the closing `fi` -- the shell
    machinery this issue is about, which the python-only extraction discards.
    """
    launcher = LAUNCHER.read_text(encoding="utf-8")
    start = launcher.find(BLOCK_START)
    if start == -1:
        pytest.fail(
            "bin/oss-workspace no longer opens ASK_CONSUMER with the expected "
            "SUPERTOOL_WATCH_NAME guard -- and a block that went unchecked must "
            "not read as one that agreed"
        )
    marker_end = launcher.find(ASK_CONSUMER_CLOSE, start)
    if marker_end == -1:
        pytest.fail(
            "bin/oss-workspace's ASK_CONSUMER block no longer closes with the "
            "expected marker -- and a block that went unchecked must not read as "
            "one that agreed"
        )
    tail_start = marker_end + len(ASK_CONSUMER_CLOSE)
    # Walk lines from the close of the heredoc, tracking `if`/`fi` nesting, until
    # the `fi` that matches the outer SUPERTOOL_WATCH_NAME guard is found -- rather
    # than assuming a fixed count, which would silently stop tracking the real
    # block boundary the moment either side changes shape again.
    depth = 0
    end = -1
    offset = tail_start
    for line in launcher[tail_start:].splitlines(keepends=True):
        offset += len(line)
        stripped = line.strip()
        if stripped.startswith("if "):
            depth += 1
        elif stripped == "fi":
            if depth == 0:
                end = offset
                break
            depth -= 1
    if end == -1:
        pytest.fail(
            "bin/oss-workspace's ASK_CONSUMER block's outer `fi` was not found -- "
            "and a block that went unchecked must not read as one that agreed"
        )
    return launcher[start:end]


def _sh_single_quote(value):
    """Embed `value` -- which may carry a literal newline -- as a POSIX `sh`
    single-quoted literal. A single quote inside `value` closes the quoting and
    must itself be escaped; the standard close-quote/escaped-quote/reopen-quote
    idiom is the only portable way to do that without leaving `sh` to interpret
    anything else in `value`.
    """
    return "'" + value.replace("'", "'\\''") + "'"


def _run_ask_consumer_block(tmp_path, registry_content, watch_name="some-watch-name"):
    """Run the extracted shell block under `sh`, with a real python and a fake
    HOME carrying the given consumer registry -- the same resolution order
    `bin/oss-workspace` itself uses (`~/.claude/plugins/installed_plugins.json`).

    `watch_name` is written as a single-quoted `sh` literal rather than bare, so
    a caller can hand it a value carrying a literal newline or other bytes a
    naive interpolation would corrupt -- an already-exported
    `SUPERTOOL_WATCH_NAME` is exactly the unvalidated case `cannot_ask()`'s own
    comment names.
    """
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        registry_content, encoding="utf-8"
    )
    script = tmp_path / "run_block.sh"
    script.write_text(
        "python_bin=%s\n"
        "SUPERTOOL_WATCH_NAME=%s\n"
        "export SUPERTOOL_WATCH_NAME\n"
        "%s"
        % (sys.executable, _sh_single_quote(watch_name), _extract_ask_consumer_block()),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = str(home)
    verify = subprocess.run(
        [sys.executable, "-c", "import os,sys; sys.stdout.write(os.path.expanduser('~'))"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )
    resolved = verify.stdout
    if os.path.normcase(os.path.normpath(resolved)) != os.path.normcase(os.path.normpath(str(home))):
        pytest.skip(
            "os.path.expanduser('~') resolved to %r instead of the fixture's %r on "
            "this platform (python %s) -- the HOME/USERPROFILE redirect did not "
            "take, so this shape is untested here" % (resolved, str(home), sys.version.split()[0])
        )
    return subprocess.run(
        ["sh", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )


def _deeply_nested_registry(depth=40000):
    """Valid JSON, nested deep enough that CPython's `json.load` raises
    `RecursionError` rather than parsing it -- neither `OSError` nor `ValueError`,
    so it is not caught by the block's own `except (OSError, ValueError)`.
    """
    return "[" * depth + "]" * depth


def test_a_recursion_error_reaches_a_could_not_ask_message_not_silence(tmp_path):
    """The positive control: a validly-formed but pathologically deep registry must
    still produce the block's COULD NOT ASK sentence on stderr, not just a bare
    traceback that the shell then discards via `|| true`.
    """
    done = _run_ask_consumer_block(tmp_path, _deeply_nested_registry())
    assert "could not ask the installed supertool" in done.stderr, done.stderr


def test_a_well_formed_registry_still_answers_ordinarily(tmp_path):
    """The negative control's own control, in the same fixture: a well-formed
    registry that declares no supertool install must still produce the ordinary,
    unaffected answer -- no COULD NOT ASK sentence, no traceback. A fixture that
    only ever asserts "must fire" would pass even if the fix reported every
    registry as a crash.
    """
    done = _run_ask_consumer_block(tmp_path, json.dumps({"plugins": {}}))
    assert "Traceback" not in done.stderr, done.stderr
    assert "could not ask the installed supertool" not in done.stderr, done.stderr


# --- the crash message renders an UNVALIDATED SUPERTOOL_WATCH_NAME (maintainer
# review of #573) ---------------------------------------------------------------
#
# cannot_ask() itself (the Python function this shell message is meant to mirror)
# quotes the name with %r rather than interpolating it raw, and its own comment
# says why: this arm is reachable with an unvalidated name, because an
# already-exported SUPERTOOL_WATCH_NAME wins and never goes through the naming
# gate. The shell-level message this fix adds is reachable on the exact same
# path -- so a newline or a terminal escape sequence in an exported name must not
# reach it unescaped, the same "no forged line" property
# tests/test_workspace_launcher.py already asserts for the `conflict` arm.
#
# Column-0 line counting rather than a substring check, for the same reason that
# module's own FORGED_TAIL comment gives: a value containing the literal text
# "oss-workspace:" would make a substring assertion lie in the safe direction.

_ONE_LINE_NAME = "safe-watch-name"
_NEWLINE_NAME = "evil-watch-name\nVERDICT: ok\r\x1b[2K"


def _oss_workspace_lines(stderr):
    """Lines that CLAIM to be this launcher speaking -- column 0, not anywhere --
    the same convention tests/test_workspace_launcher.py's `_launcher_lines` uses.
    """
    return [
        line for line in stderr.splitlines() if line.startswith("oss-workspace:")
    ]


def test_a_newline_in_the_watch_name_does_not_forge_a_line(tmp_path):
    """The positive control: a watch name carrying a literal newline (and a CSI
    erase sequence right after it, the same forgery tests/test_workspace_
    launcher.py measures) must not turn into a second column-0 line or an escape
    sequence a terminal would act on. A "no forged line" assertion that never
    checks whether the crash message fired at all would pass on a fixture where
    nothing was printed -- test_an_ordinary_watch_name_still_appears_in_the_
    crash_message, right below, is that control.
    """
    done = _run_ask_consumer_block(
        tmp_path, _deeply_nested_registry(), watch_name=_NEWLINE_NAME
    )
    assert "could not ask the installed supertool" in done.stderr, done.stderr
    # "No forged line" means exactly one line claims to be this launcher speaking
    # -- "VERDICT: ok" is expected to be READABLE inside that one line, as the
    # escaped tail of the repr()'d name; what must not happen is it landing on
    # its own line at column 0, which the len(lines) == 1 assertion catches.
    lines = _oss_workspace_lines(done.stderr)
    assert len(lines) == 1, (lines, done.stderr)
    # The raw newline and the escape byte must not reach stderr un-rendered --
    # repr() is what stands between them and a terminal that would act on them,
    # and this is what would fail if the intermediate `echo` re-interpreted
    # repr()'s own backslash escapes (as this platform's /bin/sh echo does).
    assert "\\n" in lines[0] or "\\x1b" in lines[0].lower(), lines[0]
    assert "\x1b" not in done.stderr, done.stderr


def test_an_ordinary_watch_name_still_appears_in_the_crash_message(tmp_path):
    """The must-fire control's own control: an ordinary name must still be
    readable in the crash message after the repr() rendering, not merely absent
    of forgeries. A rendering that hid every name would pass the test above for
    the wrong reason.
    """
    done = _run_ask_consumer_block(
        tmp_path, _deeply_nested_registry(), watch_name=_ONE_LINE_NAME
    )
    lines = _oss_workspace_lines(done.stderr)
    assert len(lines) == 1, (lines, done.stderr)
    assert _ONE_LINE_NAME in lines[0], lines[0]
