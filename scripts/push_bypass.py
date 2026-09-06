#!/usr/bin/env python3
"""Detect a branch-protection bypass in a git push receipt -- #1119.

`commands/release.md` has the release session commit the changelog fold and
the version-site bumps, then push that commit directly to the default
branch. `CLAUDE.md`'s "Who decides" table lists committing anything to the
default branch outside a pull request as a stop row with no content
exception. Observed cutting v0.25.0: on an ordinary push from an account
holding bypass privileges, GitHub's classic branch protection does not
refuse -- it silently records a bypass and lets the push through, announced
only in the push's own stderr:

    remote: Bypassed rule violations for refs/heads/main:
    remote: - 14 of 14 required status checks are expected.

Nothing parsed that line before this module: supertool's own receipt marks
the stream "provenance UNKNOWN", and the state file records a push that
looks identical to one that satisfied every required check. This is the
parse -- given the text of a push's own captured output (stdout and stderr
combined, whatever the caller captured), say whether a bypass happened.

This module deliberately does not decide what to do about a bypass (route
the release commit through a pull request, write a narrow documented
exception, or remove bypass privileges from the release path). That is a
governance decision named in #1119 as still open. What this closes is
narrower: the bypass must never render the same as a clean push.

Three states, not two, because an absent receipt is a different fact from a
clean one:

  clean            the literal string "Bypassed rule violations" is absent
  bypassed         it is present -- the push went through on a bypass
                    grant rather than on every required check passing
  could-not-tell   there is nothing to read at all: the caller never
                    captured the push's own output, or captured only
                    whitespace. An absent receipt must never read as clean.

Exit codes, because a shell reads those and never reads prose:

  0   clean
  1   bypassed
  3   could-not-tell
  2   argparse usage error
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STATE_CLEAN = "clean"
STATE_BYPASSED = "bypassed"
STATE_COULD_NOT_TELL = "could-not-tell"

# The exact phrase GitHub's own remote prints, observed verbatim cutting
# v0.25.0 (#1119). Matched literally rather than with a looser pattern: this
# is GitHub's own wording, not something this repo composes, and a looser
# match risks firing on unrelated prose quoting the phrase in a commit
# message or an issue body pulled into the same captured text.
_BYPASS_MARKER = "Bypassed rule violations"

EXIT_CLEAN = 0
EXIT_BYPASSED = 1
EXIT_COULD_NOT_TELL = 3


def scan(text):
    """Classify a push receipt's text into one of the three states above.

    ``text`` may be ``None`` -- a caller that never captured a push's
    output must not crash this, and must not get ``clean`` back either,
    because a crash or a default here is one more way for a silent bypass
    to go unreported.
    """
    if text is None or not str(text).strip():
        return STATE_COULD_NOT_TELL
    if _BYPASS_MARKER in str(text):
        return STATE_BYPASSED
    return STATE_CLEAN


_EXIT_CODES = {
    STATE_CLEAN: EXIT_CLEAN,
    STATE_BYPASSED: EXIT_BYPASSED,
    STATE_COULD_NOT_TELL: EXIT_COULD_NOT_TELL,
}

_MESSAGES = {
    STATE_CLEAN: (
        "clean -- no branch-protection bypass language found in the "
        "captured push receipt"
    ),
    STATE_BYPASSED: (
        "bypassed -- the push receipt contains '{0}': this push went "
        "through on a bypass grant, not on every required check passing. "
        "Report this in the release report; this tool does not decide "
        "what to do about it (#1119)".format(_BYPASS_MARKER)
    ),
    STATE_COULD_NOT_TELL: (
        "could-not-tell -- nothing was captured for this push's own "
        "output. An absent receipt must never be read as a clean push"
    ),
}


def _read_source(source):
    """Read the receipt text from a path, or from stdin when ``source`` is
    ``-``. Mirrors ``review_return.py``'s own ``_read_source`` shape:
    return ``(text, error)`` rather than raising, so a read failure is a
    state (``could-not-tell``, via the CLI) and not a crash.
    """
    if source == "-":
        try:
            return sys.stdin.read(), None
        except OSError as exc:  # pragma: no cover - stdin rarely fails
            return None, "could not read stdin: {0!r}".format(exc)
    try:
        return Path(source).read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, "could not read {0}: {1!r}".format(source, exc)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Scan a git push's captured output for GitHub's branch-"
            "protection bypass marker, so a bypassed push is never "
            "indistinguishable from a clean one (#1119)."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="path to a file holding the push's captured output, or - for stdin",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of prose"
    )
    args = parser.parse_args(argv)

    text, error = _read_source(args.source)
    if error is not None:
        state = STATE_COULD_NOT_TELL
        message = "{0} -- {1}".format(_MESSAGES[state], error)
    else:
        state = scan(text)
        message = _MESSAGES[state]

    if args.json:
        import json

        print(json.dumps({"state": state, "message": message}))
    else:
        print("PUSH-BYPASS: {0}".format(state))
        print("  {0}".format(message))
    return _EXIT_CODES[state]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
