#!/bin/sh
# Keep this plugin current, without ever making a session wait (#480).
#
# The whole job of this file is to fork and return. Every decision -- whether auto-update
# is switched off, which plugin to name, what to record -- is in scripts/plugin_update.py,
# because a decision written in shell here is a second copy of one already made there,
# and this half runs where nobody sees its output.
#
# Nothing is printed on the happy path. A SessionStart hook's stdout is injected into the
# session, and a line printed on every start whatever happened is the line nobody reads.
# The receipt is what carries the answer, and `/oss:doctor` is what reads it out.
#
# THE FALLBACK, NOT THE PRIMARY PATH, as of #753. `bin/oss-workspace` now calls
# scripts/plugin_update.py SYNCHRONOUSLY, before `exec claude`, for every session it
# opens: an update that lands before the session starts has no reload/restart window
# to be silent about, which is what this hook's own SessionStart timing could never
# fix -- the update lands AFTER the session has already resolved its plugins. This
# hook still exists because it is the only thing that ever runs for a `claude` started
# by hand, which never reaches the launcher at all. scripts/plugin_update.py's own
# debounce means that when the launcher DID just run this, this hook's call a few
# seconds later finds a receipt too fresh to re-check and stands down without
# touching the network again.

root="${CLAUDE_PROJECT_DIR:-$PWD}"
python="python3"
command -v python3 >/dev/null 2>&1 || python="python"
command -v "$python" >/dev/null 2>&1 || exit 0

# Detached, output discarded: this outlives the hook by design, and a hook that waits on
# a network call has made every session start as slow as the slowest registry.
"$python" "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_update.py" --root "$root" >/dev/null 2>&1 &

exit 0
