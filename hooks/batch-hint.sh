#!/bin/sh
# PostToolUse hook for #490 -- see scripts/batch_hint.py for the mechanism and
# the reasoning. This wrapper only picks an interpreter and pipes stdin
# through; every decision (classification, threshold, state) lives in the
# Python module, same split as session-start-update.sh above it.

python="python3"
command -v python3 >/dev/null 2>&1 || python="python"
command -v "$python" >/dev/null 2>&1 || { echo "{}"; exit 0; }

exec "$python" "${CLAUDE_PLUGIN_ROOT}/scripts/batch_hint.py"
