"""#967: the brief validated the way the report already is.

The risk this file exists to hold down is not a missed element -- it is the
opposite. Six of the seven checks can only report presence, and a tool that
says `ok` on a brief nobody read moves the missing review out of sight. So the
assertions below cover both directions: a brief missing an element is caught,
and a brief that passes is not thereby claimed to be good.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import brief_schema  # noqa: E402

GOOD = """
# Brief: fix the thing (#123)

Use `supertool` for every write, commit included. To change an existing file,
`supertool 'edit:@-'`; to create one, `supertool 'paste:@-'` -- a new file has no `old`,
and your changelog fragment is always one. Commit through `supertool 'git-commit:@-'`.
`cd <worktree_root>` on every write call leaving your branch directory, not once: a shell
cwd does not persist between calls.

The hidden judgment call: you will have to decide whether the guard belongs at the call
site or one layer down. Say which you chose and why.

Push back on any of this. The diagnosis below is a hypothesis with the evidence attached,
not a conclusion.

TDD in this order -- test, red, fix, green. Send the failing output before the
implementation exists.

Docs: the changelog fragment always; docs_targets if this reaches a user.

Live worktrees right now: ../wt-121 (issue #121), ../wt-122 (issue #122).

When you are done: commit, do not push, do not open a PR, do not comment on the issue.
"""


def _without(block):
    """The good brief minus one paragraph, so each negative case differs from the
    positive control by exactly the element under test."""
    kept = [p for p in GOOD.split("\n\n") if block not in p]
    assert len(kept) < len(GOOD.split("\n\n")), "fixture did not change: {!r}".format(block)
    return "\n\n".join(kept)


# --------------------------------------------------------- the positive control


def test_a_complete_brief_passes():
    """First, because every negative case below is only meaningful against a
    fixture that otherwise passes."""
    payload = brief_schema.check_text(GOOD)
    assert payload["state"] == brief_schema.STATE_OK, payload["missing"]
    assert payload["missing"] == []


# ------------------------------------------------------------ the seven, missing


@pytest.mark.parametrize(
    "block,element",
    [
        ("Use `supertool`", "supertool"),
        ("hidden judgment call", "judgment_call"),
        ("Push back", "pushback"),
        ("TDD in this order", "tdd"),
        ("Docs:", "docs"),
        ("Live worktrees", "worktrees"),
        ("do not push", "publishing"),
    ],
)
def test_each_missing_element_is_named_individually(block, element):
    payload = brief_schema.check_text(_without(block))
    assert payload["state"] == brief_schema.STATE_FINDINGS
    assert element in payload["missing"], payload["missing"]


def test_the_docs_and_worktree_checks_ignore_the_supertool_block():
    """Found by the tests, not anticipated. The supertool instruction names
    "your changelog fragment is always one" and `cd <worktree_root>`, so both
    presence checks passed on a brief whose own docs paragraph and worktree
    list had been deleted -- the block above them was answering for them."""
    text = _without("Docs:")
    text = "\n\n".join(p for p in text.split("\n\n") if "Live worktrees" not in p)
    payload = brief_schema.check_text(text)
    assert "docs" in payload["missing"] and "worktrees" in payload["missing"]
    # Must-not-fire half: with those paragraphs present the block does not
    # cause a false pass either -- they are found on their own merits.
    assert brief_schema.check_text(GOOD)["missing"] == []


def test_every_check_runs_even_after_one_fails():
    """A validator that stopped at the first finding would send an author back
    for one fix at a time."""
    payload = brief_schema.check_text("nothing useful here at all")
    assert len(payload["missing"]) >= 5
    assert len(payload["elements"]) == 8


# ------------------------------------------- the checks that catch a degraded element


def test_a_supertool_block_missing_paste_is_a_finding():
    """#250's own failure: the brief named supertool and omitted the one op that
    creates a file, and read as correct for six deliveries. An omitted op does
    not fail at the call -- it routes the agent to a heredoc that succeeds."""
    text = GOOD.replace("`supertool 'paste:@-'`", "the appropriate op")
    text = text.replace("and your changelog fragment is always one", "")
    payload = brief_schema.check_text(text)
    assert "supertool" in payload["missing"]
    why = [r["why"] for r in payload["elements"] if r["element"] == "supertool"][0]
    assert "paste" in why


def test_the_tdd_steps_out_of_order_are_a_finding():
    """The four words in the wrong order describe the opposite process, and a
    set-membership check would pass on both."""
    text = GOOD.replace(
        "test, red, fix, green", "fix it, then green, then write the test for the red"
    )
    payload = brief_schema.check_text(text)
    assert "tdd" in payload["missing"]


def test_a_conditional_publishing_clause_is_a_finding():
    """The recorded failure verbatim: 'do not push if something blocks you' is
    how one agent correctly pushed."""
    text = GOOD.replace(
        "commit, do not push, do not open a PR",
        "commit, and do not push if something blocks you, do not open a PR",
    )
    payload = brief_schema.check_text(text)
    assert "publishing" in payload["missing"]
    why = [r["why"] for r in payload["elements"] if r["element"] == "publishing"][0]
    assert "conditional" in why


def test_a_conditional_word_elsewhere_does_not_fail_the_publishing_clause():
    """The must-not-fire half. A brief is thousands of words and says 'if' many
    times; only the clause itself is the subject, so the check reads a window
    around it rather than the whole document."""
    text = GOOD.replace(
        "The hidden judgment call:",
        "If the tests are slow, say so. Unless it matters, skip it. The hidden judgment call:",
    )
    payload = brief_schema.check_text(text)
    assert "publishing" not in payload["missing"]


def test_a_missing_cwd_instruction_is_a_note_not_a_finding():
    """It cost two agents a re-sent heredoc, so it is worth saying -- but the
    element is present and calling it missing would make the finding list
    unreadable. A note on a found row is the honest shape."""
    text = GOOD.replace(
        "`cd <worktree_root>` on every write call leaving your branch directory, not once: a shell\ncwd does not persist between calls.",
        "",
    )
    payload = brief_schema.check_text(text)
    assert "supertool" not in payload["missing"]
    row = [r for r in payload["elements"] if r["element"] == "supertool"][0]
    assert row["state"] == "found" and "cwd" in row["note"]


# ------------------------------------------------- presence is not quality


def test_every_element_declares_how_it_was_checked():
    """The distinction the receipt rests on: `structural` can fail for the
    reason the element exists, `presence` can only fail when the section is
    gone. A row that did not say which would let `ok` read as a review."""
    payload = brief_schema.check_text(GOOD)
    for row in payload["elements"]:
        assert row["checked"] in (brief_schema.STRUCTURAL, brief_schema.PRESENCE), row


def test_the_receipt_says_a_pass_is_not_a_review():
    payload = brief_schema.check_text(GOOD)
    text = brief_schema.receipt(payload)
    assert "not a brief that was reviewed" in text
    assert "presence only" in text


def test_a_brief_of_keywords_alone_still_passes_and_that_is_the_known_limit():
    """Recorded deliberately rather than asserted as good behaviour: a document
    that name-drops all seven, in separate paragraphs, passes. That is the
    ceiling of what a text check can do and it is why the receipt refuses to
    call a pass a review.

    This test's earlier form put every keyword in one blob and it stopped
    passing when the docs and worktree checks learned to ignore the supertool
    paragraph -- an improvement, so the fixture was updated rather than the
    check loosened, per the note this docstring carried at the time. What still
    passes is keywords in separate paragraphs, which is the honest statement of
    the limit.
    """
    keywords = (
        "supertool edit paste git-commit cd cwd\n\n"
        "judgment call\n\n"
        "push back\n\n"
        "test red fix green fail\n\n"
        "changelog\n\n"
        "worktree\n\n"
        "do not push\n"
    )
    assert brief_schema.check_text(keywords)["state"] == brief_schema.STATE_OK


# ------------------------------------------------------------- could-not-read


def test_an_unreadable_brief_is_neither_ok_nor_a_finding(tmp_path):
    """'This brief is missing item 4' and 'nobody read this brief' are different
    facts, and the second must not be reported in the vocabulary of the first."""
    payload = brief_schema.check_path(tmp_path / "no-such-brief.md")
    assert payload["state"] == brief_schema.STATE_COULD_NOT_READ
    assert payload["missing"] == []
    assert "nobody looked" in brief_schema.receipt(payload)


def test_an_undecodable_brief_is_could_not_read(tmp_path):
    path = tmp_path / "brief.md"
    path.write_bytes(b"\xff\xfe\x00 not utf-8 at all")
    assert brief_schema.check_path(path)["state"] == brief_schema.STATE_COULD_NOT_READ


def test_exit_code_is_non_zero_for_findings_and_for_could_not_read(tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text(GOOD, encoding="utf-8")
    assert brief_schema.main([str(good)]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text("nothing", encoding="utf-8")
    assert brief_schema.main([str(bad)]) == 1
    assert brief_schema.main([str(tmp_path / "absent.md")]) == 1
    capsys.readouterr()
