#!/usr/bin/env bash
# Launcher for doctor.py.
#
# A bash wrapper exists because a command declared in a plugin has no fallback: if
# the interpreter is missing, the raw `python3 ...` form turns every invocation into
# an error with no explanation. This one always prints something a human can act on.
#
# Bare `python3` is never invoked. On Windows the App Execution Alias resolves and
# then fails, so `command -v python3` succeeding proves nothing. Each candidate is
# proved by running it and comparing a sentinel for EQUALITY -- `-c pass` succeeds on
# a stub. Probing reads from </dev/null so nothing consumes the caller's stdin.
#
# EXIT CODES: 0, always. This is a diagnostic.

set -u

# Derived with builtins only. `dirname` is an external binary, and the environment
# where this fallback matters most -- a broken or empty PATH -- is exactly the one
# where it is not found. Using it collapsed the root to `/` and reported the plugin
# checkout as incomplete, which is a true-sounding answer to the wrong question.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}"
else
    # Both separators. Under Git Bash `$0` arrives as `D:\a\repo\scripts\doctor.sh`,
    # where `${0%/*}` strips nothing, falls through to `.`, and resolves the plugin
    # root against the CALLER's directory -- a confident answer about the wrong tree.
    # Found by the Windows leg on the first CI run; every POSIX leg was green.
    _self_dir="${0%/*}"
    [ "$_self_dir" = "$0" ] && _self_dir="${0%\\*}"
    [ "$_self_dir" = "$0" ] && _self_dir="."
    PLUGIN_ROOT="$(cd "${_self_dir}/.." && pwd)"
fi
DOCTOR="${PLUGIN_ROOT}/scripts/doctor.py"

SENTINEL="oss-doctor-python-ok"

find_python() {
    local candidate
    local out

    if [ -n "${VIRTUAL_ENV:-}" ] && [ -f "${VIRTUAL_ENV}/pyvenv.cfg" ]; then
        for candidate in "${VIRTUAL_ENV}/bin/python" "${VIRTUAL_ENV}/Scripts/python.exe"; do
            out=$("$candidate" -c "import sys; sys.stdout.write('${SENTINEL}')" 2>/dev/null </dev/null)
            if [ "$out" = "$SENTINEL" ]; then
                printf '%s' "$candidate"
                return 0
            fi
        done
    fi

    for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
        out=$("$candidate" -c "import sys; sys.stdout.write('${SENTINEL}')" 2>/dev/null </dev/null)
        if [ "$out" = "$SENTINEL" ]; then
            printf '%s' "$candidate"
            return 0
        fi
    done

    out=$(py -3 -c "import sys; sys.stdout.write('${SENTINEL}')" 2>/dev/null </dev/null)
    if [ "$out" = "$SENTINEL" ]; then
        printf '%s' "py -3"
        return 0
    fi

    return 1
}

if [ ! -f "$DOCTOR" ]; then
    echo "FAIL doctor.py not found at ${DOCTOR}; the plugin checkout is incomplete"
    echo "VERDICT: could not run"
    exit 0
fi

if ! PYTHON=$(find_python); then
    echo "FAIL no working Python found (tried python3.14 down to python3.9, python3, python, py -3)"
    echo "FAIL the diagnostic itself could not run; this says nothing about the repo"
    echo "VERDICT: could not run"
    exit 0
fi

# shellcheck disable=SC2086
$PYTHON "$DOCTOR"
exit 0
