"""#709: `CLAUDE.md`'s agent budget table and `scripts/agent_budgets.BUDGETS` are two
machine-readable statements of the same five numbers, and nothing compared them --
which is how the table went on listing four rows for a full release cycle after a
fifth agent definition (`agents/sub-manager.md`, #697) was budgeted.

Deliberately narrow, per the issue's own instruction: this holds the *budget table*
against `BUDGETS`, nothing more. The Layout block a few sections up is prose
describing files on disk, not a table of numbers with an existing machine-readable
counterpart, and parsing prose to hold it to a derived set is a harder, separate
question the issue explicitly declines to bundle in here.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_budgets  # noqa: E402

CLAUDE_MD = ROOT / "CLAUDE.md"

#: `| \`agents/x.md\` | 12,345 B | 23,456 B |` -- the exact row shape the "Agent
#: definitions have a size budget" section renders one baseline/budget pair as.
ROW = re.compile(
    r"^\| `(agents/[\w.-]+\.md)` \| ([\d,]+) B \| ([\d,]+) B \|\s*$", re.MULTILINE
)


def _table_rows():
    """Every `(path, baseline, budget)` row under the budget table's own header, read
    from `CLAUDE.md` rather than assumed -- the header anchors the search so a row
    shaped like this one elsewhere in the file (there is none today) could not be
    picked up by accident.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    header = "| file | measured (baseline) | budget |"
    start = text.index(header)
    # Stop at the first blank line after the header -- a markdown table is a
    # contiguous block of `|`-led lines, and the prose that follows it is not.
    end = text.index("\n\n", start)
    block = text[start:end]
    return [
        (path, int(baseline.replace(",", "")), int(budget.replace(",", "")))
        for path, baseline, budget in ROW.findall(block)
    ]


def test_budget_table_names_exactly_the_files_agent_budgets_declares():
    rows = _table_rows()
    assert rows, "no rows matched under the budget table header -- the parser or the table moved"
    table_paths = {path for path, _, _ in rows}
    assert table_paths == set(agent_budgets.BUDGETS), (
        "CLAUDE.md's budget table and agent_budgets.BUDGETS name a different set of "
        "files -- table only: {}, BUDGETS only: {}".format(
            sorted(table_paths - set(agent_budgets.BUDGETS)),
            sorted(set(agent_budgets.BUDGETS) - table_paths),
        )
    )


def test_budget_table_numbers_match_agent_budgets_exactly():
    rows = _table_rows()
    mismatches = []
    for path, table_baseline, table_budget in rows:
        real_baseline, real_budget = agent_budgets.BUDGETS.get(path, (None, None))
        if (table_baseline, table_budget) != (real_baseline, real_budget):
            mismatches.append((path, (table_baseline, table_budget), (real_baseline, real_budget)))
    assert not mismatches, (
        "CLAUDE.md's budget table disagrees with agent_budgets.BUDGETS (table vs. real): "
        + ", ".join(f"{p}: {t} != {r}" for p, t, r in mismatches)
    )
