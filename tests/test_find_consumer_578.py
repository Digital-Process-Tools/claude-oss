"""#578 -- the FIND_CONSUMER heredoc at bin/oss-workspace (further down the same
file from ASK_CONSUMER) still ended in
channel_script=$("$python_bin" - <<'FIND_CONSUMER' || true) with no captured
status, and its json.load was guarded only by except (OSError, ValueError). A
RecursionError out of json.load on a deeply nested (but validly-formed) registry
is neither, so it escaped the guard, the interpreter exited nonzero, || true
swallowed that status, and channel_script was left empty with no signal
anything had gone wrong.

That is worse than the ASK_CONSUMER case #573/#588 fixed: there a crashed probe
at least left a traceback on stderr beside the "could not ask" sentence. Here
the empty result landed in the SAME branch a genuine absence lands in -- the
launcher's own "the supertool plugin's channel consumer was not found"
sentence -- a specific, plausible fact about the world that a reader has no
reason to doubt.

Two things are tested, driven at the SHELL level (not through a python-only
extraction, which would strip the very || true / status-capture wrapper this
issue is about):

  1. The acquisition block (channel_script="" ... fi) -- a crash must leave
     find_consumer_status nonzero and channel_script empty, distinguishably
     from a well-formed absence (find_consumer_status zero, channel_script
     empty) and a well-formed hit (find_consumer_status zero, channel_script
     naming the file).
  2. The decision chain (channel_ready=0 ... fi) -- fed synthetic inputs
     directly, so it exercises the new could-not-look branch without depending
     on claude/bun being on PATH -- must report a DIFFERENT, UNKNOWN-flavoured
     sentence for a crashed probe than it does for a genuine absence, and the
     ordinary absence/found sentences must be unaffected.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

ACQUIRE_START = "channel_script=\"\"\n"
ACQUIRE_GUARD = "if [ -n \"$python_bin\" ]; then"
DECIDE_START = "channel_ready=0\n"
DECIDE_GUARD = "if [ \"$find_consumer_status\" -ne 0 ]; then"


def _extract_block(start_marker, guard_line, launcher):
    """The whole shell if/heredoc/fi (or plain if/fi) wrapper starting at
    start_marker, tracking if/fi nesting from the immediately following
    guard_line so the match is the block's own closing fi, not some later one.
    """
    start = launcher.find(start_marker)
    if start == -1:
        pytest.fail(
            "bin/oss-workspace no longer contains the expected marker %r -- a "
            "block that went unchecked must not read as one that agreed"
            % start_marker
        )
    guard_pos = launcher.find(guard_line, start)
    if guard_pos == -1:
        pytest.fail(
            "bin/oss-workspace's block starting at %r no longer opens with %r "
            "-- a block that went unchecked must not read as one that agreed"
            % (start_marker, guard_line)
        )
    tail_start = guard_pos + len(guard_line)
    depth = 0
    end = -1
    offset = tail_start
    heredoc_close = None
    for line in launcher[tail_start:].splitlines(keepends=True):
        offset += len(line)
        stripped = line.strip()
        # A heredoc body is not shell -- FIND_CONSUMER's own body is python,
        # and a line like "if not isinstance(doc, dict):" would otherwise be
        # read as a shell `if` and corrupt the depth count. Skip everything
        # between a `<<'MARKER'` opener and the bare MARKER line that closes
        # it, the same way a real shell would.
        if heredoc_close is not None:
            if stripped == heredoc_close:
                heredoc_close = None
            continue
        if "<<'" in stripped:
            marker = stripped.split("<<'", 1)[1].split("'", 1)[0]
            heredoc_close = marker
            continue
        if stripped.startswith("if "):
            depth += 1
        elif stripped == "fi":
            if depth == 0:
                end = offset
                break
            depth -= 1
    if end == -1:
        pytest.fail(
            "bin/oss-workspace's block starting at %r never closes its outer "
            "fi -- a block that went unchecked must not read as one that "
            "agreed" % start_marker
        )
    return launcher[start:end]


def _extract_acquire_block():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    return _extract_block(ACQUIRE_START, ACQUIRE_GUARD, launcher)


def _extract_decide_block():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    return _extract_block(DECIDE_START, DECIDE_GUARD, launcher)


def _sh_single_quote(value):
    """Embed value -- which may carry a literal newline -- as a POSIX sh
    single-quoted literal, the standard close/escape/reopen idiom.
    """
    quote = chr(39)
    escaped = quote + "\\" + quote + quote
    return quote + value.replace(quote, escaped) + quote


def _deeply_nested_registry(depth=40000):
    """Valid JSON, nested deep enough that CPython's json.load raises
    RecursionError rather than parsing it -- neither OSError nor ValueError,
    so it is not caught by the block's own except (OSError, ValueError).
    """
    return "[" * depth + "]" * depth


def _run_acquire_block(tmp_path, registry_content, python_bin=None):
    """Run the extracted FIND_CONSUMER acquisition block under sh, with a real
    python and a fake HOME carrying the given consumer registry, and echo the
    two variables under test back out on stdout so the assertion does not have
    to parse stderr prose to know what the block computed.
    """
    if python_bin is None:
        python_bin = sys.executable
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        registry_content, encoding="utf-8"
    )
    script = tmp_path / "run_acquire.sh"
    script.write_text(
        # set -eu: bin/oss-workspace itself runs under it (:31). Without this a
        # crashed probe that also happens to kill the WHOLE extracted script
        # under errexit would look identical to one that survived -- the #588
        # blind spot, one call site over.
        "set -eu\n"
        "python_bin=%s\n"
        "%s\n"
        "echo \"CHANNEL_SCRIPT:[$channel_script]\"\n"
        "echo \"FIND_CONSUMER_STATUS:[$find_consumer_status]\"\n"
        % (_sh_single_quote(python_bin), _extract_acquire_block()),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = str(home)
    verify = subprocess.run(
        [sys.executable, "-c", "import os,sys; sys.stdout.write(os.path.expanduser(chr(126)))"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )
    resolved = verify.stdout
    if os.path.normcase(os.path.normpath(resolved)) != os.path.normcase(os.path.normpath(str(home))):
        pytest.skip(
            "os.path.expanduser resolved to %r instead of the fixture's %r "
            "on this platform (python %s) -- the HOME/USERPROFILE redirect did "
            "not take, so this shape is untested here" % (resolved, str(home), sys.version.split()[0])
        )
    return subprocess.run(
        ["sh", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
    )


def test_a_recursion_error_leaves_status_nonzero_and_script_empty(tmp_path):
    """The positive control: a crashed probe must leave find_consumer_status
    nonzero, channel_script empty, AND must not take the whole extracted
    script down with it under set -eu -- the identical #588 shape at this
    second call site.
    """
    done = _run_acquire_block(tmp_path, _deeply_nested_registry())
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "CHANNEL_SCRIPT:[]" in done.stdout, done.stdout
    assert "FIND_CONSUMER_STATUS:[0]" not in done.stdout, done.stdout


def test_a_well_formed_absent_registry_leaves_status_zero(tmp_path):
    """The must-fire control's own control: a validly-formed registry that
    simply declares no supertool install must still leave find_consumer_status
    at 0 -- an ordinary absence must not be mistaken for a crash.
    """
    done = _run_acquire_block(tmp_path, json.dumps({"plugins": {}}))
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "CHANNEL_SCRIPT:[]" in done.stdout, done.stdout
    assert "FIND_CONSUMER_STATUS:[0]" in done.stdout, done.stdout


def test_a_well_formed_registry_with_the_consumer_present_is_found(tmp_path):
    """A registry naming a real install that DOES hold the consumer file must
    still report the ordinary answer: status 0, channel_script pointing at it.
    """
    install_dir = tmp_path / "install"
    consumer_dir = install_dir / "notifiers" / "claude-channel"
    consumer_dir.mkdir(parents=True)
    consumer_path = consumer_dir / "channel.ts"
    consumer_path.write_text("// stub\n", encoding="utf-8")
    registry = json.dumps({
        "plugins": {"supertool@example": [{"installPath": str(install_dir)}]}
    })
    done = _run_acquire_block(tmp_path, registry)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "FIND_CONSUMER_STATUS:[0]" in done.stdout, done.stdout
    assert "CHANNEL_SCRIPT:[%s]" % consumer_path in done.stdout, done.stdout


# --- the decision chain: a crash must render a DIFFERENT sentence than an -------
# --- ordinary absence, fed synthetic inputs so claude/bun need not be on -------
# --- PATH for this to exercise the new branch --------------------------------


def _run_decide_block(find_consumer_status, channel_script="", channel_registered=0):
    script_text = (
        "set -eu\n"
        "CHANNEL_SERVER=%s\n"
        "find_consumer_status=%s\n"
        "channel_script=%s\n"
        "channel_registered=%s\n"
        "registered_command=\"\"\n"
        "registered_args=\"\"\n"
        "%s\n"
        % (
            _sh_single_quote("oss-channel"),
            find_consumer_status,
            _sh_single_quote(channel_script),
            channel_registered,
            _extract_decide_block(),
        )
    )
    return subprocess.run(
        ["sh", "-c", script_text],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def test_a_crashed_probe_reports_unknown_not_absent(tmp_path):
    """The positive control: find_consumer_status nonzero must produce a
    sentence saying the answer is UNKNOWN, not the plain "was not found"
    sentence a genuine absence gets below.
    """
    done = _run_decide_block(find_consumer_status=1)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "UNKNOWN" in done.stderr, done.stderr
    assert "crashed" in done.stderr, done.stderr
    assert "was not found in" not in done.stderr, done.stderr


def test_a_genuine_absence_still_reports_not_found(tmp_path):
    """The must-fire control's own control: a well-formed probe (status 0)
    that simply found nothing must still get the ORIGINAL "was not found"
    sentence, unaffected by the new branch above it.
    """
    done = _run_decide_block(find_consumer_status=0, channel_script="", channel_registered=0)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "was not found in" in done.stderr, done.stderr
    assert "UNKNOWN" not in done.stderr, done.stderr
