"""#490, the auditor's own finding: the classify_command/update_state unit
tests and the end-to-end test in tests/test_batch_hint_490.py all invoke
`scripts/batch_hint.py` directly (as a subprocess or an import) and never go
through `hooks/hooks.json` or `hooks/batch-hint.sh` at all -- so a malformed
matcher, a broken `command` string, or invalid JSON in the manifest would
silently mean the hint never fires in a real session, with no CI leg turning
red for it. This file is the guard for that gap: it parses the manifest
itself and asserts the shape a PostToolUse Bash hook actually needs, and
separately drives the shell wrapper exactly as the harness would.
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


def test_hooks_json_is_valid_json():
    _hooks_json()  # raises on malformed JSON; the assertion is that this doesn't


def test_post_tool_use_bash_entry_is_wired_to_the_wrapper():
    manifest = _hooks_json()
    post = manifest["hooks"]["PostToolUse"]
    matching = [entry for entry in post if entry.get("matcher") == "Bash"]
    assert matching, f"no PostToolUse entry matches Bash: {post!r}"
    commands = [h["command"] for entry in matching for h in entry["hooks"]]
    assert any("batch-hint.sh" in cmd for cmd in commands), commands


def test_the_wrapper_script_exists_and_is_executable():
    wrapper = ROOT / "hooks" / "batch-hint.sh"
    assert wrapper.exists()
    assert os.access(wrapper, os.X_OK), "hooks/batch-hint.sh must be executable"


def test_session_start_entry_survived_the_edit():
    # Negative control paired with the PostToolUse assertion above: adding
    # the new block must not have displaced the existing one.
    manifest = _hooks_json()
    assert "SessionStart" in manifest["hooks"]
    commands = [
        h["command"]
        for entry in manifest["hooks"]["SessionStart"]
        for h in entry["hooks"]
    ]
    assert any("session-start-update.sh" in cmd for cmd in commands), commands


def test_wrapper_script_end_to_end_through_the_real_shell_invocation(tmp_path):
    # Drives hooks/batch-hint.sh itself (not scripts/batch_hint.py directly),
    # the way the harness actually would, with CLAUDE_PLUGIN_ROOT set the way
    # a real plugin install sets it.
    payload = json.dumps(
        {
            "session_id": "wiring-test-490",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "supertool 'read:a.py'"},
        }
    )
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env["BATCH_HINT_STATE_DIR"] = str(tmp_path)
    result = spawn_guard.run(
        ["sh", str(ROOT / "hooks" / "batch-hint.sh")],
        subject="whether the wrapper script is wired to the hook at all",
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out == {}  # one call, below threshold -- silent, and valid JSON
