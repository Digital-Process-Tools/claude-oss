#!/usr/bin/env python3
"""Read the ranking table straight out of the installed
`skills/manager/SKILL.md`, rather than a human retyping it.

#688: `commands/release.md` gate 3 requires the ranking table pasted into the
release-audit payload verbatim, so a finding can never come back `could not
rank`. A hand transcription of it dropped the embargo prose on the `forges`
and `ships-local-state` rows -- bare `yes` / `no` instead of the reasons the
table carries -- and the auditor, not the transcriber, caught it by reading
`skills/manager/SKILL.md` itself and comparing. This script is the fix: it
prints the table's own bytes, so a paste is a read rather than a retype.

Three states, because a table found and a table not found must never render
the same way, and neither may a file this could not even open:

  found            the header line, its markdown divider, and every
                   contiguous data row beneath it, exactly as written in the
                   source file.
  not-found        the header was not there, or what follows it does not look
                   like a table this can safely emit -- no divider row, a row
                   whose column count disagrees with the header, or zero data
                   rows. **Never partial.** A reshape is exactly the case a
                   silent partial print would be most dangerous in, because
                   the missing embargo prose from the #688 incident this
                   module exists to prevent is invisible in a diff of stdout
                   against nothing.
  could-not-read   `skills/manager/SKILL.md` itself could not be opened under
                   the given plugin root -- absent, unreadable, or no root
                   given at all.

This is deliberately narrow: it extracts one table by its own header text, and
refuses rather than guesses when the shape does not match. It does not attempt
the broader byte-comparison `scripts/checklist_skew.py` already performs
between the installed and repo copies of this and other files -- that answers
a different question (has either tree's ranking table moved at all), and nothing
here duplicates it.
"""

import argparse
import os
import re
import sys
from pathlib import Path

STATE_FOUND = "found"
STATE_NOT_FOUND = "not-found"
STATE_COULD_NOT_READ = "could-not-read"

#: The exact header cells the ranking table in `skills/manager/SKILL.md` is
#: written with. Matched loosely on leading whitespace only -- the table sits
#: under a bullet and is indented -- because the goal is "this is the header
#: row", not "this is indented exactly two spaces".
_HEADER_RE = re.compile(
    r"^[ \t]*\|\s*Class\s*\|\s*Blocks a release\?\s*\|\s*"
    r"Embargo when reported upstream\?\s*\|\s*$"
)

#: A markdown table divider row: pipes and cells made only of dashes, colons
#: and whitespace.
_DIVIDER_RE = re.compile(r"^[ \t]*\|(?:[\s:-]+\|)+[ \t]*$")


def _cell_count(line):
    """Number of `|`-delimited cells in a markdown table row, ignoring a
    leading/trailing empty cell produced by the row's own boundary pipes."""
    parts = line.strip().split("|")
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return len(parts)


def extract_ranking_table(text):
    """``(state, table, reason)``. ``table`` is the exact substring of
    ``text`` spanning the header row through the last contiguous data row,
    joined with a newline and ending in one; ``None`` on any failure.
    ``reason`` is ``None`` on success and a one-line explanation otherwise.

    Never returns a truncated table under ``STATE_FOUND`` -- a shape this
    function cannot fully make sense of is ``STATE_NOT_FOUND``, not a partial
    ``STATE_FOUND``.
    """
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if _HEADER_RE.match(line):
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

    if header_idx + 1 >= len(lines) or not _DIVIDER_RE.match(lines[header_idx + 1]):
        return (
            STATE_NOT_FOUND,
            None,
            "the ranking table header was found but is not followed by a "
            "markdown divider row; the table may have been reshaped",
        )

    row_lines = [header_line, lines[header_idx + 1]]
    j = header_idx + 2
    while j < len(lines) and lines[j].strip().startswith("|"):
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
            "the ranking table header and divider were found but no data "
            "rows followed",
        )

    return STATE_FOUND, "\n".join(row_lines) + "\n", None


def load_table(plugin_root):
    """``(state, table, reason)`` for the ranking table under
    ``<plugin_root>/skills/manager/SKILL.md``. ``STATE_COULD_NOT_READ`` when
    that file itself cannot be opened; delegates to `extract_ranking_table`
    otherwise.
    """
    path = Path(plugin_root, "skills", "manager", "SKILL.md")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return STATE_COULD_NOT_READ, None, "{0}: {1}".format(path, exc)
    return extract_ranking_table(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root",
        default=None,
        help="Defaults to $CLAUDE_PLUGIN_ROOT.",
    )
    args = parser.parse_args(argv)

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
