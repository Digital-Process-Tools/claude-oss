"""#1275: non-blocking findings stop being filed as issues and become
trap.d/ fragments instead; only a blocking or unranked finding may still be
filed. The blocking/non-blocking row sets must be read off the ranking
table in skills/manager/phases/findings.md, never hand-copied beside it
(#577, #1014) -- so this test derives them through scripts/ranking_table.py
rather than asserting a second list of its own.

Red before the fix: `ranking_table.py` had no row parser at all, and
`findings.md`'s non-blocking rows still read "can ship behind a filed
issue" -- the exact string this change removes. Green after: the parser
exists, the table's own non-blocking value has changed, and the routing
rule is stated (not restated) in every file #1275 names as a site.
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


def test_table_has_row_parser():
    assert hasattr(ranking_table, "parse_rows")


def test_non_blocking_rows_read_trap_d_not_filed_issue():
    table = _findings_table()
    rows = ranking_table.parse_rows(table)
    non_blocking = ranking_table.non_blocking_classes(table)
    assert non_blocking, "expected at least one non-blocking row"
    for cls in non_blocking:
        assert rows[cls] == "can ship behind a trap.d fragment", (cls, rows[cls])
    assert "can ship behind a filed issue" not in table


def test_blocking_rows_still_block():
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


def test_routing_rule_present_in_findings_md_and_derives_from_the_table():
    text = (REPO_ROOT / "skills" / "manager" / "phases" / "findings.md").read_text(
        encoding="utf-8"
    )
    assert "trap.d" in text
    routing_section = text.split("## Routing a finding", 1)
    assert len(routing_section) == 2, "no 'Routing a finding' section found"
    after = routing_section[1]
    # bound the section at the next top-level heading, so prose belonging to
    # an unrelated, pre-existing section of this file is never checked here
    body = after.split("\n## ")[0]
    for cls in ("misdirects", "splices", "fails-to-preserve", "misreports"):
        assert cls not in body, "routing rule restates a row name: %s" % cls


def test_sites_reference_the_routing_rule_not_a_second_copy():
    sites = [
        REPO_ROOT / "agents" / "auditor.md",
        REPO_ROOT / "agents" / "release-auditor.md",
        REPO_ROOT / "agents" / "developer.md",
        REPO_ROOT / "agents" / "sub-manager.md",
    ]
    for path in sites:
        text = path.read_text(encoding="utf-8")
        assert "trap.d" in text, path
        assert "1275" in text, path


def test_claude_md_states_the_governing_rule():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "trap.d" in text
    assert "Blocks a release" in text or "blocks a release" in text.lower()


# --------------------------------------------------------------------------
# A row whose first cell has no backtick-quoted class name must not vanish
# silently from parse_rows -- that is the same absence-read-as-world defect
# this repository is named after, sitting in the one function the routing
# rule reads. Maintainer review on #1275 caught it: extract_ranking_table
# only guarantees a row starts with "|" and that its cell count matches the
# header; nothing validates the first cell's shape.

_HEADER_AND_DIVIDER = (
    "| Class | Blocks a release? | Embargo when reported upstream? |\n"
    "| --- | --- | --- |\n"
)

# Positive control: every row well-formed, in the identical shape the
# malformed fixture below uses -- so a change that made the assertion pass
# vacuously (nothing parses at all) would fail this one instead.
_WELL_FORMED_TABLE = _HEADER_AND_DIVIDER + (
    "| `destroys` -- data gone | yes, unconditionally | yes |\n"
    "| `misreports` | can ship behind a trap.d fragment | no |\n"
)

# The same two rows, except the first has lost its backticks -- exactly the
# shape maintainer review named.
_MALFORMED_TABLE = _HEADER_AND_DIVIDER + (
    "| destroys -- data gone | yes, unconditionally | yes |\n"
    "| `misreports` | can ship behind a trap.d fragment | no |\n"
)


def test_parse_rows_parses_every_row_of_a_well_formed_table():
    rows = ranking_table.parse_rows(_WELL_FORMED_TABLE)
    assert rows == {
        "destroys": "yes, unconditionally",
        "misreports": "can ship behind a trap.d fragment",
    }


def test_parse_rows_raises_loudly_on_a_row_with_no_backticked_class_name():
    try:
        ranking_table.parse_rows(_MALFORMED_TABLE)
    except ValueError as exc:
        assert "destroys" in str(exc)
    else:
        raise AssertionError(
            "parse_rows silently dropped a row with no backtick-quoted class "
            "name instead of raising"
        )


def test_the_real_findings_table_has_no_unbackticked_rows():
    # A positive control at the real table's own scale: parse_rows must not
    # raise against skills/manager/phases/findings.md itself.
    table = _findings_table()
    ranking_table.parse_rows(table)  # raises if any row is malformed
