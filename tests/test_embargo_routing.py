"""Release-blocking and embargo are two sets, and both documents read one table (#139).

Two documents tell an agent where a defect found in a **dependency** gets reported:
`skills/manager/SKILL.md`, under *A defect in a declared dependency is filed on that
dependency's own tracker*, and `agents/developer.md`, under the upstream-filing duty.
Both routed on **release-blocking**, and that is the wrong set.

Blocking a tag asks *what may this project ship*. An embargo asks *should a reporter
hold disclosure*. `ships-local-state` blocks a tag because **the release is the mechanism
by which it takes effect** -- an argument about our artifact, which says nothing about
whether somebody else's users are at a risk they cannot mitigate while a fix is written.
Routing it to a private channel over-applies a promise about another project's disclosure
timing, and there is no public-knowledge window for it to protect.

## Why the table gains a column instead of the documents gaining a list

The instruction already in `SKILL.md` is the right one and it was pointing at the wrong
column: *"Read the rows off the table when you route -- a restated copy has already
drifted out of step with a security policy that restated it, and the drifted copy is the
one that gets quoted."* So the ranking table gains a second column and stays what it
declares itself to be -- **the only place the rows are written down**. Neither document
lists the embargo classes; both look them up.

`SECURITY.md` is deliberately *not* the source read here, and that is a decision rather
than an oversight. It is this repository's policy about reports arriving **inbound**, and
what these two passages route is a report going **outbound** to a dependency. A shared
skill that read our own inbound policy to decide an outbound routing would also be
carrying one repository's fact in shared prose, which this codebase forbids. The two must
agree in content -- checked below -- and they answer different questions.

## What is checked

The table is parsed, not grepped. A prose assertion that some sentence exists passes
against a document that says the opposite three lines later; the two columns and their
disagreement on exactly one row are a structure, so they are read as one.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANAGER_SKILL = REPO_ROOT / "skills" / "manager" / "SKILL.md"
DEVELOPER = REPO_ROOT / "agents" / "developer.md"

# The one row where the two sets differ, and why. Written here so the disagreement is a
# recorded decision -- a test that only checked "the sets differ somewhere" would pass on
# any drift at all.
EMBARGO_EXCEPTIONS = {
    "ships-local-state": (
        "it blocks a tag because the release is the mechanism by which it takes effect, "
        "which is an argument about our artifact and not about a reporter's disclosure "
        "timing -- there is no window of private knowledge for an embargo to protect"
    ),
}

_ROW = re.compile(r"^\s*\|\s*`([a-z-]+(?: \([a-z]+\))?)`([^|]*)\|([^|]*)\|([^|]*)\|\s*$")


def parse_table(text):
    """``{class: (blocks, embargo)}`` for every ranking row found. Never raises.

    A row is recognised by a backticked class name in the first cell, so the header and
    the `---` separator fall out on their own.
    """
    rows = {}
    for line in text.splitlines():
        match = _ROW.match(line)
        if match:
            rows[match.group(1)] = (
                match.group(3).strip().lower(),
                match.group(4).strip().lower(),
            )
    return rows


def _yes(cell):
    return cell.startswith("yes")


# ------------------------------------------------------------------ the parser itself

GOOD_TABLE = """
| Class | Blocks a release? | Embargo when reporting upstream? |
| --- | --- | --- |
| `destroys` -- gone | yes, unconditionally | yes |
| `ships-local-state` -- baked in | yes, unconditionally | no -- already public on release |
| `misreports` | can ship behind a filed issue | no |
"""


def test_the_parser_reads_rows_and_reads_nothing_out_of_prose():
    """Positive and negative control in one place: a real table yields its rows, and a
    document with no table yields none rather than an empty pass nobody notices."""
    rows = parse_table(GOOD_TABLE)
    assert set(rows) == {"destroys", "ships-local-state", "misreports"}
    assert _yes(rows["destroys"][1])
    assert not _yes(rows["ships-local-state"][1])
    assert parse_table("A paragraph about `destroys` and embargoes.") == {}


def test_the_parser_sees_a_two_column_table_as_two_columns():
    """The pre-change table had one verdict column. Read against the new expectations it
    must come back without an embargo answer, not with the blocking answer twice."""
    one_column = """
| Class | Blocks a release? |
| --- | --- |
| `destroys` -- gone | yes, unconditionally |
"""
    assert parse_table(one_column) == {}


# ------------------------------------------------------------------- the shipped table


def test_the_ranking_table_carries_an_embargo_column_for_every_row():
    rows = parse_table(MANAGER_SKILL.read_text(encoding="utf-8"))
    assert len(rows) >= 10, "only {} ranking rows parsed".format(len(rows))
    blank = sorted(name for name, (blocks, embargo) in rows.items() if not blocks or not embargo)
    assert blank == [], "rows with an empty verdict: {}".format(blank)


def test_embargo_is_the_blocking_set_minus_the_recorded_exceptions():
    """The whole point. Not "the sets differ" -- they differ on exactly these rows, for
    these reasons, and a row that quietly joins or leaves fails here."""
    rows = parse_table(MANAGER_SKILL.read_text(encoding="utf-8"))
    blocking = {name for name, (blocks, _) in rows.items() if _yes(blocks)}
    embargo = {name for name, (_, hold) in rows.items() if _yes(hold)}

    assert embargo <= blocking, "embargo without blocking: {}".format(
        sorted(embargo - blocking)
    )
    assert blocking - embargo == set(EMBARGO_EXCEPTIONS), (
        "blocking-but-not-embargo is {}, recorded as {}".format(
            sorted(blocking - embargo), sorted(EMBARGO_EXCEPTIONS)
        )
    )
    assert embargo, "no row is an embargo row, which would make the routing vacuous"


def test_the_exception_states_its_reason_in_the_table_itself():
    """A reader routing a finding sees the cell, not this file."""
    rows = parse_table(MANAGER_SKILL.read_text(encoding="utf-8"))
    for name in EMBARGO_EXCEPTIONS:
        cell = rows[name][1]
        assert len(cell) > len("no"), "{}: the `no` carries no reason".format(name)


# --------------------------------------------------------- both documents route on it


def _flatten(text):
    return " ".join(text.split()).lower()


def _routes_on_embargo(text):
    """``(reads the embargo column, still routes on blocking)``."""
    folded = _flatten(text)
    return ("embargo column" in folded, "blocking" in folded and "embargo column" not in folded)


def test_the_routing_checker_can_find_something_and_can_find_nothing():
    """Anchor discipline. Proved against the sentence both documents actually carried."""
    before = (
        "A finding in a row the ranking table above marks blocking does not go onto "
        "somebody else's public tracker as a reflex. It goes down the embargo path."
    )
    after = "Route on the table's embargo column, and say which row you read."
    assert _routes_on_embargo(before) == (False, True)
    assert _routes_on_embargo(after) == (True, False)


def test_both_documents_route_the_upstream_report_on_the_embargo_column():
    for path in (MANAGER_SKILL, DEVELOPER):
        reads, stale = _routes_on_embargo(path.read_text(encoding="utf-8"))
        assert reads, "{} does not name the embargo column".format(
            path.relative_to(REPO_ROOT)
        )
        assert not stale, "{} still routes on the blocking set".format(
            path.relative_to(REPO_ROOT)
        )


def test_neither_document_restates_the_embargo_set():
    """A list is what drifts, and the table is the one place allowed to hold it.

    So the table rows are dropped before looking: what this checks is the **prose**
    around the routing instruction, which may name at most one class. A version of this
    test that read the whole document would fail on the table it is protecting.
    """
    for path in (MANAGER_SKILL, DEVELOPER):
        prose = "\n".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("|")
        )
        folded = _flatten(prose)
        window = folded[folded.find("embargo") : folded.find("embargo") + 600]
        named = [
            name
            for name in ("`destroys`", "`discloses`", "`forges`", "`containment (read)`")
            if name in window
        ]
        assert len(named) < 2, "{} restates the embargo set: {}".format(
            path.relative_to(REPO_ROOT), named
        )

