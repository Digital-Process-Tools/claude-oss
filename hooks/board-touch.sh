#!/bin/sh
# PostToolUse hook for #516 -- see scripts/board_touch.py for the mechanism and the
# reasoning. This wrapper only picks an interpreter and pipes stdin through; every
# decision (classification, settle delay, where the cache lives) is in the Python
# module, the same split as batch-hint.sh and session-start-update.sh beside it.

python="python3"
command -v python3 >/dev/null 2>&1 || python="python"
command -v "$python" >/dev/null 2>&1 || { echo "{}"; exit 0; }

exec "$python" "${CLAUDE_PLUGIN_ROOT}/scripts/board_touch.py"
