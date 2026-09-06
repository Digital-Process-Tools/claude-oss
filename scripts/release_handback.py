#!/usr/bin/env python3
"""Classify a releaser's tick handback -- #1041.

`agents/releaser.md` reports one of four states now (`released` / `refused`
/ `could-not-run` / `paused`), over its own `RELEASE:` header rather than a
sub-manager's `TICK:` one. Before this module nothing classified it at all:
a releaser's report is read directly by whoever spawned it, so the same
promise-shaped-prose defect `scripts/tick_handback.py` already catches for a
sub-manager (#941) was caught by nothing here. Observed three times in one
release (Digital-Process-Tools/claude-jit-context, 0.8.0): a releaser
reaching a CI wait closed with prose promising to resume, a promise it
cannot keep because its context dies the instant it reports.

This module deliberately reuses `tick_handback.py`'s generic helpers rather
than re-deriving them -- the enum normaliser, the single-match field finder,
and the resume-promise pattern are not sub-manager-specific despite living
in that module, and a second hand-rolled copy of any of them is a second
place for #847/#896/#941's own bugs to recur. The transport underneath both
(`unframe`, `_read_source`, `fold_to_one_ascii_line`) is `review_return.py`'s,
imported rather than reimplemented, for the identical reason.

## The states

  released          `RELEASE: released` with a `TAG:` line -- the one
                     field `agents/releaser.md`'s own report-format section
                     already says is required ("a released with no TAG:
                     line is unclassifiable"). Missing `TAG:` is
                     `could-not-classify`.
  refused           `RELEASE: refused` with a `GATE:` line naming which of
                     the six gates refused it -- likewise already required
                     by `agents/releaser.md`. Missing `GATE:` is
                     `could-not-classify`.
  could-not-run     `RELEASE: could-not-run` with a `REASON:` line. Missing
                     `REASON:` is `could-not-classify`.
  paused            `RELEASE: paused` with `WAIT-DISPATCH:` and
                     `WAIT-OBSERVABLE:` lines, reusing
                     `tick_handback.py`'s own field names for the same two
                     facts (#818/#337): what this run set in motion, and
                     what clears it. An optional `GATE:` line names which
                     of the six gates it paused mid-way through, so a
                     resume does not have to re-derive that; its absence
                     does not affect classification. Missing either wait
                     field is `could-not-classify`, the same as a `paused`
                     tick handback missing one of its own two fields.
  returned-nothing  empty, or whitespace only. The spawn executed and its
                     conclusions, if any existed, are lost.
  could-not-classify  no `RELEASE:` header at all, more than one, an
                     unrecognised value, or a required companion field
                     missing or duplicated. A header-less message that
                     reads as a promise to resume names `RELEASE: paused`
                     in its reason, the same courtesy #941 already gives a
                     sub-manager's equivalent shape.

## Exit codes

Because a shell reads those and never reads prose:

  0   released
  3   refused
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
import tick_handback as _th  # noqa: E402

_RELEASE = re.compile(
    r"^[ \t>*_#]*RELEASE:[ \t]*(\S+)",
    re.MULTILINE | re.IGNORECASE,
)
_KNOWN_RELEASE_STATES = ("released", "refused", "could-not-run", "paused")

_TAG = re.compile(r"^[ \t>*_#]*TAG:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)
_GATE = re.compile(r"^[ \t>*_#]*GATE:[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)


def _verdict(state, reason, **extra):
    out = {
        "state": state,
        "reason": reason,
        "declared": None,
        "detail": None,
        "quoted": None,
        "tag": None,
        "gate": None,
        "wait_dispatch": None,
        "wait_observable": None,
    }
    out.update(extra)
    return out


def classify(message):
    """Sort one releaser's final message into the states above.

    ``message`` may be ``None`` -- a harness that hands back no final
    message at all must not crash this.
    """
    if message is None or not str(message).strip():
        return _verdict(
            "returned-nothing",
            "the releaser's handback was empty or whitespace-only: the "
            "spawn executed and nothing was reported -- this must not read "
            "as a completed, idle release",
        )

    text = str(message)
    headers = list(_RELEASE.finditer(text))
    if not headers:
        promise = _th._RESUME_PROMISE.search(text)
        if promise is not None:
            return _verdict(
                "could-not-classify",
                "no RELEASE: header found, and this message reads as a "
                "promise to resume ('{0}') -- a releaser dies with its "
                "context the moment it reports back and cannot keep that "
                "promise; a mid-release stop waiting on CI has its own "
                "shape, RELEASE: paused with "
                "WAIT-DISPATCH:/WAIT-OBSERVABLE: lines, not a status "
                "note".format(_rr.fold_to_one_ascii_line(promise.group(0))),
            )
        return _verdict(
            "could-not-classify",
            "no RELEASE: header found -- this tool cannot tell a completed "
            "release reported in plain prose from one that did nothing at "
            "all, so it refuses to guess: read the message yourself",
        )
    if len(headers) > 1:
        return _verdict(
            "could-not-classify",
            "{0} RELEASE: headers found, not one -- a handback naming more "
            "than one outcome is not a shape agents/releaser.md's template "
            "can produce, so this refuses to pick one rather than guessing "
            "between the first and the last".format(len(headers)),
        )
    header = headers[0]

    raw_declared = header.group(1)
    declared = _th._normalize_enum_value(raw_declared)
    header_line = _rr.fold_to_one_ascii_line(_rr._line_containing(text, header.start()))
    if declared not in _KNOWN_RELEASE_STATES:
        return _verdict(
            "could-not-classify",
            "RELEASE: {0} is not a recognised state (expected one of {1}) "
            "-- an unrecognised value is exactly as undecidable as a "
            "missing header: read the message yourself".format(
                _rr.fold_to_one_ascii_line(raw_declared),
                ", ".join(_KNOWN_RELEASE_STATES),
            ),
            declared=declared,
            quoted=header_line,
        )
    tail = text[header.end() :]

    if declared == "released":
        match, count = _th._find_field(_TAG, tail)
        if count != 1:
            problem = (
                "no TAG: line"
                if count == 0
                else "{0} TAG: lines, not one".format(count)
            )
            return _verdict(
                "could-not-classify",
                "RELEASE: released with {0} -- a released state with no "
                "usable tag is not classifiable".format(problem),
                declared="released",
                quoted=header_line,
            )
        tag = _rr.fold_to_one_ascii_line(match.group(1))
        return _verdict(
            "released",
            "released: {0}".format(tag),
            declared="released",
            tag=tag,
            quoted=header_line,
        )

    if declared == "refused":
        match, count = _th._find_field(_GATE, tail)
        if count != 1:
            problem = (
                "no GATE: line"
                if count == 0
                else "{0} GATE: lines, not one".format(count)
            )
            return _verdict(
                "could-not-classify",
                "RELEASE: refused with {0} -- a refused state with no "
                "named gate is not classifiable".format(problem),
                declared="refused",
                quoted=header_line,
            )
        gate = _rr.fold_to_one_ascii_line(match.group(1))
        return _verdict(
            "refused",
            "refused at gate: {0}".format(gate),
            declared="refused",
            gate=gate,
            quoted=header_line,
        )

    if declared == "could-not-run":
        match, count = _th._find_field(_th._REASON, tail)
        if count != 1:
            problem = (
                "no REASON: line"
                if count == 0
                else "{0} REASON: lines, not one".format(count)
            )
            return _verdict(
                "could-not-classify",
                "RELEASE: could-not-run with {0} -- an unnamed reason is "
                "not classifiable".format(problem),
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

    # declared == "paused" -- the only remaining alternative in _RELEASE
    wait_dispatch_match, wait_dispatch_count = _th._find_field(_th._WAIT_DISPATCH, tail)
    wait_observable_match, wait_observable_count = _th._find_field(
        _th._WAIT_OBSERVABLE, tail
    )
    if wait_dispatch_count != 1 or wait_observable_count != 1:
        problems = [
            "no {0} line".format(name)
            if count == 0
            else "{0} {1} lines, not one".format(count, name)
            for name, count in (
                ("WAIT-DISPATCH:", wait_dispatch_count),
                ("WAIT-OBSERVABLE:", wait_observable_count),
            )
            if count != 1
        ]
        return _verdict(
            "could-not-classify",
            "RELEASE: paused with {0} -- a release mid-flight with an "
            "undecidable wait state is not a usable paused state".format(
                " and ".join(problems)
            ),
            declared="paused",
            quoted=header_line,
        )
    wait_dispatch = _rr.fold_to_one_ascii_line(wait_dispatch_match.group(1))
    wait_observable = _rr.fold_to_one_ascii_line(wait_observable_match.group(1))
    # GATE: is optional for a paused report -- it does not affect classification, only
    # what a resume can skip -- so unlike every required field above, an ambiguous
    # (duplicated) GATE: line is folded into the same "absent" answer as a genuinely
    # missing one, deliberately, rather than promoted to could-not-classify. This is a
    # narrower rule than "a second match is exactly as undecidable as a missing one"
    # (_find_field's own docstring, applied everywhere else in this module): here the
    # two ambiguous cases share one answer because neither one can make the paused
    # state unclassifiable, not because the ambiguity was overlooked.
    gate_match, gate_count = _th._find_field(_GATE, tail)
    gate = _rr.fold_to_one_ascii_line(gate_match.group(1)) if gate_count == 1 else None
    return _verdict(
        "paused",
        "paused: {0} (clears on: {1})".format(wait_dispatch, wait_observable),
        declared="paused",
        wait_dispatch=wait_dispatch,
        wait_observable=wait_observable,
        gate=gate,
        quoted=header_line,
    )


EXIT_CODES = {
    "released": 0,
    "refused": 3,
    "could-not-run": 4,
    "returned-nothing": 5,
    "could-not-classify": 6,
    "could-not-read": 7,
    "paused": 8,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Classify a releaser's final message. A releaser that died and "
            "one that finished clean must not render identically (#1041)."
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
            "reading 'END OF MESSAGE' at column zero (#404)"
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
    if verdict["tag"]:
        print("  tag: {0}".format(verdict["tag"]))
    if verdict["gate"]:
        print("  gate: {0}".format(verdict["gate"]))
    if verdict["wait_dispatch"]:
        print("  wait_dispatch: {0}".format(verdict["wait_dispatch"]))
    if verdict["wait_observable"]:
        print("  wait_observable: {0}".format(verdict["wait_observable"]))
    if verdict["quoted"]:
        print("  quoted: {0}".format(verdict["quoted"]))
    return EXIT_CODES[verdict["state"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
