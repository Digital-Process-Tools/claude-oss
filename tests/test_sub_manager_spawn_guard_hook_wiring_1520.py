"""#1520, the same gap #490's own wiring test (test_batch_hint_hook_wiring_490.py)
was written to close for a different hook: a unit test that only imports
`scripts/sub_manager_spawn_guard.py` directly never proves the manifest or the
shell wrapper are wired at all. This file parses `hooks/hooks.json` itself and
drives the real wrapper the way the harness would.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import spawn_guard  # noqa: E402


def _hooks_json() -> dict:
    return json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))


def test_pre_tool_use_agent_entry_is_wired_to_the_wrapper():
    manifest = _hooks_json()
    pre = manifest["hooks"]["PreToolUse"]
    matching = [entry for entry in pre if entry.get("matcher") == "Agent"]
    assert matching, f"no PreToolUse entry matches Agent: {pre!r}"
    commands = [h["command"] for entry in matching for h in entry["hooks"]]
    assert any("sub-manager-spawn-guard.sh" in cmd for cmd in commands), commands


def test_the_wrapper_script_exists_and_is_executable():
    wrapper = ROOT / "hooks" / "sub-manager-spawn-guard.sh"
    assert wrapper.exists()
    assert os.access(wrapper, os.X_OK), (
        "hooks/sub-manager-spawn-guard.sh must be executable"
    )


def test_post_tool_use_entries_survived_the_edit():
    # Negative control paired with the PreToolUse assertion above: adding
    # the new block must not have displaced the existing one.
    manifest = _hooks_json()
    assert "PostToolUse" in manifest["hooks"]
    commands = [
        h["command"]
        for entry in manifest["hooks"]["PostToolUse"]
        for h in entry["hooks"]
    ]
    assert any("batch-hint.sh" in cmd for cmd in commands), commands
    assert any("board-touch.sh" in cmd for cmd in commands), commands


def test_wrapper_denies_end_to_end_through_the_real_shell_invocation(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    import time

    sys.path.insert(0, str(ROOT / "scripts"))
    import agent_role  # noqa: E402

    agent_role.write_role_marker(
        "sub-manager", root=str(tmp_path), written_at=time.time()
    )

    payload = json.dumps(
        {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "oss:sub-manager",
                "description": "d",
                "prompt": "p",
            },
            "cwd": str(tmp_path),
        }
    )
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env.pop("OSS_AGENT_ROLE", None)
    result = spawn_guard.run(
        ["sh", str(ROOT / "hooks" / "sub-manager-spawn-guard.sh")],
        subject="whether the wrapper script is wired to the hook at all",
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_wrapper_allows_end_to_end_when_no_role_is_declared(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    payload = json.dumps(
        {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "oss:sub-manager",
                "description": "d",
                "prompt": "p",
            },
            "cwd": str(tmp_path),
        }
    )
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env.pop("OSS_AGENT_ROLE", None)
    result = spawn_guard.run(
        ["sh", str(ROOT / "hooks" / "sub-manager-spawn-guard.sh")],
        subject="whether the wrapper allows an unforbidden spawn through",
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
