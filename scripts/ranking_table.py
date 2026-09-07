#!/usr/bin/env python3
"""Read the ranking table straight out of the installed manager loop's own
prose, rather than a human retyping it.

#688: `commands/release.md` gate 3 requires the ranking table pasted into the
release-audit payload verbatim, so a finding can never come back `could not
rank`. A hand transcription of it dropped the embargo prose on two of the
table's rows -- bare `yes` / `no` instead of the reasons the table carries --
and the auditor, not the transcriber, caught it by reading
`skills/manager/SKILL.md` itself and comparing. This script is the fix: it
prints the table's own bytes, so a paste is a read rather than a retype.

Three states, because a table found and a table not found must never render
the same way, and neither may a file this could not even open:

  found            the header line, its markdown divider, and every
                   contiguous data row beneath it, exactly as written in the
                   source file -- original line endings included.
  not-found        the header was not there, or what follows it does not look
                   like a table this can safely emit -- no divider row, a row
                   whose column count disagrees with the header, or zero data
                   rows. **Never partial.** A reshape is exactly the case a
                   silent partial print would be most dangerous in, because
                   the missing embargo prose from the #688 incident this
                   module exists to prevent is invisible in a diff of stdout
                   against nothing.
  could-not-read   **no** source file could be opened or decoded as UTF-8
                   under the given plugin root -- all absent, all unreadable,
                   or no root given at all. One unreadable source beside a
                   readable one is not this state: the reason line names which
                   were searched and which could not be read, so a table found
                   in the second source is never reported as if the first had
                   agreed with it.

`SOURCES` is searched in order and the first well-formed table wins. Two
entries, not one, and the second is not legacy tolerance (#958): the table
moved from the spine to `skills/manager/phases/findings.md`, and gate 3 in
`commands/release.md` runs against `${CLAUDE_PLUGIN_ROOT}` -- the *installed*
plugin, which during a release is ordinarily the previous tag. A single
hardcoded path would have made this script `not-found` against every install
on the other side of that move, in the one session that needs it.

This is deliberately narrow: it extracts one table by its own header text, and
refuses rather than guesses when the shape does not match. It does not attempt
the broader byte-comparison `scripts/checklist_skew.py` already performs
between the installed and repo copies of this and other files -- that answers
a different question (has either tree's ranking table moved at all), and
nothing here duplicates it.
"""

import argparse
import os
import re
import sys
from pathlib import Path

STATE_FOUND = "found"
STATE_NOT_FOUND = "not-found"
STATE_COULD_NOT_READ = "could-not-read"

#: Where the ranking table may live, most current first. See the docstring:
#: the second entry is what keeps gate 3 working against an install predating
#: the #958 split, not tolerance for an old copy lying around.
SOURCES = (
    "skills/manager/phases/findings.md",
    "skills/manager/SKILL.md",
)

#: The exact header cells the ranking table is written with. Matched loosely
#: on leading whitespace only, because the goal is "this is the header row",
#: not "this is indented exactly N spaces" -- it sat indented under a bullet
#: in the spine and sits at column 0 in `phases/findings.md`, and both must
#: match.
_HEADER_RE = re.compile(
    r"^[ \t]*\|\s*Class\s*\|\s*Blocks a release\?\s*\|\s*"
    r"Embargo when reported upstream\?\s*\|\s*$"
)

#: A markdown table divider row: pipes and cells made only of dashes, colons
#: and whitespace.
_DIVIDER_RE = re.compile(r"^[ \t]*\|(?:[\s:-]+\|)+[ \t]*$")

#: A backtick-quoted span, e.g. `` `containment (write)` ``. Stripped before
#: counting a row's cells (self-review finding, #688): a literal `|` inside
#: one of these -- a code span naming a shell pipe, say -- is not a column
#: separator, and counting it as one produced a false `not-found` refusal on
#: an otherwise well-formed table.
_BACKTICK_SPAN_RE = re.compile(r"`[^`\n]*`")

#: Line-ending styles this module treats as a terminator when deciding where
#: one row ends and the next begins. Stripped only for matching; the
#: original bytes, terminator included, are what gets emitted.
_EOL_RE = re.compile(r"(?:\r\n|\r|\n)\Z")


def _strip_eol(line):
    """``line`` with exactly one trailing line terminator removed, so regexes
    anchored with ``$`` behave the same whether the source used LF, CRLF or a
    bare CR -- without ever discarding the terminator from the emitted text.
    """
    return _EOL_RE.sub("", line)


def _cell_count(line):
    """Number of `|`-delimited cells in a markdown table row, ignoring a
    leading/trailing empty cell produced by the row's own boundary pipes and
    any `|` that appears inside a backtick-quoted span rather than as a
    column separator."""
    stripped = _BACKTICK_SPAN_RE.sub("", _strip_eol(line))
    parts = stripped.strip().split("|")
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return len(parts)


def extract_ranking_table(text):
    """``(state, table, reason)``. ``table`` is the exact substring of
    ``text`` spanning the header row through the last contiguous data row --
    original line endings preserved, byte for byte -- or ``None`` on any
    failure. ``reason`` is ``None`` on success and a one-line explanation
    otherwise.

    Never returns a truncated table under ``STATE_FOUND`` -- a shape this
    function cannot fully make sense of is ``STATE_NOT_FOUND``, not a partial
    ``STATE_FOUND``.
    """
    lines = text.splitlines(keepends=True)
    header_idx = None
    for i, line in enumerate(lines):
        if _HEADER_RE.match(_strip_eol(line)):
            header_idx = i
            break
    if header_idx is None:
        return (
            STATE_NOT_FOUND,
            None,
            "no line matching the ranking table header "
            "('| Class | Blocks a release? | Embargo when reported "
            "upstream? |') was found",
        )

    header_line = lines[header_idx]
    header_cells = _cell_count(header_line)

    if header_idx + 1 >= len(lines) or not _DIVIDER_RE.match(
        _strip_eol(lines[header_idx + 1])
    ):
        return (
            STATE_NOT_FOUND,
            None,
            "the ranking table header was found but is not followed by a "
            "markdown divider row; the table may have been reshaped",
        )

    row_lines = [header_line, lines[header_idx + 1]]
    j = header_idx + 2
    while j < len(lines) and _strip_eol(lines[j]).strip().startswith("|"):
        row = lines[j]
        if _cell_count(row) != header_cells:
            return (
                STATE_NOT_FOUND,
                None,
                "row {0} has {1} column(s), the header has {2}; the table "
                "may have been reshaped".format(j + 1, _cell_count(row), header_cells),
            )
        row_lines.append(row)
        j += 1

    if len(row_lines) <= 2:
        return (
            STATE_NOT_FOUND,
            None,
            "the ranking table header and divider were found but no data rows followed",
        )

    table = "".join(row_lines)
    if not table.endswith(("\n", "\r")):
        table += "\n"
    return STATE_FOUND, table, None


#: Exact value the `Blocks a release?` column carries on a blocking row.
BLOCKS_UNCONDITIONALLY = "yes, unconditionally"


def parse_rows(table):
    """``{class_name: blocks_value}`` for every data row in ``table`` -- the
    string ``extract_ranking_table`` (or ``load_table``) returned under
    ``STATE_FOUND``. Call it on nothing else; the two guards below rely on
    ``extract_ranking_table``'s own shape checks and are dead code on any
    other input.

    #1275: this is the one place that reads which classes block a release
    and which do not, so a routing rule naming either set can derive it here
    rather than keep a second, hand-copied list that drifts (#577, #1014).

    Raises ``ValueError``, naming the offending row, if a data row's first
    cell is not a backtick-quoted class name. Maintainer review on #1275
    caught the alternative: a silently skipped row is absent from both
    ``blocking_classes`` and ``non_blocking_classes`` alike -- neither
    blocking nor non-blocking, simply gone -- which is exactly the
    absence-read-as-world defect this plugin is named after, sitting in the
    one function a routing rule reads. The two other ``continue`` guards
    below stay defensive rather than becoming a second raise: both are
    provably unreachable on a table ``extract_ranking_table`` returned under
    ``STATE_FOUND``, and are annotated as such at each one, so this is the
    only shape a caller can actually be surprised by.
    """
    rows = {}
    lines = table.splitlines()
    for line in lines[2:]:
        stripped = _strip_eol(line).strip()
        if not stripped.startswith("|"):
            # Unreachable for a STATE_FOUND table: extract_ranking_table's
            # own row-collecting loop only ever appends a line that already
            # passed `_strip_eol(line).strip().startswith("|")`, so nothing
            # failing that same test can be among ``table``'s data rows.
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            # Unreachable for a STATE_FOUND table: extract_ranking_table
            # already refused (as STATE_NOT_FOUND) any row whose cell count
            # disagrees with the header before returning this table at all.
            continue
        class_match = re.match(r"^`([^`]+)`", cells[0])
        if not class_match:
            raise ValueError(
                "ranking table row has no backtick-quoted class name in its "
                "first cell, so it cannot be routed as blocking or "
                "non-blocking: {0!r}".format(stripped)
            )
        rows[class_match.group(1)] = cells[1]
    return rows


def blocking_classes(table):
    """Classes whose row answers ``BLOCKS_UNCONDITIONALLY`` in the
    ``Blocks a release?`` column, sorted."""
    return sorted(
        cls
        for cls, value in parse_rows(table).items()
        if value == BLOCKS_UNCONDITIONALLY
    )


def non_blocking_classes(table):
    """Every other ranked class, sorted -- the rows a routing rule sends to
    ``trap.d/`` instead of the tracker (#1275)."""
    blocking = set(blocking_classes(table))
    return sorted(cls for cls in parse_rows(table) if cls not in blocking)


def load_table(plugin_root):
    """``(state, table, reason)`` for the ranking table under ``plugin_root``.

    `SOURCES` is searched in order; the first file carrying a well-formed
    table answers. ``STATE_COULD_NOT_READ`` only when *none* of them could be
    opened or decoded -- a single unreadable source beside a readable one is
    reported in the reason rather than by the state, because "the table is not
    in the loop's prose" and "one of the two files was denied" are different
    facts and the second must never be printed as the first.

    Opened with ``newline=""`` deliberately: the default universal-newline
    translation would silently rewrite a CRLF source to LF before this
    module ever saw it, which is exactly the kind of quiet rewrite a script
    whose whole job is "verbatim" must not perform on its own input.
    """
    unreadable = []
    searched = []
    misses = []
    for rel in SOURCES:
        path = Path(plugin_root, *rel.split("/"))
        try:
            with open(str(path), "r", encoding="utf-8", newline="") as handle:
                text = handle.read()
        # UnicodeDecodeError is a ValueError, not an OSError -- a file that is
        # not valid UTF-8 would otherwise raise out of this function and crash
        # a tool whose whole contract is "never crashes, always could-not-read".
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append("{0}: {1}".format(rel, exc))
            continue
        searched.append(rel)
        state, table, reason = extract_ranking_table(text)
        if state == STATE_FOUND:
            return STATE_FOUND, table, None
        misses.append("{0}: {1}".format(rel, reason))

    if not searched:
        return (
            STATE_COULD_NOT_READ,
            None,
            "no source could be read under {0} -- {1}".format(
                plugin_root, "; ".join(unreadable)
            ),
        )
    detail = "; ".join(misses + unreadable)
    return (
        STATE_NOT_FOUND,
        None,
        "searched {0} of {1} source(s) ({2}) -- {3}".format(
            len(searched), len(SOURCES), ", ".join(searched), detail
        ),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root",
        default=None,
        help="Defaults to $CLAUDE_PLUGIN_ROOT.",
    )
    args = parser.parse_args(argv)

    # The table this prints carries an em dash in nearly every row. A Windows
    # console whose active codepage is not UTF-8 or cp1252 (cp437, cp850) can
    # not encode it, and would otherwise crash here -- after the file was
    # already found and the table already extracted. Same guard, same reason,
    # as scripts/release_delta.py and its siblings.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    plugin_root = args.plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        sys.stderr.write(
            "could-not-read: no plugin root given (pass --plugin-root or set "
            "CLAUDE_PLUGIN_ROOT)\n"
        )
        return 1

    state, table, reason = load_table(plugin_root)
    if state == STATE_FOUND:
        sys.stdout.write(table)
        return 0

    sys.stderr.write("{0}: {1}\n".format(state, reason))
    return 1


if __name__ == "__main__":
    sys.exit(main())
