"""#621: `grep mcp scripts/doctor.py` returned nothing. `/oss:doctor` checks the
watch channel NAME and the radar board DECLARATION and nothing between them: whether
any MCP server is registered to carry that channel into a session, and whether the
path it stores still exists. `bin/oss-workspace:873-944` already asks exactly this
question, in states this diagnostic mirrors -- registered/resolvable,
registered/target-absent, registered/unreadable-entry, not-registered, could-not-ask
-- so a maintainer running `/oss:doctor` gets the same answer the launcher already
computes at session-open, instead of two clean OK lines either side of the one
artifact that actually carries the channel.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


class _FakeCompleted:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def _run_answering(text, returncode=0):
    def run(cmd, **kwargs):
        return _FakeCompleted(returncode, text.encode("utf-8"))

    return run


def _run_raising(exc):
    def run(cmd, **kwargs):
        raise exc

    return run


def test_could_not_ask_when_claude_is_not_on_path():
    """The must-fire half for the state that isn't ordinary absence: nothing here
    established that the channel is unregistered, only that nothing could ask."""
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: None, run=_run_answering("")
    )
    assert state == "could-not-ask", (state, detail)

    doctor.check_mcp_channel_registration(which=lambda name: None, run=_run_answering(""))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "not on PATH" in message, message


def test_could_not_ask_when_the_call_itself_fails():
    """The second could-not-ask arm: `claude` is on PATH but the subprocess call
    could not be run at all."""
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude",
        run=_run_raising(OSError("boom")),
    )
    assert state == "could-not-ask", (state, detail)

    doctor.check_mcp_channel_registration(
        which=lambda name: "/usr/bin/claude", run=_run_raising(OSError("boom"))
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)


def test_not_registered_is_the_ordinary_absence(tmp_path):
    """The must-not-fire control for could-not-ask: `claude` answers, cleanly, that
    nothing is configured under this name -- a nonzero exit."""
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude",
        run=_run_answering("", returncode=1),
    )
    assert state == "not-registered", (state, detail)

    doctor.check_mcp_channel_registration(
        which=lambda name: "/usr/bin/claude", run=_run_answering("", returncode=1)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "not registered" in message.lower(), message


def test_registered_resolvable_when_the_stored_path_exists(tmp_path):
    """`bin/oss-workspace:873-879`'s own reasoning: `claude mcp get` answers 0 for
    any CONFIGURED server whether or not the file it names still exists, so
    presence is not readiness -- the stored path must be read and checked too."""
    consumer = tmp_path / "channel.ts"
    consumer.write_text("// consumer\n", encoding="utf-8")
    text = "Type: stdio\nCommand: bun\nArgs: {}\n".format(consumer)
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    assert state == "registered", (state, detail)
    assert str(consumer) in detail, detail

    doctor.check_mcp_channel_registration(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", (level, message)


def test_registered_target_absent_the_registration_outlives_the_file(tmp_path):
    """The must-fire half `bin/oss-workspace`'s own comment names: the path
    `claude mcp add` stores is absolute and version-pinned, and the plugin cache
    drops the old version directory on auto-update -- the registration outlives
    the file, the flag is still passed, and nothing starts."""
    gone = tmp_path / "does-not-exist" / "channel.ts"
    text = "Type: stdio\nCommand: bun\nArgs: {}\n".format(gone)
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    assert state == "target-absent", (state, detail)
    assert str(gone) in detail, detail

    doctor.check_mcp_channel_registration(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert str(gone) in message, message


def test_unreadable_entry_no_args_line_could_be_parsed():
    """Registered (exit 0), but the output carries no Args line -- the shape
    `bin/oss-workspace` also names (project-scope entries print no Command/Args at
    all). Distinct from target-absent: nothing was read to check."""
    text = "Type: sse\nURL: https://example.invalid/mcp\n"
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    assert state == "unreadable-entry", (state, detail)

    doctor.check_mcp_channel_registration(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "unreadable-entry" not in message  # the state name, not the message contract
    assert "no command" in message.lower() or "no args" in message.lower() or "could not" in message.lower(), message


def test_the_check_prints_exactly_one_line_in_every_state(tmp_path):
    """doctor's contract is one line per check."""
    consumer = tmp_path / "channel.ts"
    consumer.write_text("x\n", encoding="utf-8")
    cases = [
        (lambda n: None, _run_answering("")),
        (lambda n: "/usr/bin/claude", _run_answering("", returncode=1)),
        (lambda n: "/usr/bin/claude", _run_answering("Type: stdio\nCommand: bun\nArgs: {}\n".format(consumer))),
        (lambda n: "/usr/bin/claude", _run_answering("Type: stdio\nCommand: bun\nArgs: {}\n".format(tmp_path / "gone.ts"))),
        (lambda n: "/usr/bin/claude", _run_answering("Type: sse\n")),
    ]
    for which, run in cases:
        doctor.FINDINGS.clear()
        doctor.check_mcp_channel_registration(which=which, run=run)
        assert len(doctor.FINDINGS) == 1, doctor.FINDINGS


def test_server_name_matches_bin_oss_workspaces_own_constant():
    """The two files must not drift apart on the name they each ask `claude mcp
    get` about -- one Python constant, one shell constant, and nothing keeps them
    in sync automatically since they live in different languages. This is that
    sync check, in the same spirit as #577's supertool-rule comparison."""
    workspace = (REPO_ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")
    assert 'CHANNEL_SERVER="{}"'.format(doctor.CHANNEL_SERVER) in workspace, (
        "scripts/doctor.py's CHANNEL_SERVER ({!r}) and bin/oss-workspace's own "
        "CHANNEL_SERVER have drifted apart".format(doctor.CHANNEL_SERVER)
    )


def test_target_absent_when_an_ancestor_component_is_a_plain_file(tmp_path):
    """Self-review finding: `NotADirectoryError` (an ancestor of the stored path is
    a plain file, not a directory -- ENOTDIR) is absence too, the same way
    `_locate_on_path` and `supertool_entry_point` both already treat it -- see
    their own `except (FileNotFoundError, NotADirectoryError)` catches. Before this
    fix, `os.stat` raising `NotADirectoryError` fell into the generic `OSError`
    branch and was reported as `target-unreadable` ("this is unknown, not
    confirmed gone") instead of the more useful and more correct `target-absent`,
    which names the concrete removal remedy."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x\n", encoding="utf-8")
    target = blocker / "channel.ts"
    text = "Type: stdio\nCommand: bun\nArgs: {}\n".format(target)
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    assert state == "target-absent", (state, detail)
    assert str(target) in detail, detail


def _run_that_must_not_be_called():
    def run(cmd, **kwargs):
        raise AssertionError(
            "claude mcp get was shelled out to a second time -- the precomputed "
            "OSS_WORKSPACE_MCP_* handoff should have made this call unnecessary"
        )

    return run


def test_a_precomputed_registered_answer_skips_the_second_subprocess_call():
    """#629: `bin/oss-workspace` already asked this at session-open. When it
    hands the answer over via the three OSS_WORKSPACE_MCP_* variables, doctor
    must not shell out again -- `run` raises if it is called at all."""
    consumer_text = "Type: stdio\nCommand: bun\nArgs: /abs/path/channel.ts\n"
    env = {
        "OSS_WORKSPACE_MCP_CHECKED": "1",
        "OSS_WORKSPACE_MCP_STATUS": "0",
        "OSS_WORKSPACE_MCP_OUTPUT": consumer_text,
    }
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude",
        run=_run_that_must_not_be_called(),
        env=env,
    )
    # target-absent, not registered: /abs/path/channel.ts does not exist on the
    # test machine, and that is fine -- the point of this test is that the
    # SOURCE of the answer was the handoff, not a subprocess.
    assert state == "target-absent", (state, detail)
    assert "/abs/path/channel.ts" in detail, detail


def test_a_precomputed_not_registered_answer_also_skips_the_call():
    """Must-fire pair for the state above: a nonzero precomputed status reads as
    not-registered without ever shelling out, the same as the live path does."""
    env = {"OSS_WORKSPACE_MCP_CHECKED": "1", "OSS_WORKSPACE_MCP_STATUS": "1", "OSS_WORKSPACE_MCP_OUTPUT": ""}
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude",
        run=_run_that_must_not_be_called(),
        env=env,
    )
    assert state == "not-registered", (state, detail)


def test_the_handoff_is_ignored_for_a_different_server():
    """`bin/oss-workspace` only ever pre-asks about its own hardcoded channel
    server. A caller asking about a different server must fall through to a
    real ask rather than answering the wrong question from a stale handoff --
    must-not-fire control, paired with the two must-fire tests above."""
    env = {
        "OSS_WORKSPACE_MCP_CHECKED": "1",
        "OSS_WORKSPACE_MCP_STATUS": "0",
        "OSS_WORKSPACE_MCP_OUTPUT": "Type: stdio\nCommand: bun\nArgs: /nope\n",
    }
    state, detail = doctor.mcp_channel_registration_state(
        server="some-other-server",
        which=lambda name: "/usr/bin/claude",
        run=_run_answering("", returncode=1),
        env=env,
    )
    assert state == "not-registered", (state, detail)


def test_a_malformed_precomputed_status_falls_through_to_a_real_ask():
    """The handoff is trusted only when it parses. A non-integer STATUS -- a
    shell quoting mistake, a future format change -- must not silently answer
    `not-registered` for a channel that might actually be registered; it falls
    through to the real subprocess call instead of guessing."""
    env = {
        "OSS_WORKSPACE_MCP_CHECKED": "1",
        "OSS_WORKSPACE_MCP_STATUS": "not-a-number",
        "OSS_WORKSPACE_MCP_OUTPUT": "",
    }
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude",
        run=_run_answering("", returncode=1),
        env=env,
    )
    assert state == "not-registered", (state, detail)


def test_no_handoff_present_asks_normally():
    """Must-not-fire control for the whole feature: an ordinary invocation with
    no OSS_WORKSPACE_MCP_* variables in `env` behaves exactly as before --
    `run` IS called."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(1, b"")

    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude", run=run, env={}
    )
    assert state == "not-registered", (state, detail)
    assert calls, "the real subprocess call was skipped with no handoff present"


def test_run_is_handed_the_resolved_path_not_the_bare_name():
    """#753/#810's own Windows CI regression: `which()` was already called to
    check PATH membership, but `run()` was still handed the bare `"claude"`
    string instead of `which()`'s own resolved, extension-qualified answer --
    which `subprocess.run(shell=False)` cannot turn back into `claude.cmd` on
    Windows. Pin the argv `run` actually receives, not just the state it
    returns, so a regression back to the bare name is caught here rather than
    only on a windows-latest CI leg nobody can run locally."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(1, b"")

    doctor.mcp_channel_registration_state(
        which=lambda name: "/resolved/claude.cmd", run=run, env={}
    )
    assert calls and calls[0][0] == "/resolved/claude.cmd", calls


def test_could_not_ask_when_the_stored_path_carries_an_embedded_null(tmp_path):
    """Self-review finding: `os.stat` raises `ValueError`, not `OSError`, for a
    path carrying an embedded null byte -- the exact class `_dir_state`'s own
    docstring names elsewhere in this file. `~/.claude.json` is JSON, and JSON can
    spell a null, so a malformed or adversarial MCP registration must not raise
    out of this function -- `doctor.py`'s whole contract is exit 0, one VERDICT
    line, never a traceback."""
    text = "Type: stdio\nCommand: bun\nArgs: /tmp/\x00evil\n"
    state, detail = doctor.mcp_channel_registration_state(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    assert state == "could-not-ask", (state, detail)

    doctor.check_mcp_channel_registration(
        which=lambda name: "/usr/bin/claude", run=_run_answering(text)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
