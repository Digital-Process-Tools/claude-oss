"""PreToolUse guard: refuse an Agent(subagent_type: "oss:sub-manager") spawn
from inside an already-running sub-manager (#1520).

#1469's second suggestion asked whether the harness exposes a hook that could
refuse this spawn the same way `agent_role.py` already refuses a publish call
in code. #1022/PR #1034 found the mechanism plausible but left the exact
`tool_input` field name unconfirmed and declined to build on it. #1520
confirmed it against the published SDK docs: `code.claude.com/docs/en/agent-
sdk/hooks` lists `Agent` among the built-in tool names a `PreToolUse` matcher
can target, using the same `hookSpecificOutput.permissionDecision: "deny"`
JSON-output path documented for `Write`/`Edit`; `AgentInput`
(`code.claude.com/docs/en/agent-sdk/typescript`) has exactly three fields --
`description`, `prompt`, `subagent_type` -- so `tool_input.subagent_type` is
what this reads.

This is the same one-word boundary `agent_role.py` already makes code-level
for release authority (#695), aimed at a different mistake: a running
sub-manager spawning a *nested* sub-manager -- re-running the tick loop's
own selection, claim and dispatch from inside a tick that is already running
them -- is never something a lane should do, and #695's own argument for why
that boundary belongs in code and not only in prose applies here unchanged.

Only ever denies the one condition #1520 names: `tool_input.subagent_type ==
SUB_MANAGER_SUBAGENT_TYPE`, AND the caller's own declared role (read through
`agent_role.current_role`, inheriting its env-then-marker-file resolution and
its stale/malformed-fails-open behaviour unchanged) is already
`agent_role.SUB_MANAGER`. Anything else -- a different subagent_type, no
declared role, a stale or malformed marker, a payload this hook cannot even
parse -- passes through allowed. Never denies for a reason the caller was not
told: a crash reading the role, an unreadable payload, an unexpected shape,
all resolve to allow rather than to an unexplained refusal.

Three states, not two (this repository's own defect class -- see CLAUDE.md):
`decide()` returns `DECISION_DENY`, `DECISION_ALLOW`, or
`DECISION_ALLOW_COULD_NOT_TELL` -- the last one distinguishes "looked and
found nothing to deny" from "could not look at all", both of which pass the
call through, but only one of which is a genuine clean read. Nothing today
consumes the distinction outside this module's own tests; it exists so a
future caller (a `doctor.py` check, a log) has it to read rather than having
to re-derive it.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_role  # noqa: E402

#: The one subagent_type this guard refuses, and only when the caller's own
#: role is already `agent_role.SUB_MANAGER`. Spelled out as a constant
#: rather than derived from a naming convention -- the `oss:` prefix is a
#: fact about how this plugin is installed, not something to infer
#: structurally from `agent_role.SUB_MANAGER` or any other value here.
SUB_MANAGER_SUBAGENT_TYPE = "oss:sub-manager"

DECISION_DENY = "deny"
DECISION_ALLOW = "allow"
DECISION_ALLOW_COULD_NOT_TELL = "allow-could-not-tell"

#: The message surfaced to the caller as `permissionDecisionReason` -- read
#: by whichever agent's spawn attempt this hook refused, so it names the
#: alternative rather than only the refusal.
_DENY_REASON = (
    "a running sub-manager (#695's role marker) may not spawn a nested "
    "oss:sub-manager: tick ownership and release authority are withheld "
    "from the per-tick sub-manager by design (#695, #1520) -- spawn "
    "oss:tick-dispatch or a developer lane instead"
)


def decide(payload, root=None):
    """The guard's verdict for one PreToolUse payload: `(decision, reason)`.

    `reason` is the human string for `DECISION_DENY`, `None` otherwise.
    `root` overrides where `agent_role.current_role` looks for the marker
    file; a real caller leaves it unset and this falls back to the
    payload's own `cwd` (the harness's convention -- see `board_touch.py`),
    then `os.getcwd()`.
    """
    if not isinstance(payload, dict):
        return DECISION_ALLOW_COULD_NOT_TELL, None
    tool_name = payload.get("tool_name")
    if tool_name not in (None, "Agent"):
        return DECISION_ALLOW, None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return DECISION_ALLOW_COULD_NOT_TELL, None
    subagent_type = tool_input.get("subagent_type")
    if subagent_type != SUB_MANAGER_SUBAGENT_TYPE:
        return DECISION_ALLOW, None
    resolved_root = root if root is not None else (payload.get("cwd") or os.getcwd())
    try:
        role = agent_role.current_role(root=resolved_root)
    except Exception:  # noqa: BLE001 -- never deny over a read failure this
        # hook cannot explain to the caller; see the module docstring.
        return DECISION_ALLOW_COULD_NOT_TELL, None
    if role is None or role.strip().lower() != agent_role.SUB_MANAGER:
        return DECISION_ALLOW, None
    return DECISION_DENY, _DENY_REASON


def main(argv=None, stdin_text=None):
    # #846's lesson (see batch_hint.py): sys.stdin can be None when the
    # harness hands this hook a closed standard input; `.read()` on `None`
    # raises `AttributeError`, which a bare `except json.JSONDecodeError`
    # would not catch. This hook must never crash the tool call it is
    # deciding, so both failure shapes fall back to an empty payload, which
    # `decide()` reports as `DECISION_ALLOW_COULD_NOT_TELL` and this
    # function still allows.
    try:
        if stdin_text is not None:
            raw = stdin_text
        elif sys.stdin is None:
            raw = ""
        else:
            raw = sys.stdin.read()
        payload = json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    decision, reason = decide(payload)
    output = {}
    if decision == DECISION_DENY:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
