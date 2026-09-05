"""#985: CLAUDE.md's new "Command files have a size budget too" table and
`scripts/command_budgets.BUDGETS` are two machine-readable statements of the
same numbers, and nothing compared them -- the same gap `test_claude_md_
budget_table_709.py` closed for the agents table and `test_claude_md_phase_
budget_table_725.py` closed for the phase table.

Deliberately narrow, same posture as #709's own test: this holds the
*command budget table* against `command_budgets.BUDGETS`, nothing more.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import command_budgets  # noqa: E402

CLAUDE_MD = ROOT / "CLAUDE.md"

#: `| `commands/x.md` | 12,345 B | 23,456 B |` -- the exact row shape the
#: "Command files have a size budget too" section renders one baseline/budget
#: pair as.
ROW = re.compile(
    r"^\| `(commands/[\w.-]+\.md)` \| ([\d,]+) B \| ([\d,]+) B \|\s*$",
    re.MULTILINE,
)


def _table_rows():
    """Every `(path, baseline, budget)` row under the command budget table's
    own header, read from `CLAUDE.md` rather than assumed -- the header
    anchors the search so a differently-shaped row elsewhere in the file
    cannot be picked up by accident."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    header = "## Command files have a size budget too"
    start = text.index(header)
    # A markdown table is a contiguous block of `|`-led lines followed by the
    # next `##` heading -- stop there rather than at the first blank line,
    # since this table has prose above it inside the same section.
    next_heading = text.index("\n## ", start + len(header))
    block = text[start:next_heading]
    return [
        (path, int(baseline.replace(",", "")), int(budget.replace(",", "")))
        for path, baseline, budget in ROW.findall(block)
    ]


def test_command_budget_table_names_exactly_the_files_command_budgets_declares():
    rows = _table_rows()
    assert rows, (
        "no rows matched under the command budget table header -- the parser or table moved"
    )
    table_paths = {path for path, _, _ in rows}
    assert table_paths == set(command_budgets.BUDGETS), (
        "CLAUDE.md's command budget table and command_budgets.BUDGETS name a different set "
        "of files -- table only: {}, BUDGETS only: {}".format(
            sorted(table_paths - set(command_budgets.BUDGETS)),
            sorted(set(command_budgets.BUDGETS) - table_paths),
        )
    )


def test_command_budget_table_numbers_match_command_budgets_exactly():
    rows = _table_rows()
    assert rows, (
        "no rows matched under the command budget table header -- the parser or table moved"
    )
    mismatches = []
    for path, table_baseline, table_budget in rows:
        real_baseline, real_budget = command_budgets.BUDGETS.get(path, (None, None))
        if (table_baseline, table_budget) != (real_baseline, real_budget):
            mismatches.append(
                (path, (table_baseline, table_budget), (real_baseline, real_budget))
            )
    assert not mismatches, (
        "CLAUDE.md's command budget table disagrees with command_budgets.BUDGETS (table vs. real): "
        + ", ".join(f"{p}: {t} != {r}" for p, t, r in mismatches)
    )
