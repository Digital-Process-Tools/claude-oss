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
# #1037: this content moved out of commands/tick.md into its own phase file.
TICK_MD = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"

REQUIRED_PHRASES = [
    "#302",
    "radar:--state",
    "not resolved here, that would be",
    # #1037/content-invariants: a phase file is prose the loop executes, so
    # a hardcoded sibling-repo slug in it carries the same authority a
    # re-derived one would (CLAUDE.md's own rule) -- reworded to name the
    # dependency's tracker without spelling out its repo slug.
    "against supertool's own tracker",
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

    Phrase presence alone would not catch a narrowing edit that keeps every phrase and
    inserts a qualifier next to one of them -- "merged or closed, unless radar already
    reports full coverage" still contains "pull request merged or closed". So this also
    asserts there is no conditional-sounding word inside the bullet that states the
    merged-or-closed case, which is the one #302 asked to make conditional.
    """
    text = _text()
    assert "board membership changed" in text
    assert re.search(r"pull request was opened", text)
    assert re.search(r"default branch went red", text)

    merged_bullet = re.search(
        r"pull request merged or closed\..*?(?=\n\s*-\s+\*\*|\n\s*\n)",
        text,
        flags=re.DOTALL,
    )
    assert merged_bullet, "the merged-or-closed bullet is missing entirely"
    conditional_words = re.findall(
        r"\bunless\b|\bif\b|\bonly when\b|\bexcept when\b",
        merged_bullet.group(0),
        flags=re.IGNORECASE,
    )
    assert not conditional_words, (
        "the merged-or-closed bullet now reads as conditional ({!r}) -- #302 concluded "
        "there is no cheap gate for this case, so a rewrite that quietly narrows it here "
        "contradicts the reasoning recorded above and needs that reasoning updated too: "
        "{!r}".format(conditional_words, merged_bullet.group(0))
    )


def test_a_narrowed_rewrite_of_the_same_bullet_is_caught():
    """Positive control for the conditional-word check above.

    Without this, the check could pass by construction if the regex never actually
    matched real prose shaped like a narrowing edit.
    """
    narrowed = (
        "- **A pull request merged or closed.** Its poller is correctly reaped, and a "
        "stacked follow-up needs its own, unless radar already reports full coverage.\n"
        "\n"
        "- **The next bullet.** Unrelated text follows.\n"
    )
    merged_bullet = re.search(
        r"pull request merged or closed\..*?(?=\n\s*-\s+\*\*|\n\s*\n)",
        narrowed,
        flags=re.DOTALL,
    )
    assert merged_bullet
    conditional_words = re.findall(
        r"\bunless\b|\bif\b|\bonly when\b|\bexcept when\b",
        merged_bullet.group(0),
        flags=re.IGNORECASE,
    )
    assert conditional_words, "the check did not fire on prose shaped like a narrowing edit"
