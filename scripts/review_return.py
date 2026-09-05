#!/usr/bin/env python3
"""Classify a review spawn's final message -- #392.

`agents/developer.md` spawns two reviewers and then has to decide what came
back. Today that decision is a judgment: *read the final message you actually
received and sort it in four*. This module computes that sort.

## Why this is not a fourth sentence in the brief

#275 and #296 were the first two instances of one class -- a reviewer whose
final message refers to findings it does not carry. Both were closed by PR
#332, whose fix was brief language: *state every finding explicitly in your
final message*. #392 is the same shape recurring twice in one day, in two
unrelated lanes, after that mitigation shipped. A third round of stronger
adjectives is the intervention that has already been tried and measured, and
the measurement is in `agents/developer.md` under "The brief sentence is an
experiment, not a fix".

The two structural options that document weighed were both on the reviewer's
side of the boundary, and both were correctly refused there:

  * a structured sub-agent return contract -- `findings[]` at the tool
    boundary, so a claim of four beside an empty list is a validation failure
    rather than a prose contradiction. That is still the right ask and it is
    still upstream: nothing this repository ships sits between a sub-agent's
    final message and its caller's context.
  * routing findings through a file the reviewer writes -- refused because an
    ignored instruction to write a file fails identically to an ignored
    instruction to state findings, and it hands a write path to the one spawn
    the brief spends a paragraph telling not to write.

This module is on the **caller's** side. The caller already holds the string.
It asks nothing of the reviewer, adds no artifact, and grants no capability --
so it is unaffected by which of #392's two candidate mechanisms is true. If
`Explore` treats its intermediate turns as the deliverable, this fires on what
came back. If something truncates the final message, a better brief changes
nothing at all and this still fires. A mechanism-independent check is worth
more than a mechanism-specific one written against a mechanism that is, in the
issue's own words, "not established".

## What it does and does not buy

It does not recover a lost review, and it does not stop one being lost. What it
removes is the step where a *less careful* agent silently records `checked`:
#392's own sentence is that the arrangement is "one careful agent away from
silently losing every review it runs", and both lanes survived only because two
agents happened to read carefully. This turns that reading into a comparison of
two numbers and a match on a phrase.

It is still the developer who calls it, and that call is a request like any
other. What changes is that the failure becomes *nobody ran the check* -- an
absent verdict, visible -- rather than *somebody read a confident paragraph and
believed it*, which is invisible by construction.

## The states, and the one that is load-bearing

  states-findings      a `FINDINGS: n` header with n >= 1 and at least n
                       enumerable blocks under it.
  no-findings          a `NO FINDINGS` sentinel, or `FINDINGS: 0`.
  referred-not-stated  the message points at findings it does not carry: a
                       header claiming more than it enumerates, or a
                       back-reference phrase ("reported above", "found above",
                       "as noted") with nothing enumerated. This is #392.
  returned-nothing     empty, or whitespace only.
  could-not-classify   the message carries no sentinel, no header and no
                       back-reference -- so this tool cannot tell a review that
                       stated its findings in prose from one that gestured, and
                       says so instead of guessing.
  could-not-read       nothing was reliably looked at, which is not the same
                       as looking and finding nothing, and is not
                       `could-not-classify` either. Four ways in: a path that
                       could not be opened; a closed or unopenable stdin
                       (#405); and, under `--framed`, a frame that never
                       closed or one whose message is not indented (#404).

`could-not-classify` is the load-bearing one and it is deliberately not a
catch-all: calling an undecidable message clean is the defect this repository
is named after, and calling it a loss is a false alarm the developer learns to
ignore, which ends in the same place.

**What the block count can and cannot see, stated rather than assumed.** It
counts markdown markers at column zero over everything after the header. A
marker is a marker: a "Files checked" list, a pasted diff hunk and an
enumerated finding are the same bytes to it, so the count can be *too high* as
easily as too low. The first draft of this module claimed the over-count was
safe because reaching `states-findings` requires a header and enough markers,
"which is the behaviour the brief asks for anyway" -- and review of that draft
falsified it in one line: `FINDINGS: 3`, then "Findings reported above (3
total)", then a three-item list of file names, returned the decisive good
verdict over a message that is precisely #392. Two consequences:

  * **A back-reference anywhere forecloses `states-findings`**, however many
    markers trail it. That is not a heuristic bolted on -- it is the rule the
    brief already states to the reviewer ("No `reported above`, no `as noted`,
    no `detailed earlier`"), so a compliant message contains no back-reference
    and pays nothing, and a gesture is the stronger signal than a count that
    cannot tell a finding from a filename.
  * **A header with zero enumerable blocks and no gesture is
    `could-not-classify`, not a loss.** Findings written as plain paragraphs are
    a delivered review, and there is no way to count those. Calling them lost
    would be the false alarm above. The brief's definition of
    `referred-not-stated` carries this qualification for the same reason.

## The message is untrusted input, and the transport is part of that

A final message is written by somebody else's agent. Nothing from inside it is
echoed unreduced: the residue this module quotes is folded to one printable
ASCII line, bounded at 120 characters, and emitted indented so it can never
occupy the receipt's own `VERDICT:` column. That is the same rule
`release_version.py` applies to fragment bodies, and it does double duty here:
the Windows legs encode stdout with the console codepage, typically cp1252,
where a box-drawing glyph or an em dash raises `UnicodeEncodeError` at the
print -- after the work the print was reporting already happened.

None of that could defend the boundary that decides what this module receives
in the first place, and #404 is the instance: the transport `agents/
developer.md` documented put the message at column zero of a stream **bash**
parses, closed by a fixed one-word terminator. A message carrying that word --
and the likeliest carrier is a reviewer quoting the documented block, not an
attacker -- ended the stream early. The audit's single invocation produced
both halves at once: a line of message text ran as a command in the
developer's session, and this module classified the surviving prefix
`referred-not-stated`, manufacturing the failure it exists to measure.

The fix is `--framed`, below. It is a construction rather than a stronger
terminator, because any terminator this file writes down is one an ordinary
message can quote.

## The residue

#392 calls the count "the cheapest residue there is and the easiest to drop",
and one lost return in this repository's own history survived only as the name
of a file. So `implied_count` and `quoted` are carried out of the message even
when the verdict is a loss: a handle is not a finding, but it is the only thing
anybody will have.

Exit codes, because a shell reads those and never reads prose:

  0   the return survived -- states-findings or no-findings
  3   referred-not-stated
  4   returned-nothing
  5   could-not-classify
  6   could-not-read
  2   argparse usage error

0 covers two states on purpose: the question a shell asks is whether the review
survived, and the `VERDICT:` line says which of the two it was.
"""

import argparse
import re
import sys
from pathlib import Path

# A header at the start of a line, tolerating the markdown a model wraps it in.
_HEADER = re.compile(r"^[ \t>*_#]*FINDINGS:[ \t]*(\d+)", re.MULTILINE | re.IGNORECASE)

# The clean sentinel. Anchored at line start so "FINDINGS: 2" cannot match it.
_NO_FINDINGS = re.compile(
    r"^[ \t>*_#]*NO[ \t]+FINDINGS\b", re.MULTILINE | re.IGNORECASE
)

# A pointer at material that is not in the return value. Deliberately a closed
# list of verbs plus a closed list of directions: a looser rule ("findings"
# near a numeral) also fires on `NO FINDINGS` and on an honest "0 findings
# across 3 classes", taxing exactly the reviewers who did the right thing.
# Up to three words may sit between the verb and the direction: "described in
# the paragraph above" is the same act as "described above", and matching only
# the adjacent form left an ordinary English sentence undetected. The
# intervening words may not contain a full stop, so the match cannot cross a
# sentence boundary and pair a verb with a direction word from the next thought.
_BACKREF = re.compile(
    r"\b(?:reported|report|found|listed|list|described|detailed|noted|note|"
    r"mentioned|stated|outlined|flagged|identified|documented|given|shown)"
    r"[ \t]+(?:[\w,'-]+[ \t]+){0,3}(?:above|earlier|previously|already)\b"
    r"|\bas[ \t]+(?:noted|described|stated|mentioned)\b"
    r"|\b(?:see|per)[ \t]+(?:above|earlier|my[ \t]+\w+[ \t]+above)\b"
    r"|\b(?:above|earlier)[ \t]+(?:findings|analysis|review)\b",
    re.IGNORECASE,
)

# An enumerable block at column zero: a numbered item, a bullet, a heading, or
# a bolded lead-in. Indented lines are not counted, because sub-bullets belong
# to the block above them and counting them would over-count towards
# `states-findings` -- the one direction an error here must not take.
_BLOCK = re.compile(r"^(?:\d+[.)][ \t]|[-*+][ \t]|#{1,6}[ \t]|\*\*\S)", re.MULTILINE)

# A count left behind by a message that did not state what it counted.
_IMPLIED_COUNT = (
    re.compile(r"\((\d+)[ \t]+total\)", re.IGNORECASE),
    re.compile(r"\b(\d+)[ \t]+(?:total[ \t]+)?findings?\b", re.IGNORECASE),
    re.compile(r"\bfindings?\b[^.\n]{0,30}?\((\d+)\)", re.IGNORECASE),
)

_MAX_QUOTE = 120


def fold_to_one_ascii_line(text, limit=_MAX_QUOTE):
    """Reduce untrusted text to one printable-ASCII line of bounded length.

    Every character outside printable ASCII becomes a space rather than being
    deleted, so a glyph run does not silently join two words into one and
    change what the residue appears to say.
    """
    if not text:
        return None
    folded = "".join(c if 32 <= ord(c) <= 126 else " " for c in text)
    folded = " ".join(folded.split())
    if not folded:
        return None
    if len(folded) > limit:
        folded = folded[: max(0, limit - 3)].rstrip() + "..."
    return folded


def _line_containing(text, index):
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:] if end == -1 else text[start:end]


def _implied_count(text):
    for pattern in _IMPLIED_COUNT:
        match = pattern.search(text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:  # pragma: no cover -- a digit run cannot fail here
                return None
    return None


def _verdict(state, reason, **extra):
    out = {
        "state": state,
        "reason": reason,
        "claimed": None,
        "stated_blocks": 0,
        "implied_count": None,
        "quoted": None,
    }
    out.update(extra)
    return out


def classify(message):
    """Sort one reviewer final message into the six states above.

    ``message`` may be ``None`` -- a harness that handed back no final message
    at all is the first instance this class was ever observed in, and it must
    not be a crash, because a crash here is one more way for a review to go
    missing quietly.
    """
    if message is None or not str(message).strip():
        return _verdict(
            "returned-nothing",
            "the final message was empty or whitespace-only: the spawn "
            "executed and its conclusions are lost",
        )

    text = str(message)
    header = _HEADER.search(text)
    clean = _NO_FINDINGS.search(text)
    backref = _BACKREF.search(text)
    implied = _implied_count(text)

    claimed = int(header.group(1)) if header else None

    if header and clean and claimed:
        return _verdict(
            "could-not-classify",
            "the message contradicts itself: it carries both a NO FINDINGS "
            "sentinel and a FINDINGS: {0} header, and guessing which was "
            "meant is how a lost review becomes a clean one".format(claimed),
            claimed=claimed,
            implied_count=implied,
            quoted=fold_to_one_ascii_line(_line_containing(text, header.start())),
        )

    if clean and not header:
        return _verdict(
            "no-findings",
            "a NO FINDINGS sentinel: the reviewer said it looked and found nothing",
            implied_count=implied,
            quoted=fold_to_one_ascii_line(_line_containing(text, clean.start())),
        )

    if header:
        if claimed == 0:
            return _verdict(
                "no-findings",
                "a FINDINGS: 0 header: the reviewer said it looked and found nothing",
                claimed=0,
                implied_count=implied,
            )
        body = text[header.end() :]
        blocks = len(_BLOCK.findall(body))
        header_line = fold_to_one_ascii_line(_line_containing(text, header.start()))
        if blocks >= claimed and not backref:
            return _verdict(
                "states-findings",
                "a FINDINGS: {0} header with {1} enumerable block(s) under "
                "it and no back-reference anywhere".format(claimed, blocks),
                claimed=claimed,
                stated_blocks=blocks,
                implied_count=implied,
                quoted=header_line,
            )
        if blocks >= 1 or backref:
            lost = claimed - blocks
            if lost > 0:
                why = (
                    "the header claims {0} finding(s) and {1} enumerable "
                    "block(s) are under it: {2} finding(s) are referred to and "
                    "not stated".format(claimed, blocks, lost)
                )
            else:
                # Enough markers to satisfy the header, and a gesture as well.
                # The markers cannot be told from a "files checked" list or a
                # pasted diff hunk, so the gesture is the stronger signal and
                # the count is not evidence against it.
                why = (
                    "the header claims {0} finding(s) and {1} enumerable "
                    "block(s) trail it, but the message also points at material "
                    "it does not carry -- a marker count cannot tell a stated "
                    "finding from a list of file names, so the back-reference "
                    "decides".format(claimed, blocks)
                )
            return _verdict(
                "referred-not-stated",
                why,
                claimed=claimed,
                stated_blocks=blocks,
                implied_count=implied,
                quoted=fold_to_one_ascii_line(_line_containing(text, backref.start()))
                if backref
                else header_line,
            )
        return _verdict(
            "could-not-classify",
            "the header claims {0} finding(s) and nothing under it is "
            "enumerable, so the findings may be in prose this tool cannot "
            "count -- read the message yourself".format(claimed),
            claimed=claimed,
            implied_count=implied,
            quoted=header_line,
        )

    if backref:
        return _verdict(
            "referred-not-stated",
            "the message points at findings it does not carry, and no header "
            "says how many: a finding referred to and not stated is a finding "
            "that does not exist",
            implied_count=implied,
            quoted=fold_to_one_ascii_line(_line_containing(text, backref.start())),
        )

    return _verdict(
        "could-not-classify",
        "no FINDINGS header, no NO FINDINGS sentinel and no back-reference: "
        "this tool cannot tell a review that stated its findings in prose "
        "from one that gestured -- read the message yourself",
        implied_count=implied,
    )


# -- the framed transport (#404) -------------------------------------------
#
# The caller is an agent whose only route to this script is `Bash`, so the
# message is always embedded in something a parser resolves before this
# process starts. What `--framed` changes is that no line of the message can
# be the thing that parser is looking for.
#
# A quoted heredoc ends at the first line *equal* to its terminator, with no
# leading whitespace. Indenting every content line makes such a line
# unconstructible -- a construction, not an assertion that a construction is
# safe. Lengthening or randomising the terminator instead does not work: the
# route the issue calls likeliest is a reviewer quoting this very code block,
# terminator and all, so any terminator written down here is one an ordinary
# message can carry.
#
# The closing sentinel is the second, independent half, and it detects rather
# than prevents. If the indentation was not applied and a message line did end
# the stream early, this process receives a prefix and the sentinel never
# arrives -- so it answers `could-not-read` instead of classifying a truncated
# message, which is what produced #404's `referred-not-stated` over a review
# that referred to nothing. The sentinel cannot itself be forged from inside
# the message, because a message line carrying it is indented.

FRAME_INDENT = "    "
FRAME_END = "END OF MESSAGE"


def unframe(text):
    """Return ``(message, error)`` -- exactly one of the two is None.

    Undoes the transport in `agents/developer.md`: every line of the message
    indented by ``FRAME_INDENT``, closed by ``FRAME_END`` at column zero.

    The indent is stripped rather than tolerated, because column zero is where
    `_BLOCK` counts and an indented message would enumerate nothing.
    """
    # `split("\n")`, not `splitlines()`. `splitlines()` also breaks on `\r`,
    # `\v`, `\f`, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029 -- none of which
    # bash treats as a line boundary, and none of which whoever applied the
    # indent treated as one either. So a message carrying one of those mid-line
    # arrives as a single indented line from bash and would be split here into
    # a first part that is indented and a rest that is not, handing a message
    # the power to produce an unindented line at will. That is #404's own
    # mechanism one layer down, and it needs no adversary: a stray `\r` from
    # pasted mixed-ending text is enough. Splitting on exactly what bash split
    # on keeps the two parsers agreeing about what a line is.
    lines = text.split("\n")
    end = None
    for index, line in enumerate(lines):
        # The *first* sentinel, not the last: the frame ends where it first
        # says it does, so nothing after it can be appended to the message.
        if line.rstrip() == FRAME_END:
            end = index
            break
    if end is None:
        return None, (
            "the framing never closed -- no {0!r} line at column zero, so what "
            "arrived is a prefix of the message and the rest of it was parsed "
            "by the shell".format(FRAME_END)
        )
    # Nothing may follow the sentinel. A content line carrying the sentinel
    # unindented is indistinguishable from the real one, so the frame closes
    # early and the rest of the message is dropped -- silently, with a
    # confident verdict over a prefix, which is exactly the shape this
    # function exists to refuse. What that case *does* leave behind is
    # material after the close, and that is decidable. The one residue is a
    # message whose final line is an unindented sentinel, which nothing can
    # tell from the real one; it costs that line and cannot truncate a body.
    trailing = [line for line in lines[end + 1 :] if line.strip()]
    if trailing:
        return None, (
            "the frame closed at line {0} and {1} line(s) follow it, so where "
            "the message ends is not decidable -- an unindented {2!r} inside "
            "the message looks exactly like this. First trailing line: {3}".format(
                end + 1, len(trailing), FRAME_END, fold_to_one_ascii_line(trailing[0])
            )
        )
    out = []
    for number, line in enumerate(lines[:end], 1):
        if not line.strip():
            out.append("")
            continue
        if not line.startswith(FRAME_INDENT):
            return None, (
                "line {0} of the framed message is not indented by the {1} "
                "spaces the transport requires, so nothing here can be relied "
                "on to be content: {2}".format(
                    number, len(FRAME_INDENT), fold_to_one_ascii_line(line)
                )
            )
        out.append(line[len(FRAME_INDENT) :])
    return "\n".join(out), None


EXIT_CODES = {
    "states-findings": 0,
    "no-findings": 0,
    "referred-not-stated": 3,
    "returned-nothing": 4,
    "could-not-classify": 5,
    "could-not-read": 6,
}


def _read_source(source):
    """Return ``(text, error)`` -- exactly one of the two is None.

    The exception already in hand answers whether the path was absent or
    unreadable. Asking the filesystem a second question to find out is this
    repository's own trap: ``Path.exists()`` swallows a short list of errnos
    and re-raises everything else, so the line added to explain a bad read is
    the line that kills the process on an over-long or untraversable path.
    """
    if source == "-":
        # #405: `sys.stdin` is None when the harness hands the process a
        # closed or unopenable standard input, so `.buffer` raises before any
        # of this module's handling runs -- exit 1 and no VERDICT line, on the
        # one route `agents/developer.md` mandates. The correct answer already
        # existed three lines below; the branch that needed it could not reach
        # it. An *open* stdin carrying no bytes is a different thing and stays
        # `returned-nothing`: read and found nothing, not could not read.
        stream = getattr(sys.stdin, "buffer", None)
        if stream is None:
            return None, (
                "no readable stdin: the process was handed a closed or "
                "unopenable standard input"
            )
        try:
            data = stream.read()
        except (OSError, ValueError) as exc:
            return None, "unreadable stdin: {0}".format(
                getattr(exc, "strerror", None) or exc.__class__.__name__
            )
        return data.decode("utf-8", errors="replace"), None
    try:
        data = Path(source).read_bytes()
    except FileNotFoundError as exc:
        return None, "no such file: {0}".format(exc.strerror or "not found")
    except OSError as exc:
        return None, "unreadable: {0}".format(exc.strerror or exc.__class__.__name__)
    return data.decode("utf-8", errors="replace"), None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Classify a review spawn's final message. A reviewer that returned "
            "nothing and a reviewer that found nothing are the same bytes "
            "unless something looks (#392)."
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

    text, error = _read_source(args.source)
    if error is None and args.framed:
        text, error = unframe(text)
    if error is not None:
        verdict = _verdict(
            "could-not-read",
            "{0} -- nothing was looked at, which is not the same as looking "
            "and finding nothing".format(error),
        )
    else:
        verdict = classify(text)
    source_note = fold_to_one_ascii_line(args.source)

    # One VERDICT line, at column zero. Everything else is indented, so no
    # residue quoted out of an untrusted message can occupy this column.
    print("VERDICT: {0} -- {1}".format(verdict["state"], verdict["reason"]))
    print("  source: {0}".format(source_note or "-"))
    if verdict["claimed"] is not None:
        print(
            "  header claimed: {0}   enumerable blocks: {1}".format(
                verdict["claimed"], verdict["stated_blocks"]
            )
        )
    if verdict["implied_count"] is not None:
        print(
            "  implied count (residue, a handle and not a finding): {0}".format(
                verdict["implied_count"]
            )
        )
    if verdict["quoted"]:
        print("  quoted: {0}".format(verdict["quoted"]))
    return EXIT_CODES[verdict["state"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
