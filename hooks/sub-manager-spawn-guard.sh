#!/bin/sh
# PreToolUse hook for #1520 -- see scripts/sub_manager_spawn_guard.py for the mechanism
# and the reasoning. This wrapper only picks an interpreter and pipes stdin through;
# every decision (which subagent_type, which role, deny or allow) is in the Python
# module, the same split as batch-hint.sh, board-touch.sh and session-start-update.sh
# beside it. A missing interpreter must fail open (allow the spawn), never deny a call
# this hook could not actually evaluate.

python="python3"
command -v python3 >/dev/null 2>&1 || python="python"
command -v "$python" >/dev/null 2>&1 || { echo "{}"; exit 0; }

exec "$python" "${CLAUDE_PLUGIN_ROOT}/scripts/sub_manager_spawn_guard.py"
