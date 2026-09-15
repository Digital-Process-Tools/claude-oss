"""#1520: a running sub-manager must not be able to spawn a nested
oss:sub-manager. #1469's second suggestion asked whether the harness exposes
a PreToolUse hook mechanism for this; #1022/PR #1034 found it plausible but
left `tool_input`'s field name unconfirmed and declined to build on it.
#1520 confirms `subagent_type` against the published SDK docs -- this is the
guard that reads it.

Mirrors `tests/test_agent_role_695.py`'s own shape (env-based role, no need
to touch a real git repo for most cases) since `agent_role.current_role`
checks `OSS_AGENT_ROLE` before the marker file.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agent_role  # noqa: E402
import sub_manager_spawn_guard as guard  # noqa: E402


def _payload(subagent_type="oss:sub-manager", tool_name="Agent"):
    return {
        "tool_name": tool_name,
        "tool_input": {
            "subagent_type": subagent_type,
            "description": "d",
            "prompt": "p",
        },
    }


def test_sub_manager_spawning_a_nested_sub_manager_is_denied(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    decision, reason = guard.decide(_payload())
    assert decision == guard.DECISION_DENY
    assert "oss:sub-manager" in reason
    assert "695" in reason


def test_maintainer_role_spawning_sub_manager_is_allowed(monkeypatch):
    """Positive control: a legitimate role spawning the exact same subagent_type
    must not be caught by the same check -- otherwise this would just be
    banning oss:sub-manager outright rather than banning it from a sub-manager."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "maintainer")
    decision, reason = guard.decide(_payload())
    assert decision == guard.DECISION_ALLOW
    assert reason is None


def test_no_role_declared_spawning_sub_manager_is_allowed(monkeypatch):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    decision, _reason = guard.decide(_payload(), root=str(REPO))
    assert decision == guard.DECISION_ALLOW


def test_sub_manager_spawning_a_different_subagent_type_is_allowed(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    decision, _reason = guard.decide(_payload(subagent_type="oss:developer"))
    assert decision == guard.DECISION_ALLOW


def test_sub_manager_role_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "  Sub-Manager  ")
    decision, _reason = guard.decide(_payload())
    assert decision == guard.DECISION_DENY


def test_a_non_agent_tool_call_is_allowed_without_reading_the_role(monkeypatch):
    # If this read the role for every Bash call it would be needlessly slow
    # on the hot path; asserting ALLOW here does not prove that on its own,
    # but pairs with the tool_name check being the very first branch in
    # decide().
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    decision, _reason = guard.decide(_payload(tool_name="Bash"))
    assert decision == guard.DECISION_ALLOW


def test_missing_tool_input_is_could_not_tell_not_a_silent_deny():
    decision, reason = guard.decide({"tool_name": "Agent"})
    assert decision == guard.DECISION_ALLOW_COULD_NOT_TELL
    assert reason is None


def test_non_dict_payload_is_could_not_tell():
    decision, _reason = guard.decide(None)
    assert decision == guard.DECISION_ALLOW_COULD_NOT_TELL


def test_stale_marker_resolves_as_no_role_declared_and_is_allowed(
    tmp_path, monkeypatch
):
    """Positive control paired with test_marker_based_role_is_denied below:
    a stale marker must fail open, the same asymmetry agent_role.py's own
    module docstring documents for release_refusal()."""
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    agent_role.write_role_marker(
        "sub-manager",
        root=str(tmp_path),
        written_at=0.0,  # epoch -- long expired
    )
    decision, _reason = guard.decide(_payload(), root=str(tmp_path))
    assert decision == guard.DECISION_ALLOW


def test_marker_based_role_is_denied(tmp_path, monkeypatch):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    import subprocess
    import time

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    agent_role.write_role_marker(
        "sub-manager", root=str(tmp_path), written_at=time.time()
    )
    decision, reason = guard.decide(_payload(), root=str(tmp_path))
    assert decision == guard.DECISION_DENY
    assert reason is not None


def test_main_prints_deny_json_on_stdout():
    payload = json.dumps(_payload())
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import os

        prior = os.environ.get(agent_role.ROLE_ENV)
        os.environ[agent_role.ROLE_ENV] = "sub-manager"
        try:
            rc = guard.main(stdin_text=payload)
        finally:
            if prior is None:
                os.environ.pop(agent_role.ROLE_ENV, None)
            else:
                os.environ[agent_role.ROLE_ENV] = prior
    assert rc == 0
    out = json.loads(buf.getvalue())
    hook_out = out["hookSpecificOutput"]
    assert hook_out["permissionDecision"] == "deny"
    assert hook_out["hookEventName"] == "PreToolUse"
    assert "oss:sub-manager" in hook_out["permissionDecisionReason"]


def test_main_prints_empty_json_when_allowed(monkeypatch):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = guard.main(stdin_text=json.dumps(_payload()))
    assert rc == 0
    assert json.loads(buf.getvalue()) == {}


def test_main_never_crashes_on_malformed_stdin():
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = guard.main(stdin_text="not json{{{")
    assert rc == 0
    assert json.loads(buf.getvalue()) == {}


def test_main_never_crashes_on_empty_stdin():
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = guard.main(stdin_text="")
    assert rc == 0
    assert json.loads(buf.getvalue()) == {}
