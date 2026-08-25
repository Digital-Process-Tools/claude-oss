"""The fleet-view label for one dispatched developer lane (#539).

Four developer lanes running concurrently used to render as ``Lane 534  auto-update
path``, ``Lane 535  statusline guard sets``, and so on -- the first issue's number plus
a phrase about that issue. A lane carrying three issues (#534, #537, #495) and a lane
carrying one rendered identically, because the label was composed by habit at the
moment of the spawn and nothing checked it.

``fleet_label`` is the one place that composition happens. It does not observe what a
lane actually carries -- the label is a string handed to the ``Agent`` tool's own
``description`` parameter at dispatch time, and nothing in this repository can inspect
that after the fact (the sibling constraint the issue names explicitly). What it can do
is refuse to *compose* a label from an incomplete answer: the caller must state every
issue the lane carries, not just the one that named the branch, or nothing is rendered
at all. A convention followed only by habit is exactly what #539 was filed about, so the
guard lives in the one function that ever produces the string, not in a sentence next to
it.

The count is the load-bearing half (see the issue's own "what would settle it"): a
reader scanning a fleet must see ``x3`` without reading the phrase. A genuine one-issue
lane never carries the multiplier -- if every lane wrote ``x1``, a bundled lane's ``x3``
would read as house style rather than as a fact.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import sys


class FleetLabelError(ValueError):
    """The label cannot be composed from what was given."""


def fleet_label(primary_issue, issues, phrase):
    """Render ``Lane <primary> [x<N>]  <phrase>`` for one dispatched lane.

    ``primary_issue`` is the issue that named the branch and the worktree.
    ``issues`` is every issue this lane carries, primary included -- never inferred
    from ``primary_issue`` alone, because the whole failure this module exists to
    close is a label that named only the first issue. ``phrase`` is the short
    description of what the lane is doing.
    """
    if not isinstance(issues, (list, tuple)) or not issues:
        raise FleetLabelError(
            "fleet_label needs every issue this lane carries, as a non-empty list -- "
            "an omitted or empty bundle is exactly the label #539 was filed about"
        )

    normalized = []
    for item in issues:
        if isinstance(item, bool):
            raise FleetLabelError(
                "fleet_label: {!r} is not a usable issue number".format(item)
            )
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            raise FleetLabelError(
                "fleet_label: {!r} is not a usable issue number".format(item)
            )

    if len(set(normalized)) != len(normalized):
        raise FleetLabelError(
            "fleet_label: {!r} names the same issue more than once".format(issues)
        )

    if isinstance(primary_issue, bool):
        raise FleetLabelError(
            "fleet_label: {!r} is not a usable primary issue".format(primary_issue)
        )
    try:
        primary = int(primary_issue)
    except (TypeError, ValueError):
        raise FleetLabelError(
            "fleet_label: {!r} is not a usable primary issue".format(primary_issue)
        )

    if primary not in normalized:
        raise FleetLabelError(
            "fleet_label: primary issue {} is not among the lane's own issues {!r} -- "
            "the primary is the branch's issue and must be counted in its own "
            "bundle".format(primary, issues)
        )

    if not phrase or not str(phrase).strip():
        raise FleetLabelError("fleet_label needs a phrase describing the lane's work")
    phrase = str(phrase).strip()

    count = len(normalized)
    if count == 1:
        return "Lane {}  {}".format(primary, phrase)
    return "Lane {} x{}  {}".format(primary, count, phrase)


def _print(text, stream=None):
    """Print ``text`` without dying on the console's own codepage.

    ``print`` encodes with the stream's encoding, not the source file's, and on
    Windows that is typically cp1252 -- a phrase carrying a character cp1252 cannot
    represent (an arrow, for instance; an em dash is representable and would not
    have caught this) raises ``UnicodeEncodeError`` and kills the process at this
    call, after every validation in ``fleet_label`` already passed. Round-tripped
    through the stream's own encoding first, with ``backslashreplace`` on the way
    out, so an unrepresentable character survives as an escape somebody can read
    instead of ending the process -- the same shape ``oss_state._say`` already uses
    for the same reason.
    """
    stream = sys.stdout if stream is None else stream
    encoding = getattr(stream, "encoding", None)
    if encoding:
        text = text.encode(encoding, "backslashreplace").decode(encoding, "replace")
    print(text, file=stream)


def _main(argv=None):
    """CLI: ``fleet_label.py PRIMARY ISSUE1,ISSUE2,... "phrase"``.

    Named in the brief instead of composed by hand -- the whole point is that the
    guard runs even when the caller is a maintainer typing a spawn call, not only a
    test.
    """
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        sys.stderr.write(
            "usage: fleet_label.py PRIMARY_ISSUE ISSUE1,ISSUE2,... PHRASE\n"
        )
        return 2

    primary_text, issues_text, phrase = argv
    issues = [part.strip() for part in issues_text.split(",") if part.strip()]

    try:
        label = fleet_label(primary_text, issues, phrase)
    except FleetLabelError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1

    _print(label)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
