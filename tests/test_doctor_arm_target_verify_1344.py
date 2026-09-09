"""#1344: `check_mcp_channel_registration`'s #1307 relay
(`OSS_WORKSPACE_CHANNEL_ARM_TARGET`) converted ANY non-empty arm target
differing from the label under check into a clean `OK`, with nothing
verifying the named server actually resolves via `claude mcp get`. A stale
export left over from an earlier session, or a value inherited from an
unrelated parent shell, would silence a genuine `not-registered` finding
forever -- exactly the kind of relay #1307's own docstring warns a caller
not to trust unverified.

Every test drives the real `check_mcp_channel_registration`/
`mcp_channel_registration_state`, injecting `run`/`which` the same way
`tests/test_doctor_mcp_channel_registration_621.py` already does, extended
here with a per-server-name `run` fake so the SECOND `claude mcp get` call
(against the arm target) can answer differently from the first (against the
label under check).
"""

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


def _run_by_server(mapping):
    """A `run` fake answering `claude mcp get <server>` differently per
    `<server>` -- `mapping` is `{server_name: (returncode, stdout_text)}`.
    A name not in `mapping` answers non-zero, empty (not registered)."""

    def run(cmd, **kwargs):
        server = cmd[3] if len(cmd) > 3 else None
        returncode, text = mapping.get(server, (1, ""))
        return _FakeCompleted(returncode, text.encode("utf-8"))

    return run


def _which_ok(name):
    return "/usr/bin/claude"


def test_an_unverified_arm_target_does_not_silently_become_ok():
    """Must-fire: the relay names a server (`plugin:supertool:claude-channel`)
    that `claude mcp get` does NOT actually know about -- a stale export or a
    value inherited from an unrelated shell. This must NOT render as `OK`;
    the real gap (nothing carries the channel into a session) must still be
    reported."""
    doctor.check_mcp_channel_registration(
        which=_which_ok,
        run=_run_by_server({}),  # oss-channel AND the arm target both absent
        env={"OSS_WORKSPACE_CHANNEL_ARM_TARGET": "plugin:supertool:claude-channel"},
    )
    level, message = doctor.FINDINGS[-1]
    assert level != "OK", (level, message)
    assert "plugin:supertool:claude-channel" in message, message


def test_a_verified_arm_target_still_renders_ok(tmp_path):
    """Positive control: when the arm target DOES resolve to a real,
    existing consumer, this must still render `OK` naming it -- the
    verification must not become a second false-negative source over the
    real #1307 case it was written for."""
    consumer = tmp_path / "channel.ts"
    consumer.write_text("// consumer\n", encoding="utf-8")
    arm_text = "Type: stdio\nCommand: bun\nArgs: {}\n".format(consumer)
    doctor.check_mcp_channel_registration(
        which=_which_ok,
        run=_run_by_server({"plugin:supertool:claude-channel": (0, arm_text)}),
        env={"OSS_WORKSPACE_CHANNEL_ARM_TARGET": "plugin:supertool:claude-channel"},
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", (level, message)
    assert "plugin:supertool:claude-channel" in message, message


def test_a_could_not_ask_verification_is_not_reported_as_ok_either():
    """Third state: the PRIMARY ask (oss-channel) answers cleanly
    (not-registered), but the SECOND ask -- verifying the arm target --
    itself could not be made. This must not read as either a clean OK or a
    plain absence; the message must say verification failed, not that
    nothing is there."""

    def run(cmd, **kwargs):
        server = cmd[3] if len(cmd) > 3 else None
        if server == "plugin:supertool:claude-channel":
            raise OSError("boom")
        return _FakeCompleted(1, b"")

    doctor.check_mcp_channel_registration(
        which=_which_ok,
        run=run,
        env={"OSS_WORKSPACE_CHANNEL_ARM_TARGET": "plugin:supertool:claude-channel"},
    )
    level, message = doctor.FINDINGS[-1]
    assert level != "OK", (level, message)
