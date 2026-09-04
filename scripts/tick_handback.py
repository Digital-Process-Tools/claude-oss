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

  completed        `TICK: completed` followed by a `TICK-ENDS:` line naming
                    which of `skills/manager/SKILL.md`'s *What ends a tick*
                    three states applied -- `work-started`, `blocked` or
                    `nothing-left` -- then a summary paragraph. A tick that
                    read the board and dispatched nothing is `completed`,
                    not a lesser state -- an idle tick is a real, clean
                    answer, and #695 is explicit that this must not collapse
                    onto the died case below. A `completed` with no
                    `TICK-ENDS:` line is `could-not-classify`, the same way
                    a `blocked` with no `BLOCKER:` line is (#773) -- an
                    *optional* field would give "the sub-manager had
                    nothing to say" and "the sub-manager never answered"
                    the same rendering, and the scheduler's continue-or-wait
                    decision (`commands/tick.md` step 7) needs to tell them
                    apart.
  blocked           `TICK: blocked` with a `BLOCKER:` line naming what. A
                    `blocked` with no `BLOCKER:` line is undecidable and is
                    `could-not-classify`, not `blocked` -- an unnamed blocker
                    is not a usable blocked state.
  could-not-run     `TICK: could-not-run` with a `REASON:` line naming why
                    the sub-manager itself could not execute a tick (a spawn
                    refusal, a worktree it could not cut, a permission
                    denial before any tick work began). Missing `REASON:` is
                    `could-not-classify`, for the same reason as `blocked`.
  paused            `TICK: paused` with `WAIT-DISPATCH:` and
                    `WAIT-OBSERVABLE:` lines naming, respectively, what was
                    set in motion this tick and what clears it -- the same
                    two facts `scripts/oss_state.py`'s
                    `--wait-dispatch`/`--wait-observable` already carry for a
                    tick closing blocked (#337), reused rather than
                    reinvented. This is #818's resolution 2: a sub-manager
                    has no `ScheduleWakeup` and cannot receive channel
                    events, so it hands back what it is waiting on instead
                    of polling itself or blocking on a watch, and the
                    scheduler -- which holds both -- waits and resumes the
                    same sub-manager with `SendMessage`. It is deliberately
                    not `blocked`: `blocked` reads as ending the tick's
                    work, and a paused tick is mid-merge, with a lane pushed
                    and a pull request open. Missing either line is
                    `could-not-classify`, the same way a `blocked` with no
                    `BLOCKER:` line is -- work in flight with nothing naming
                    what it is waiting on is not a usable paused state.
  returned-nothing  empty, or whitespace only. This is the "died" case: the
                    spawn executed and its conclusions, if any existed, are
                    lost. It must never be read as `completed`.
  could-not-classify  no `TICK:` header at all, so this module cannot tell a
                    completed tick reported in plain prose from one that
                    silently did nothing -- read the message yourself rather
                    than guess. Also the answer when a header is present but
                    its required companion field (`TICK-ENDS:` / `BLOCKER:` /
                    `REASON:` / `WAIT-DISPATCH:` / `WAIT-OBSERVABLE:`) is
                    either missing or matched more than once, or when more
                    than one `TICK:` header appears in the message at all
                    (#706) -- a handback naming two outcomes is not a shape
                    `agents/sub-manager.md`'s template can produce, so this
                    refuses to pick one rather than guessing between the
                    first and the last. A second companion-field match is
                    refused the same way regardless of whether it sits
                    inside a markdown quote (#847): the pattern that finds
                    the field cannot tell a quoted excerpt from a real
                    second declaration, so guessing which one is real would
                    be exactly the guess the header refusal already
                    declines to make. Two more shapes land here too (#896,
                    #941): a `TICK:` or a `TICK-ENDS:` line that IS present
                    but names a value none of the above -- the reason names
                    the value found rather than claiming no line exists --
                    and a header-less message whose prose reads as a
                    promise to resume, which is refused with a reason
                    pointing at `TICK: paused` instead of the generic
                    no-header reason.

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
  8   paused
  2   argparse usage error
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_return as _rr  # noqa: E402

# A header at the start of a line, tolerating light markdown wrapping the
# same way review_return.py's own header pattern does. This captures any
# token, not only the four recognised states -- #896: an enum-anchored
# pattern makes "the line is present with an unrecognised value" invisible,
# because it never matches at all and so counts the same as "the line is
# absent". Recognition is validated separately, after the match, so the two
# questions ("is a TICK: header here" and "is its value one this tool
# knows") get two different answers instead of collapsing onto one.
_TICK = re.compile(
    r"^[ \t>*_#]*TICK:[ \t]*(\S+)",
    re.MULTILINE | re.IGNORECASE,
)
_KNOWN_TICK_STATES = ("completed", "blocked", "could-not-run", "paused")

# #941: a sub-manager that stops mid-work with no TICK: header at all
# sometimes closes with prose promising to resume once CI or a poller
# reports back -- a promise it cannot keep, because its context is gone the
# instant it reports (#695, #767). TICK: paused (#818) is already the
# correct, cheap shape for exactly this case, so when no header is found at
# all the reason names that shape instead of only saying "no header found".
_RESUME_PROMISE = re.compile(
    r"\b(?:"
    r"pick(?:ing)?\s+(?:this|it|that)\s+(?:tick\s+)?back\s+up"
    r"|will\s+(?:resume|continue|pick\s+(?:this|it|that)?\s*back\s+up)"
    r"|once\s+(?:ci|the\s+ci|a\s+poller|the\s+poller)\b"
    r"|when\s+(?:ci|the\s+ci|a\s+poller|the\s+poller)"
    r"\s+(?:resolves|reports|finishes|completes|clears)"
    r")",
    re.IGNORECASE,
)


_ENUM_VALUE = re.compile(r"[A-Za-z0-9-]+")


def _normalize_enum_value(raw):
    """Fold a captured field value for enum comparison: case-insensitive,
    and read only the leading run of letters/digits/hyphens -- an enum
    value is always exactly that shape, so anything after it (a closing
    ``**``, a stray ``)``/``"``, a trailing comma or period) is exactly the
    surrounding sentence, not part of the value. This mirrors the word
    boundary (``\\b``) the field patterns used before #896: ``\\b`` is
    satisfied by *any* non-word character, not only a handful of
    punctuation marks, so stripping a fixed set (as an earlier version of
    this function did) silently un-recognised values like ``completed**``
    or ``completed)`` that the old pattern accepted without a second
    thought. Used for both ``TICK:`` and ``TICK-ENDS:`` -- the same
    "present but unrecognised" question, asked twice."""
    match = _ENUM_VALUE.match(raw.strip())
    return match.group(0).lower() if match else raw.strip().lower()
_BLOCKER = re.compile(r"^[ \t>*_#]*BLOCKER:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)
_REASON = re.compile(r"^[ \t>*_#]*REASON:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)
# #818: the two facts a `paused` tick must name, reusing the field names
# scripts/oss_state.py's --wait-dispatch/--wait-observable already give a
# tick closing blocked (#337) rather than inventing a second vocabulary.
_WAIT_DISPATCH = re.compile(r"^[ \t>*_#]*WAIT-DISPATCH:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)
_WAIT_OBSERVABLE = re.compile(r"^[ \t>*_#]*WAIT-OBSERVABLE:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)
# #773: which of "What ends a tick"'s three states (skills/manager/SKILL.md) this
# completed tick is in -- required, not optional, for the same reason BLOCKER:/
# REASON: are required on their own states: an *optional* field gives "absent" and
# "not-applicable" the same rendering, and the scheduler's step 7 continue-or-wait
# decision cannot then tell a tick that had nothing to say from one that never
# answered the question at all.
# #896: captures any token, not only the three recognised states, for the
# same reason _TICK does above -- an enum-anchored pattern cannot tell "the
# line is here with a value this tool does not recognise" from "the line
# is not here at all", because the unrecognised case never matches.
_TICK_ENDS = re.compile(
    r"^[ \t>*_#]*TICK-ENDS:[ \t]*(\S+)",
    re.MULTILINE | re.IGNORECASE,
)
_KNOWN_TICK_ENDS = ("work-started", "blocked", "nothing-left")


def _verdict(state, reason, **extra):
    out = {
        "state": state,
        "reason": reason,
        "declared": None,
        "detail": None,
        "quoted": None,
        "ends": None,
        "wait_dispatch": None,
        "wait_observable": None,
    }
    out.update(extra)
    return out


def _find_field(pattern, tail):
    """Search ``tail`` for every match of a companion-field pattern and
    return ``(match, count)``.

    ``match`` is the single match only when exactly one was found;
    otherwise it is ``None`` and the caller must refuse. A second match is
    exactly as undecidable as a missing one (#847) -- taking the first, as
    an earlier version of every caller below silently did via ``.search``,
    is a guess about which declaration is real. This mirrors ``_TICK``'s
    own refuse-on-second-match behaviour (#706) rather than inventing a
    second policy for the fields beside it, and -- like ``_TICK`` -- does
    not distinguish a quoted match from an unquoted one: both patterns
    accept the same markdown quote/bullet prefix, so a line legitimately
    quoted from an earlier attempt is indistinguishable, at the regex
    level, from a second real declaration. Refusing either shape is the
    same "read the message yourself rather than guess" policy the module
    already applies to the header.
    """
    matches = list(pattern.finditer(tail))
    if len(matches) == 1:
        return matches[0], 1
    return None, len(matches)


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
    # Exactly one TICK: header is the only shape agents/sub-manager.md's
    # template can produce (#706): the header goes on the first line, with
    # narrative -- which may quote an earlier attempt, an issue body, or a
    # CI log -- coming after it. A sub-manager reporting `blocked` or
    # `could-not-run` is explicitly asked, two sections below, to say "what
    # you tried, what stopped you", and that narrative can introduce a
    # second TICK:-shaped line even when it comes after the real header, as
    # #706 measured. Taking the first or the last match is a guess about
    # which one is real; refuse instead, the same way a missing header
    # refuses rather than assuming `completed`.
    headers = list(_TICK.finditer(text))
    if not headers:
        # #941: a message with no TICK: header at all sometimes reads as a
        # promise to resume once CI or a poller reports back -- a promise
        # the sub-manager cannot keep, since it dies with its context the
        # instant it reports. Name the shape it should have used instead
        # of only saying "no header found", which gives no hint that the
        # sub-manager thought it had already said something.
        promise = _RESUME_PROMISE.search(text)
        if promise is not None:
            return _verdict(
                "could-not-classify",
                "no TICK: header found, and this message reads as a "
                "promise to resume ('{0}') -- a sub-manager dies with its "
                "context the moment it reports back (#695, #767) and "
                "cannot keep that promise; a mid-work stop waiting on CI "
                "or a poller has its own shape, TICK: paused with "
                "WAIT-DISPATCH:/WAIT-OBSERVABLE: lines "
                "(agents/sub-manager.md), not a status note".format(
                    _rr.fold_to_one_ascii_line(promise.group(0))
                ),
            )
        return _verdict(
            "could-not-classify",
            "no TICK: header found -- this tool cannot tell a completed "
            "tick reported in plain prose from one that did nothing at "
            "all, so it refuses to guess: read the message yourself",
        )
    if len(headers) > 1:
        return _verdict(
            "could-not-classify",
            "{0} TICK: headers found, not one -- a handback naming more "
            "than one outcome is not a shape agents/sub-manager.md's "
            "template can produce, so this refuses to pick one rather "
            "than guessing between the first and the last: read the "
            "message yourself".format(len(headers)),
        )
    header = headers[0]

    raw_declared = header.group(1)
    declared = _normalize_enum_value(raw_declared)
    header_line = _rr.fold_to_one_ascii_line(_rr._line_containing(text, header.start()))
    # #896: the header is present -- say so, rather than "no header found",
    # when its value is not one of the four this tool knows. An
    # unrecognised value is exactly as undecidable as a missing header, so
    # the state is the same (`could-not-classify`); only the reason changes.
    if declared not in _KNOWN_TICK_STATES:
        return _verdict(
            "could-not-classify",
            "TICK: {0} is not a recognised state (expected one of {1}) -- "
            "an unrecognised value is exactly as undecidable as a missing "
            "header, so this refuses to guess which one you meant: read "
            "the message yourself".format(
                _rr.fold_to_one_ascii_line(raw_declared),
                ", ".join(_KNOWN_TICK_STATES),
            ),
            declared=declared,
            quoted=header_line,
        )
    # Only text *after* the chosen header can supply its companion field.
    # Searching the whole message (as an earlier version of this module
    # did) let a stale BLOCKER:/REASON: line sitting before the real header
    # be read as that header's own detail, even once the header itself was
    # picked correctly.
    tail = text[header.end():]

    if declared == "completed":
        match, count = _find_field(_TICK_ENDS, tail)
        if count == 0:
            return _verdict(
                "could-not-classify",
                "TICK: completed with no TICK-ENDS: line -- an omitted field "
                "is not a usable completed state: 'absent' and "
                "'not-applicable' would render identically, and the "
                "scheduler's continue-or-wait decision needs to tell them "
                "apart",
                declared="completed",
                quoted=header_line,
            )
        if count > 1:
            return _verdict(
                "could-not-classify",
                "{0} TICK-ENDS: lines found, not one -- a second declaration "
                "(quoted or not) is exactly as undecidable as a missing one, "
                "so this refuses to pick between them: read the message "
                "yourself".format(count),
                declared="completed",
                quoted=header_line,
            )
        raw_ends = match.group(1)
        ends = _normalize_enum_value(raw_ends)
        # #896: TICK-ENDS: is right there, with a value -- when that value
        # is not one of the three this tool knows, say so instead of
        # falling through to a state that renders identically to "the line
        # was never written at all".
        if ends not in _KNOWN_TICK_ENDS:
            return _verdict(
                "could-not-classify",
                "TICK-ENDS: {0} is not a recognised value (expected one of "
                "{1}) -- an unrecognised value is exactly as undecidable "
                "as a missing line, so this refuses to guess which one "
                "you meant: read the message yourself".format(
                    _rr.fold_to_one_ascii_line(raw_ends),
                    ", ".join(_KNOWN_TICK_ENDS),
                ),
                declared="completed",
                quoted=header_line,
            )
        return _verdict(
            "completed",
            "TICK: completed ({0})".format(ends),
            declared="completed",
            ends=ends,
            quoted=header_line,
        )

    if declared == "blocked":
        match, count = _find_field(_BLOCKER, tail)
        if count == 0:
            return _verdict(
                "could-not-classify",
                "TICK: blocked with no BLOCKER: line -- an unnamed blocker "
                "is not a usable blocked state",
                declared="blocked",
                quoted=header_line,
            )
        if count > 1:
            return _verdict(
                "could-not-classify",
                "{0} BLOCKER: lines found, not one -- a second declaration "
                "(quoted or not) is exactly as undecidable as a missing one, "
                "so this refuses to pick between them: read the message "
                "yourself".format(count),
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

    if declared == "could-not-run":
        match, count = _find_field(_REASON, tail)
        if count == 0:
            return _verdict(
                "could-not-classify",
                "TICK: could-not-run with no REASON: line -- an unnamed "
                "reason is not a usable could-not-run state",
                declared="could-not-run",
                quoted=header_line,
            )
        if count > 1:
            return _verdict(
                "could-not-classify",
                "{0} REASON: lines found, not one -- a second declaration "
                "(quoted or not) is exactly as undecidable as a missing one, "
                "so this refuses to pick between them: read the message "
                "yourself".format(count),
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

    # declared == "paused" -- the only remaining alternative in _TICK (#818)
    wait_dispatch_match, wait_dispatch_count = _find_field(_WAIT_DISPATCH, tail)
    wait_observable_match, wait_observable_count = _find_field(_WAIT_OBSERVABLE, tail)
    if wait_dispatch_count != 1 or wait_observable_count != 1:
        problems = [
            "no {0} line".format(name) if count == 0
            else "{0} {1} lines, not one".format(count, name)
            for name, count in (
                ("WAIT-DISPATCH:", wait_dispatch_count),
                ("WAIT-OBSERVABLE:", wait_observable_count),
            )
            if count != 1
        ]
        return _verdict(
            "could-not-classify",
            "TICK: paused with {0} -- work in flight with an undecidable "
            "wait state, whether the field is missing or duplicated "
            "(quoted or not), is not a usable paused state".format(
                " and ".join(problems)
            ),
            declared="paused",
            quoted=header_line,
        )
    wait_dispatch = _rr.fold_to_one_ascii_line(wait_dispatch_match.group(1))
    wait_observable = _rr.fold_to_one_ascii_line(wait_observable_match.group(1))
    return _verdict(
        "paused",
        "paused: {0} (clears on: {1})".format(wait_dispatch, wait_observable),
        declared="paused",
        wait_dispatch=wait_dispatch,
        wait_observable=wait_observable,
        quoted=header_line,
    )


EXIT_CODES = {
    "completed": 0,
    "blocked": 3,
    "could-not-run": 4,
    "returned-nothing": 5,
    "could-not-classify": 6,
    "could-not-read": 7,
    "paused": 8,
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
    if verdict["ends"]:
        print("  ends: {0}".format(verdict["ends"]))
    if verdict["wait_dispatch"]:
        print("  wait_dispatch: {0}".format(verdict["wait_dispatch"]))
    if verdict["wait_observable"]:
        print("  wait_observable: {0}".format(verdict["wait_observable"]))
    if verdict["quoted"]:
        print("  quoted: {0}".format(verdict["quoted"]))
    return EXIT_CODES[verdict["state"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
