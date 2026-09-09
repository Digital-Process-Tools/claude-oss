"""#1374: a v0.59.0 release audit of claude-supertool found a defect the
ranking table in skills/manager/phases/findings.md could not classify -- a
credential cache written with `write_text(...)` then chmodded to `0o600` on
the next line, briefly world-readable at the process umask. None of the
eleven existing rows fit: it does not egress (`discloses`), the path is fixed
and named (rules out `containment`), and it is not the swallowed-`chmod` half
filed separately.

The issue's own author flagged the hidden judgment call: "blocks a release?
I would argue no, unconditionally-no is wrong too" -- a first-of-its-kind
instance on a multi-user host is a different answer than a sub-second,
single-operator-machine clone of a pre-existing pattern. So the new row's
`Blocks a release?` column states a *condition*, not a bare yes/no, and the
ranking table's own row parser (`scripts/ranking_table.py`) needs a third
answer alongside `blocking_classes`/`non_blocking_classes` to keep reading it
rather than silently sorting a conditional row into one bucket or the other.

Red before the fix: `ranking_table` has no `conditional_classes`, and the
findings table carries no `overexposes` row at all -- `parse_rows` finds
nothing to classify and `hasattr(ranking_table, "conditional_classes")` is
False. Green after: the row exists, states its condition, and is excluded
from both `blocking_classes` and `non_blocking_classes` (a router must read
the condition, not derive an automatic answer).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ranking_table  # noqa: E402


def _findings_table():
    text = (REPO_ROOT / "skills" / "manager" / "phases" / "findings.md").read_text(
        encoding="utf-8"
    )
    state, table, reason = ranking_table.extract_ranking_table(text)
    assert state == ranking_table.STATE_FOUND, reason
    return table


def test_ranking_table_has_a_conditional_classifier():
    assert hasattr(ranking_table, "conditional_classes"), (
        "ranking_table.py needs a third answer alongside blocking_classes/"
        "non_blocking_classes for a row that states a condition rather than "
        "an unconditional yes/no (#1374)"
    )


def test_overexposes_row_exists_and_states_a_condition():
    table = _findings_table()
    rows = ranking_table.parse_rows(table)
    assert "overexposes" in rows, (
        "no row for a secret created wide, narrowed immediately after (#1374)"
    )
    assert rows["overexposes"].startswith("conditionally"), rows["overexposes"]


def test_overexposes_is_neither_blocking_nor_plain_non_blocking():
    table = _findings_table()
    assert "overexposes" not in ranking_table.blocking_classes(table)
    assert "overexposes" not in ranking_table.non_blocking_classes(table)
    assert ranking_table.conditional_classes(table) == ["overexposes"]


def test_other_rows_unaffected_by_the_new_classifier():
    """Positive control: every pre-existing row keeps its old bucket -- the
    new third answer must not sweep anything else into it."""
    table = _findings_table()
    blocking = set(ranking_table.blocking_classes(table))
    assert blocking == {
        "destroys",
        "discloses",
        "executes",
        "containment (read)",
        "containment (write)",
        "forges",
        "ships-local-state",
    }
    non_blocking = set(ranking_table.non_blocking_classes(table))
    assert non_blocking == {
        "misdirects",
        "splices",
        "fails-to-preserve",
        "misreports",
    }


def test_parse_rows_conditional_helper_reads_arbitrary_tables():
    """Unit-level control against a small fixture, so the classifier is
    proven against something other than the real, changeable prose file."""
    header_and_divider = (
        "| Class | Blocks a release? | Embargo when reported upstream? |\n"
        "| --- | --- | --- |\n"
    )
    table = header_and_divider + (
        "| `destroys` -- data gone | yes, unconditionally | yes |\n"
        "| `misreports` | can ship behind a trap.d fragment | no |\n"
        "| `overexposes` -- wide then narrowed | conditionally -- blocks when X, "
        "otherwise can ship behind a trap.d fragment | yes |\n"
    )
    assert ranking_table.conditional_classes(table) == ["overexposes"]
    assert ranking_table.blocking_classes(table) == ["destroys"]
    assert ranking_table.non_blocking_classes(table) == ["misreports"]
