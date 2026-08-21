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
  could-not-read       the CLI was given a path it could not open. Nothing was
                       looked at, which is not the same as looking and finding
                       nothing, and is not `could-not-classify` either.

`could-not-classify` is the load-bearing one and it is deliberately not a
catch-all: calling an undecidable message clean is the defect this repository
is named after, and calling it a loss is a false alarm the developer learns to
ignore, which ends in the same place. The counting is therefore conservative in
one direction only -- an under-count of enumerable blocks produces
`referred-not-stated`, which is loud and cheap (one re-spawn), while the
over-count that would produce a false `states-findings` needs the reviewer to
have written a header *and* enumerated at least that many blocks, which is the
behaviour the brief asks for anyway.

## The message is untrusted input

A final message is written by somebody else's agent. Nothing from inside it is
echoed unreduced: the residue this module quotes is folded to one printable
ASCII line, bounded at 120 characters, and emitted indented so it can never
occupy the receipt's own `VERDICT:` column. That is the same rule
`release_version.py` applies to fragment bodies, and it does double duty here:
the Windows legs encode stdout with the console codepage, typically cp1252,
where a box-drawing glyph or an em dash raises `UnicodeEncodeError` at the
print -- after the work the print was reporting already happened.

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
_NO_FINDINGS = re.compile(r"^[ \t>*_#]*NO[ \t]+FINDINGS\b", re.MULTILINE | re.IGNORECASE)

# A pointer at material that is not in the return value. Deliberately a closed
# list of verbs plus a closed list of directions: a looser rule ("findings"
# near a numeral) also fires on `NO FINDINGS` and on an honest "0 findings
# across 3 classes", taxing exactly the reviewers who did the right thing.
_BACKREF = re.compile(
    r"\b(?:reported|report|found|listed|list|described|detailed|noted|note|"
    r"mentioned|stated|outlined|flagged|identified|documented|given|shown)"
    r"[ \t]+(?:above|earlier|previously|already)\b"
    r"|\bas[ \t]+(?:noted|described|stated|mentioned)\b"
    r"|\b(?:see|per)[ \t]+(?:above|earlier|my[ \t]+\w+[ \t]+above)\b"
    r"|\b(?:above|earlier)[ \t]+(?:findings|analysis|review)\b",
    re.IGNORECASE,
)

# An enumerable block at column zero: a numbered item, a bullet, a heading, or
# a bolded lead-in. Indented lines are not counted, because sub-bullets belong
# to the block above them and counting them would over-count towards
# `states-findings` -- the one direction an error here must not take.
_BLOCK = re.compile(
    r"^(?:\d+[.)][ \t]|[-*+][ \t]|#{1,6}[ \t]|\*\*\S)", re.MULTILINE
)

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
            "a NO FINDINGS sentinel: the reviewer said it looked and found "
            "nothing",
            implied_count=implied,
            quoted=fold_to_one_ascii_line(_line_containing(text, clean.start())),
        )

    if header:
        if claimed == 0:
            return _verdict(
                "no-findings",
                "a FINDINGS: 0 header: the reviewer said it looked and found "
                "nothing",
                claimed=0,
                implied_count=implied,
            )
        body = text[header.end():]
        blocks = len(_BLOCK.findall(body))
        header_line = fold_to_one_ascii_line(_line_containing(text, header.start()))
        if blocks >= claimed:
            return _verdict(
                "states-findings",
                "a FINDINGS: {0} header with {1} enumerable block(s) under "
                "it".format(claimed, blocks),
                claimed=claimed,
                stated_blocks=blocks,
                implied_count=implied,
                quoted=header_line,
            )
        if blocks >= 1 or backref:
            lost = claimed - blocks
            return _verdict(
                "referred-not-stated",
                "the header claims {0} finding(s) and {1} enumerable block(s) "
                "are under it: {2} finding(s) are referred to and not stated"
                .format(claimed, blocks, lost),
                claimed=claimed,
                stated_blocks=blocks,
                implied_count=implied,
                quoted=fold_to_one_ascii_line(
                    _line_containing(text, backref.start())
                ) if backref else header_line,
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
        data = sys.stdin.buffer.read()
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
    args = parser.parse_args(argv)

    text, error = _read_source(args.source)
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
