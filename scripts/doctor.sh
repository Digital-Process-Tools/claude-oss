#!/usr/bin/env bash
# Launcher for doctor.py.
#
# A bash wrapper exists because a command declared in a plugin has no fallback: if
# the interpreter is missing, the raw `python3 ...` form turns every invocation into
# an error with no explanation. This one always prints something a human can act on.
#
# Bare `python3` is never invoked BLINDLY. On Windows the App Execution Alias
# resolves and then fails, so `command -v python3` succeeding proves nothing. Each
# candidate is proved by running it and comparing a sentinel for EQUALITY -- `-c pass`
# succeeds on a stub. Probing reads from </dev/null so nothing consumes the caller's
# stdin.
#
# ORDER (#398). The enumeration is a FALLBACK for when bare `python3` does not run,
# not a ranking of versions, and it used to be walked newest-first with `python3`
# seventh. That encoded *newest is best* and consulted neither of the two facts that
# decide it here:
#
#   * The CI matrix is 3.9-3.12, so `python3.14` was first-tried and never-tested.
#     Thirteen green legs said nothing about the interpreter this launcher preferred.
#   * A `python3.N` on PATH is no evidence it is the good BUILD. Measured on macOS
#     arm64: the only 3.14 was an x86_64 build under Rosetta in the Intel prefix,
#     while the native arm64 interpreter answers to bare `python3` -- so preferring
#     the explicit minor is exactly what selected the translated one, and
#     `bash scripts/doctor.sh` disagreed with `python3 scripts/doctor.py` on the same
#     tree, by two warnings.
#
# So: bare `python3` first, because PATH order is the machine's own answer to which
# build of Python it wants and it is what the documented direct invocation gets; then
# the band CI covers, newest first; then newer-than-band; then `python`; then `py -3`.
# The cost is stated rather than hidden: a machine holding both an explicit 3.14 and
# an explicit 3.12 now runs the older one. That is deliberate -- the older one is the
# one this project's tests have ever been run on. Nothing is REMOVED from the walk, so
# an interpreter newer than the band is still found when it is the only one there.
#
# Architecture is deliberately NOT part of the selection. doctor.py reports whether it
# is running translated, and does so only after the choice; asking the same question
# from shell means running a probe snippet under every candidate, and doctor.py's own
# probe returns `unknown` on Linux and Windows -- so the rule would have no signal on
# two of the three CI platforms and would silently degrade to "prefer the first", which
# is a confident answer where a gap belongs. Preferring bare `python3` gets the native
# build here by a route that needs no probe at all: PATH already ranks the prefixes.
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

    for candidate in python3 python3.12 python3.11 python3.10 python3.9 python3.13 python3.14 python; do
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
    echo "FAIL no working Python found (tried python3, python3.12, python3.11, python3.10, python3.9, python3.13, python3.14, python, py -3)"
    echo "FAIL the diagnostic itself could not run; this says nothing about the repo"
    echo "VERDICT: could not run"
    exit 0
fi

# Arguments are forwarded, not dropped: `--root` is unreachable through the command
# surface otherwise, and a flag that only works when you bypass the launcher is a flag
# nobody has.
# shellcheck disable=SC2086
$PYTHON "$DOCTOR" "$@"
exit 0
