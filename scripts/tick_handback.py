#!/usr/bin/env python3
"""Classify a sub-manager's tick handback -- #695.

The scheduler/sub-manager split (#695) means the scheduler never holds a
tick's payload, so it never watches the sub-manager work. What comes back is
one final message, over the same kind of boundary #392 already put a
classifier on for a reviewer: a spawn that executed and said nothing, and a
spawn that ran cleanly and had nothing to report, are the same bytes unless
something looks. The issue's own sentence: "A sub-manager that died and one
that found nothing to do must not render identically to the scheduler, or
the loop silently stops working and reports a clean board."

`scripts/review_return.py` is the existing shape to copy, per the issue, and
this module copies it rather than re-deriving it: the transport is imported
(`unframe`, `FRAME_INDENT`, `FRAME_END`, `fold_to_one_ascii_line`,
`_read_source`), not reimplemented, because the injection risk at that
boundary (#404 -- an ordinary message quoting the documented heredoc block
ends the stream that carries it) is identical here. A second hand-rolled
frame parser is a second place for that bug to recur.

## The states

  completed        `TICK: completed`, optionally followed by a summary.
                    A tick that read the board and dispatched nothing is
                    `completed`, not a lesser state -- an idle tick is a
                    real, clean answer, and #695 is explicit that this must
                    not collapse onto the died case below.
  blocked           `TICK: blocked` with a `BLOCKER:` line naming what. A
                    `blocked` with no `BLOCKER:` line is undecidable and is
                    `could-not-classify`, not `blocked` -- an unnamed blocker
                    is not a usable blocked state.
  could-not-run     `TICK: could-not-run` with a `REASON:` line naming why
                    the sub-manager itself could not execute a tick (a spawn
                    refusal, a worktree it could not cut, a permission
                    denial before any tick work began). Missing `REASON:` is
                    `could-not-classify`, for the same reason as `blocked`.
  returned-nothing  empty, or whitespace only. This is the "died" case: the
                    spawn executed and its conclusions, if any existed, are
                    lost. It must never be read as `completed`.
  could-not-classify  no `TICK:` header at all, so this module cannot tell a
                    completed tick reported in plain prose from one that
                    silently did nothing -- read the message yourself rather
                    than guess. Also the answer when a header is present but
                    its required companion field (`BLOCKER:` / `REASON:`) is
                    missing.

## What this deliberately does not do

Release authority is not a state here and never will be. A sub-manager's
handback describes one tick; whether the release trigger fired is a fact the
scheduler re-derives itself from the board, and #696 (the releaser agent,
filed separately) is where tag-and-publish authority lives. Nothing in this
module accepts, or needs to accept, a "released" claim from a sub-manager --
see `scripts/agent_role.py` for the code-level half of that withholding.

## Exit codes

Because a shell reads those and never reads prose:

  0   completed
  3   blocked
  4   could-not-run
  5   returned-nothing
  6   could-not-classify
  7   could-not-read (unreadable source, or `--framed` could not unframe it)
  2   argparse usage error
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_return as _rr  # noqa: E402

# A header at the start of a line, tolerating light markdown wrapping the
# same way review_return.py's own header pattern does.
_TICK = re.compile(
    r"^[ \t>*_#]*TICK:[ \t]*(completed|blocked|could-not-run)\b",
    re.MULTILINE | re.IGNORECASE,
)
_BLOCKER = re.compile(r"^[ \t>*_#]*BLOCKER:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)
_REASON = re.compile(r"^[ \t>*_#]*REASON:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)


def _verdict(state, reason, **extra):
    out = {
        "state": state,
        "reason": reason,
        "declared": None,
        "detail": None,
        "quoted": None,
    }
    out.update(extra)
    return out


def classify(message):
    """Sort one sub-manager final message into the five states above.

    ``message`` may be ``None`` -- a harness that hands back no final
    message at all must not crash this, because a crash here is one more
    way for a tick's outcome to go missing quietly.
    """
    if message is None or not str(message).strip():
        return _verdict(
            "returned-nothing",
            "the sub-manager's handback was empty or whitespace-only: the "
            "spawn executed and nothing was reported -- this must not read "
            "as a completed, idle tick",
        )

    text = str(message)
    header = _TICK.search(text)
    if header is None:
        return _verdict(
            "could-not-classify",
            "no TICK: header found -- this tool cannot tell a completed "
            "tick reported in plain prose from one that did nothing at "
            "all, so it refuses to guess: read the message yourself",
        )

    declared = header.group(1).lower()
    header_line = _rr.fold_to_one_ascii_line(_rr._line_containing(text, header.start()))

    if declared == "completed":
        return _verdict(
            "completed",
            "TICK: completed",
            declared="completed",
            quoted=header_line,
        )

    if declared == "blocked":
        match = _BLOCKER.search(text)
        if not match:
            return _verdict(
                "could-not-classify",
                "TICK: blocked with no BLOCKER: line -- an unnamed blocker "
                "is not a usable blocked state",
                declared="blocked",
                quoted=header_line,
            )
        detail = _rr.fold_to_one_ascii_line(match.group(1))
        return _verdict(
            "blocked",
            "blocked: {0}".format(detail),
            declared="blocked",
            detail=detail,
            quoted=header_line,
        )

    # declared == "could-not-run" -- the only remaining alternative in _TICK
    match = _REASON.search(text)
    if not match:
        return _verdict(
            "could-not-classify",
            "TICK: could-not-run with no REASON: line -- an unnamed "
            "reason is not a usable could-not-run state",
            declared="could-not-run",
            quoted=header_line,
        )
    detail = _rr.fold_to_one_ascii_line(match.group(1))
    return _verdict(
        "could-not-run",
        "could not run: {0}".format(detail),
        declared="could-not-run",
        detail=detail,
        quoted=header_line,
    )


EXIT_CODES = {
    "completed": 0,
    "blocked": 3,
    "could-not-run": 4,
    "returned-nothing": 5,
    "could-not-classify": 6,
    "could-not-read": 7,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Classify a sub-manager's tick handback. A sub-manager that "
            "died and one that found nothing to do must not render "
            "identically (#695)."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="path to a file holding the final message, or - for stdin",
    )
    parser.add_argument(
        "--framed",
        action="store_true",
        help=(
            "the message is indented by four spaces and closed by a line "
            "reading 'END OF MESSAGE' at column zero, so no line of it can "
            "end the stream that carried it (#404)"
        ),
    )
    args = parser.parse_args(argv)

    text, error = _rr._read_source(args.source)
    if error is None and args.framed:
        text, error = _rr.unframe(text)
    if error is not None:
        verdict = _verdict(
            "could-not-read",
            "{0} -- nothing was looked at, which is not the same as "
            "looking and finding nothing".format(error),
        )
    else:
        verdict = classify(text)
    source_note = _rr.fold_to_one_ascii_line(args.source)

    print("VERDICT: {0} -- {1}".format(verdict["state"], verdict["reason"]))
    print("  source: {0}".format(source_note or "-"))
    if verdict["declared"] is not None:
        print("  declared: {0}".format(verdict["declared"]))
    if verdict["detail"]:
        print("  detail: {0}".format(verdict["detail"]))
    if verdict["quoted"]:
        print("  quoted: {0}".format(verdict["quoted"]))
    return EXIT_CODES[verdict["state"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
