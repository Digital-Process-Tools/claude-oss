"""#725: `CLAUDE.md`'s manager-skill budget table and `scripts/skill_phases.DOCUMENTS`
are two machine-readable statements of the same numbers, and nothing compared them --
the sibling gap left after #709 built the same comparison for the *agent* table and
`scripts/agent_budgets.BUDGETS`, and explicitly declined to widen its own scope to cover
this one.

Deliberately a sibling file rather than a generalised helper shared with #709's test:
the two tables differ in shape (this one is sourced from a three-tuple that also carries
a `governs` string the table itself never renders), and #577/#673's own precedent --
named in the issue -- is "a comparison costs one file", not "one mechanism for every
pair". A shared parametrised helper was weighed and declined for that reason; see the
pull request body for the fuller argument.

`test_claude_md_budget_table_709.py` models the shape this file repeats: read the table
under its own header, from `CLAUDE.md` as it stands on disk, and hold it against the
module's live dict -- nothing pre-computed, nothing assumed.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import skill_phases  # noqa: E402

CLAUDE_MD = ROOT / "CLAUDE.md"

#: `| `skills/manager/SKILL.md` | 58,377 B | 64,600 B |` -- the exact row shape the
#: "The manager skill is a spine plus one file per phase" section renders one
#: baseline/budget pair as. Anchored to `skills/manager/...` paths so the agent
#: table's identically-headed block a few sections up cannot be matched by accident.
ROW = re.compile(
    r"^\| `(skills/manager/[\w./-]+\.md)` \| ([\d,]+) B \| ([\d,]+) B \|\s*$",
    re.MULTILINE,
)

#: The section heading is what tells this table apart from the agent-definition
#: table a few sections up -- both are introduced by the identical
#: "| file | measured (baseline) | budget |" header, so the search has to start
#: after this heading rather than at the header's first occurrence in the file.
SECTION_HEADING = "## The manager skill is a spine plus one file per phase"


def _table_rows():
    """Every `(path, baseline, budget)` row under the phase-table's own header, read
    from `CLAUDE.md` rather than assumed -- scoped to the section so the agent table's
    identically-shaped header earlier in the file is never the one matched.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    section_start = text.index(SECTION_HEADING)
    header = "| file | measured (baseline) | budget |"
    start = text.index(header, section_start)
    # Stop at the first blank line after the header -- a markdown table is a
    # contiguous block of `|`-led lines, and the prose that follows it is not.
    end = text.index("\n\n", start)
    block = text[start:end]
    return [
        (path, int(baseline.replace(",", "")), int(budget.replace(",", "")))
        for path, baseline, budget in ROW.findall(block)
    ]


def _module_pairs():
    """`{path: (baseline, budget)}` from `skill_phases.DOCUMENTS`, dropping the
    third element (`governs`) -- the table renders only the numbers.
    """
    return {path: (baseline, budget) for path, (baseline, budget, _governs) in skill_phases.DOCUMENTS.items()}


def test_phase_budget_table_names_exactly_the_files_skill_phases_declares():
    rows = _table_rows()
    assert rows, "no rows matched under the phase budget table header -- the parser or the table moved"
    table_paths = {path for path, _, _ in rows}
    module_paths = set(skill_phases.DOCUMENTS)
    assert table_paths == module_paths, (
        "CLAUDE.md's manager-skill budget table and skill_phases.DOCUMENTS name a "
        "different set of files -- table only: {}, DOCUMENTS only: {}".format(
            sorted(table_paths - module_paths),
            sorted(module_paths - table_paths),
        )
    )


def test_phase_budget_table_numbers_match_skill_phases_exactly():
    rows = _table_rows()
    module_pairs = _module_pairs()
    mismatches = []
    for path, table_baseline, table_budget in rows:
        real_baseline, real_budget = module_pairs.get(path, (None, None))
        if (table_baseline, table_budget) != (real_baseline, real_budget):
            mismatches.append((path, (table_baseline, table_budget), (real_baseline, real_budget)))
    assert not mismatches, (
        "CLAUDE.md's manager-skill budget table disagrees with skill_phases.DOCUMENTS "
        "(table vs. real): " + ", ".join(f"{p}: {t} != {r}" for p, t, r in mismatches)
    )
