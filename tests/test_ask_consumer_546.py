"""#546 -- `bin/oss-workspace`'s ASK_CONSUMER block masks a crashing consumer probe
with `|| true` at the shell level, and the extracted Python body itself crashes with
an unguarded `AttributeError` on five of seven measured registry shapes instead of
reaching `cannot_ask()` (`:649-657`), which exists precisely to report this state
loudly.

Measured directly against `bin/oss-workspace`'s own heredoc body (extracted, not
reimplemented -- see `tests/test_workspace_launcher.py`'s `_extract_heredoc`): the
issue's own table claims "four of seven crash"; a direct run of all seven shapes
against the pre-fix heredoc showed FIVE crash (`top-level list`, `top-level null`,
`top-level string`, `entry is a string`, `entries is a string`). This test asserts
against the measured five, not the issue's prose count -- the issue's own table
lists five rc=1 rows and the "four" in its prose does not match its own table.

`scripts/doctor.py`'s `_consumer_watch_name_verdict` (`:2848-2922`) already performs
this exact guard, unrelated to and unmodified by this fix -- the fix ports the same
`isinstance` guards into the launcher's own copy.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

MARKER = "ASK_CONSUMER"


def _home_env(home):
    """An env mapping that redirects `os.path.expanduser("~")` to `home`,
    verified rather than assumed (#557).

    `HOME` alone only redirects `expanduser` on POSIX: CPython's `ntpath.
    expanduser` (the implementation Windows uses) never consults `HOME` at
    all -- it reads `USERPROFILE` first and `HOMEDRIVE`+`HOMEPATH` second,
    falling through to the real, unredirected profile when neither of those
    is overridden. The pre-fix fixture set only `HOME`, so on the Windows
    runner every shape silently resolved against the real profile instead
    of the fixture's `tmp_path` -- which is why CI's own stderr named that
    real path rather than the fixture's. Setting all three here is the
    fix; verifying it actually took, below, is what stops this from being
    the same unverified assumption one env var over.
    """
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = str(home)
    return env


def _verify_home_redirect(env, home):
    """Attempt the exact resolution the code under test performs, rather than
    assuming the env override took. Returns None when it matches, or a
    skip reason naming what did not take.
    """
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os,sys; sys.stdout.write(os.path.expanduser('~'))",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )
    resolved = done.stdout
    expected = str(home)
    if os.path.normcase(os.path.normpath(resolved)) != os.path.normcase(
        os.path.normpath(expected)
    ):
        return (
            "os.path.expanduser('~') resolved to %r instead of the fixture's "
            "%r on this platform (python %s) -- the HOME/USERPROFILE redirect "
            "did not take, so this shape is untested here"
            % (resolved, expected, sys.version.split()[0])
        )
    return None


def _extract_heredoc(marker):
    launcher = LAUNCHER.read_text(encoding="utf-8")
    opening = "<<'" + marker + "'"
    closing = "\n" + marker + "\n"
    tail = launcher.split(opening, 1)[1] if opening in launcher else ""
    if "\n" not in tail or closing not in tail:
        pytest.fail(
            "bin/oss-workspace no longer carries a %s heredoc, so its consumer-probe "
            "behaviour went unchecked -- and a block that went unchecked must not "
            "read as one that agreed" % marker
        )
    return tail.split("\n", 1)[1].split(closing, 1)[0]


#: Seven registry shapes, measured directly against the extracted heredoc body
#: (see the module docstring). `content` is what the fixture writes as
#: `~/.claude/plugins/installed_plugins.json`.
SHAPES = {
    "dict, no supertool": '{"plugins": {}}',
    "top-level list": "[]",
    "top-level null": "null",
    "top-level string": '"x"',
    "plugins is a list": '{"plugins": []}',
    "entry is a string": '{"plugins": {"supertool@x": ["notadict"]}}',
    "entries is a string": '{"plugins": {"supertool@x": "notalist"}}',
}

#: Measured (see module docstring), not the issue's prose count of four.
CRASHES_TODAY = {
    "top-level list",
    "top-level null",
    "top-level string",
    "entry is a string",
    "entries is a string",
}

#: The must-fire control: these two must stay quiet (rc=0, no output) after the
#: fix, exactly as they are today -- a guard that reports every shape loudly would
#: be as wrong as one that reports none.
BENIGN = set(SHAPES) - CRASHES_TODAY


def _run_ask_consumer(tmp_path, content):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        content, encoding="utf-8"
    )
    script = tmp_path / "ask_consumer.py"
    script.write_text(_extract_heredoc(MARKER), encoding="utf-8")
    env = _home_env(home)
    skip_reason = _verify_home_redirect(env, home)
    if skip_reason:
        pytest.skip(skip_reason)
    done = subprocess.run(
        [sys.executable, str(script), "some-watch-name"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )
    return done


@pytest.mark.parametrize("shape", sorted(CRASHES_TODAY))
def test_a_crashing_registry_shape_must_reach_cannot_ask_not_a_traceback(
    tmp_path, shape
):
    """The positive control: each of the five measured crashing shapes must now
    produce the loud `cannot_ask()` sentence instead of an unhandled traceback.
    """
    done = _run_ask_consumer(tmp_path, SHAPES[shape])
    assert "Traceback" not in done.stderr, (shape, done.stderr)
    assert "could not ask the installed supertool" in done.stderr, (shape, done.stderr)


@pytest.mark.parametrize("shape", sorted(BENIGN))
def test_a_benign_registry_shape_still_exits_quietly(tmp_path, shape):
    """The negative control's own control: a benign shape (empty registry, empty
    `plugins`, or `plugins` itself an empty list) must still produce no output at
    all after the fix -- a guard that reports every shape loudly is exactly as
    wrong as one that reports none.
    """
    done = _run_ask_consumer(tmp_path, SHAPES[shape])
    assert done.stdout == "" and done.stderr == "", (shape, done.stdout, done.stderr)
    assert done.returncode == 0, (shape, done.returncode)


# --- FIND_CONSUMER: the same unguarded pattern, one block down (adjacent finding) --
#
# Not filed in #546 -- the issue names only ASK_CONSUMER at :622 -- but it is the
# SAME 17-line list comprehension, in the same file, crashing on the same five
# shapes with the same AttributeError. `|| true` does not swallow this one (stderr
# is not captured by the command substitution around it), so a live launcher run
# would already show a raw Python traceback rather than silence -- still worse
# than the clean, actionable message this block's own comment argues for two lines
# above ("Not found with no reason is the shape that reports a confident wrong
# answer"). Small, mechanical, same subsystem: fixed alongside rather than filed.

FIND_MARKER = "FIND_CONSUMER"


def _run_find_consumer(tmp_path, content):
    home = tmp_path / "find_home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        content, encoding="utf-8"
    )
    script = tmp_path / "find_consumer.py"
    script.write_text(_extract_heredoc(FIND_MARKER), encoding="utf-8")
    env = _home_env(home)
    skip_reason = _verify_home_redirect(env, home)
    if skip_reason:
        pytest.skip(skip_reason)
    return subprocess.run(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )


@pytest.mark.parametrize("shape", sorted(CRASHES_TODAY))
def test_find_consumer_a_crashing_shape_reaches_a_clean_message_not_a_traceback(
    tmp_path, shape
):
    """The same positive control against FIND_CONSUMER: no traceback, and a
    stderr line naming the registry rather than a Python exception.
    """
    done = _run_find_consumer(tmp_path, SHAPES[shape])
    assert "Traceback" not in done.stderr, (shape, done.stderr)
    assert done.stdout == "", (shape, done.stdout)
    assert "oss-workspace:" in done.stderr, (shape, done.stderr)


@pytest.mark.parametrize("shape", sorted(BENIGN))
def test_find_consumer_a_benign_shape_reports_no_supertool_install(tmp_path, shape):
    """FIND_CONSUMER was never silent for "no installs" (unlike ASK_CONSUMER) --
    it already reports that state with its own remedy. That behaviour must not
    change: still one clean stderr line, still no traceback, still no match on
    stdout.
    """
    done = _run_find_consumer(tmp_path, SHAPES[shape])
    assert "Traceback" not in done.stderr, (shape, done.stderr)
    assert done.stdout == "", (shape, done.stdout)
    assert "lists no supertool install" in done.stderr, (shape, done.stderr)
