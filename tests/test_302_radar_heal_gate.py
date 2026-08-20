"""#302: the heal-vs-probe tradeoff for radar's board-membership rule.

The issue proposed two cheaper alternatives to healing radar on every board-membership
change: gate the heal on radar's own three-state coverage report, or gate it on
gh-pr-merge's receipt naming a stacked follow-up. Measuring the first in this clone found
that the only op that can answer the coverage question (`N watched` against `N open`) is
the bare `radar` heal itself -- `radar:--state` explicitly declines to resolve live
coverage. So a probe that decided whether to heal would pay the heal's own cost to decide
whether to pay it, which is not a saving. commands/tick.md records that finding so the
question is not re-investigated cold on a future tick; this guards the record, not the
behaviour it describes, because the behaviour (heal unconditionally on board-membership
change) did not change.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICK_MD = REPO_ROOT / "commands" / "tick.md"

REQUIRED_PHRASES = [
    "#302",
    "radar:--state",
    "not resolved here, that would be",
    "claude-supertool",
]


def _text():
    return TICK_MD.read_text(encoding="utf-8")


def test_tick_md_exists():
    """A missing file would make every assertion below vacuous."""
    assert TICK_MD.is_file(), "commands/tick.md not found -- checks below would pass on nothing"


def test_tick_md_records_the_302_measurement():
    text = _text()
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in text]
    assert not missing, (
        "commands/tick.md no longer records the #302 finding that a cheap coverage probe "
        "cannot gate the radar heal -- missing: {}".format(missing)
    )


def test_a_document_missing_the_finding_fails_the_same_check():
    """Positive control: an unrelated document must fail the phrase check above.

    Without this, test_tick_md_records_the_302_measurement could pass because the
    phrases happen to appear somewhere irrelevant, or because REQUIRED_PHRASES was
    written loosely enough to match anything.
    """
    unrelated = "This document says nothing about board coverage or probes."
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in unrelated]
    assert missing, "the phrase list matched a document that says nothing -- it checks nothing"


def test_step_4_rule_is_still_unconditional_on_the_event():
    """The rule this issue examined -- heal on board-membership change -- is unchanged.

    #302 offered two ways to make it conditional and this suite documents why neither
    was taken; the rule text itself must still say the heal covers all three cases
    unconditionally, so a later edit that quietly narrows it is caught here rather than
    only in prose nobody re-reads.
    """
    text = _text()
    assert "board membership changed" in text
    assert re.search(r"pull request was opened", text)
    assert re.search(r"pull request merged or closed", text)
    assert re.search(r"default branch went red", text)
