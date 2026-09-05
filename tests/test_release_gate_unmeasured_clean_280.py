"""A `clean` the gate cannot tell from a measurement, and a completion it cannot
attribute to its own dispatch (#280).

One `oss:release-auditor` dispatch produced **two** completions for one range
during the 0.6.0 gate. They disagreed. One carried a class B finding ranked
`containment (read)`, which blocks; the other reported `VERDICT: clean` with
class B stated as `checked, 0 findings` and closed by saying nothing blocked the
tag. The finding was real -- #279 carries the receipts, and it reproduces in one
command.

Two separate defects, and they are separate on purpose:

**The grade.** `checked, 0 findings` is one word for two different things. The
clean report's class C entry had a control behind it that had fired; its class B
entry had a reading behind it and nothing else. Nothing in the report format
distinguished them, so a class established by measurement and a class established
by looking rendered identically -- and the one that was only looked at is the one
that was wrong. That is this repository's own defect class one level inside the
word `clean`.

**The attribution.** Two completions arrived for one dispatch, and the mismatch
was visible only because the maintainer happened to be reading identifiers. The
completion whose identity matched the dispatch was the wrong one; the
**unattributed** completion was the one that was right. So an unattributed
completion must neither clear the gate nor be discarded, and those are two
requirements rather than one.

## Why this is a producer -> consumer join

Same shape as `test_release_gate_rowless_findings.py`. A vocabulary stated in the
agent file and absent from the gate that acts on it is how a state renders as its
cheapest neighbour -- which is exactly what `checked, 0 findings` did. So each
term is asserted where it is **defined** (`agents/release-auditor.md`) and
required to have an **arm** where it is acted on (`commands/release.md`).

The ranking table is referenced by both documents and restated by neither; this
file adds no copy of it.

## Three states, including this file's own

Every checker is a function over text and is run twice: against the real file,
where it must come back clean, and against text written to violate exactly one
thing, where it must fire. A checker that cannot fire passes over prose nobody
constrained. And a file that would not read is a failure with its own name, never
an empty finding set -- `_doc` fails rather than returning "".

The novelty controls are the pre-change blocks of both documents, verbatim. Every
anchor here must report unmet against them, or these checks are satisfied by
vocabulary that was already on disk and say nothing about whether the grade or the
attribution was ever written down.
"""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_AUDITOR = REPO_ROOT / "agents" / "release-auditor.md"
RELEASE_COMMAND = REPO_ROOT / "commands" / "release.md"


def _doc(path):
    """A document that would not read is a failure with its own name.

    Returning "" would make every `in` check below fire at once and read like a
    document that says nothing, which is a different fact about the world.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail("could not read {}: {!r}".format(path, exc))


def _chunks(text):
    """Split prose into bullet items and paragraphs.

    Lines are too small -- a wrapped bullet looks like a state named with no
    disposition beside it. Paragraphs are too large -- a bullet list is one
    paragraph, so two states listed as two bullets look like one collapsed arm.
    """
    chunks = []
    current = []
    for line in text.splitlines():
        starts_item = re.match(r"^\s*[-*+] ", line) is not None
        if not line.strip() or starts_item:
            if current:
                chunks.append("\n".join(current))
                current = []
        if line.strip():
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _folded_chunks(text):
    return [chunk.lower() for chunk in _chunks(text)]


def _slug(term):
    """An id from a term. Parentheses are stripped wherever they sit, not only
    at the ends: `str.strip` left the `(` in `clean-(read)` interior and produced
    two ids nobody could read, which is a checker whose finding is about its own
    spelling dressed as a finding about the file.
    """
    return term.replace(" ", "-").replace("(", "").replace(")", "")


# --------------------------------------------------------------- the vocabulary
#
# A registry with a sentence each rather than a discovery run over the prose. A
# regex that extracted the terms would have its own third state -- "the defining
# paragraph moved, so I found nothing" -- and would report that as a clean join.

EVIDENCE_GRADES = {
    "clean (exercised)": (
        "a control was run over this range that would have failed had the class "
        "been present, and it did not fail. This is a measurement, and it is the "
        "only grade that may be read as one."
    ),
    "clean (read)": (
        "the surface was read and nothing was found; no control was run. This is "
        "a reading. It is an honest answer and a common one, and it must never "
        "render as the measured grade above."
    ),
}

ATTRIBUTION_STATES = {
    "dispatch token": (
        "the identifier the gate mints before spawning and the auditor echoes "
        "back verbatim, so a completion can be joined to the dispatch it answers "
        "instead of being believed because it arrived."
    ),
    "unattributed": (
        "a completion carrying no token, or one that does not match. It does not "
        "clear the gate and it is not discarded -- in the instance this comes "
        "from, the unattributed completion was the one that was right."
    ),
}

VERDICT_TAIL = "read but not exercised"
REPRODUCTION_RULE = "never outweighs a reproduction"
MULTIPLE_COMPLETIONS = "more than one completion"


def _producer_unmet(text):
    """What `agents/release-auditor.md` owes: the vocabulary, and the slot in its
    own template where the count is written down.
    """
    unmet = set()
    folded = text.lower()
    chunks = _folded_chunks(text)

    for term in list(EVIDENCE_GRADES) + list(ATTRIBUTION_STATES):
        if term not in folded:
            unmet.add("names-" + _slug(term))

    # The two grades must not share one arm. Collapsed, the reading inherits
    # whatever was decided for the measurement, which is the whole defect.
    for term, other in (
        ("clean (read)", "clean (exercised)"),
        ("clean (exercised)", "clean (read)"),
    ):
        alone = [c for c in chunks if term in c and other not in c]
        if not alone:
            unmet.add("keeps-{}-apart".format(_slug(term)))

    if not any("clean (read)" in c and "never renders as" in c for c in chunks):
        unmet.add("a-read-grade-never-renders-as-a-measured-one")

    # A control that cannot fail is not a control, and grading a class on one is
    # the same claim with a longer receipt.
    if not any("clean (exercised)" in c and "would have failed" in c for c in chunks):
        unmet.add("a-control-has-to-be-able-to-fail")

    # `any` over an empty list is False, so a template with no verdict line at
    # all lands here too -- deliberately one id, because the template's own
    # existence is already held by test_release_gate_rowless_findings.py and a
    # second id for it would be a second copy of that guard.
    verdict_lines = [
        line.lower() for line in text.splitlines() if "verdict: clean" in line.lower()
    ]
    if not any(VERDICT_TAIL in line for line in verdict_lines):
        unmet.add("the-verdict-line-carries-the-unexercised-count")

    if not any("dispatch token" in c and "none reached me" in c for c in chunks):
        unmet.add("has-a-no-token-reached-me-state")

    return unmet


def _consumer_unmet(text):
    """What `commands/release.md` owes: an arm for each term the agent can hand
    back. A term with no arm is a state the gate reads as its neighbour.
    """
    unmet = set()
    folded = text.lower()
    chunks = _folded_chunks(text)

    for term in ATTRIBUTION_STATES:
        if term not in folded:
            unmet.add("names-" + _slug(term))

    if VERDICT_TAIL not in folded:
        unmet.add("names-the-unexercised-count")

    if not any("unattributed" in c and "does not clear" in c for c in chunks):
        unmet.add("an-unattributed-completion-does-not-clear-the-gate")

    if not any("unattributed" in c and "not discarded" in c for c in chunks):
        unmet.add("an-unattributed-completion-is-not-discarded")

    if MULTIPLE_COMPLETIONS not in folded:
        unmet.add("has-an-arm-for-more-than-one-completion")

    # The count annotates rather than stopping. Demanding a control for every
    # class on every delta would teach the auditor to name a command it did not
    # run, which is the same defect with a longer receipt.
    if not any(VERDICT_TAIL in c and "does not stop" in c for c in chunks):
        unmet.add("an-unexercised-class-does-not-stop-the-tag-by-itself")

    # And the arm with force, which is the one the incident turned on: a reading
    # graded clean cannot be weighed against a finding that reproduces.
    if REPRODUCTION_RULE not in folded:
        unmet.add("a-read-grade-never-outweighs-a-reproduction")

    return unmet


# Derived by running each checker over text that says none of it, rather than
# written out. An id a checker can never emit would otherwise be excluded from
# both sides of the must-fire comparisons below and pass unnoticed.
PRODUCER_IDS = frozenset(_producer_unmet("A release auditor that says none of it.\n"))
CONSUMER_IDS = frozenset(_consumer_unmet("A release command that says none of it.\n"))


# ------------------------------------------------------------ the must-not-fire


def test_the_two_documents_exist():
    """Without them every check below fails for the wrong reason."""
    assert RELEASE_AUDITOR.is_file(), "agents/release-auditor.md is missing"
    assert RELEASE_COMMAND.is_file(), "commands/release.md is missing"


def test_the_release_auditor_grades_a_clean_class_by_how_it_was_established():
    unmet = _producer_unmet(_doc(RELEASE_AUDITOR))
    assert not unmet, (
        "agents/release-auditor.md does not state what a clean class has to "
        "carry, so a class established by reading renders exactly like one "
        "established by a control that fired:\n  " + "\n  ".join(sorted(unmet))
    )


def test_the_release_command_has_an_arm_for_each_answer_the_agent_can_give():
    unmet = _consumer_unmet(_doc(RELEASE_COMMAND))
    assert not unmet, (
        "commands/release.md has no arm for these, so the gate reads each as "
        "its cheapest neighbour:\n  " + "\n  ".join(sorted(unmet))
    )


# ---------------------------------------------------------------- the must-fire
#
# The pre-change blocks, verbatim. These are the texts that were on disk when the
# clean report was produced. Every anchor must report unmet against them, or this
# file is satisfied by prose that was already there.

RELEASE_AUDITOR_REPORT_FORMAT_AS_IT_STOOD = """
## Report format

Open with the verdict line, in exactly one of these shapes, and nothing before it:

```
VERDICT: clean          -- range <range>, <n> commits, round <1|2>
VERDICT: findings       -- range <range>, <n> findings, round <1|2>
VERDICT: could not run  -- <the reason the script gave>
```

Then, per class, one line each -- every class named even when empty, because a class you skipped and a
class that was clean look identical otherwise. Each finding: file, line, the class, **its ranking row**
(or `unranked` / `could not rank`), what an attacker or a caller gets, and the one fact that would
settle it.

**`could not run` never renders as clean, and neither does a per-class `could not check`.** The
first of the two stops the release. `clean` means you looked at the whole range and found nothing;
if you could not look, that is the third outcome, whatever the schedule wants it to be.
"""

RELEASE_COMMAND_SPAWN_BLOCK_AS_IT_STOOD = """
   Then, and only for the two computable states of the range:

   ```
   Agent(subagent_type: "oss:release-auditor", run_in_background: false)
   ```

   Hand it the payload verbatim and the round number. It writes nothing and it does not tag. **A
   spawn that did not run is `could not run`**, never a clean audit -- if the agent fails to start or
   comes back empty, that is the third outcome and the same stop applies.

   - **Quote the spawn error verbatim in the release report.** It is the only thing that separates a
     wiring failure from a clean audit, and both otherwise render as silence.
   - **If the fallback does not run either, the gate is `could not run` and the release stops.**
"""


def test_the_producer_checks_fire_on_the_report_format_as_it_stood():
    """The third state was already in that block -- `could not check`, required,
    declared never to render as clean. The report that missed class B had
    somewhere honest to put "I did not exercise this" and graded it checked
    instead. So none of these anchors may be satisfied by what was there.
    """
    unmet = _producer_unmet(RELEASE_AUDITOR_REPORT_FORMAT_AS_IT_STOOD)
    assert unmet == PRODUCER_IDS, (
        "these anchors are satisfied by the report format that was already on "
        "disk when the clean report was produced, so they constrain nothing new. "
        "Not firing: " + repr(sorted(PRODUCER_IDS - unmet))
    )


def test_the_consumer_checks_fire_on_the_spawn_block_as_it_stood():
    """That block already handled a spawn that did not run and a spawn whose name
    did not resolve. What it had no arm for is a spawn that ran, returned, and
    cannot be joined to the dispatch it answers.
    """
    unmet = _consumer_unmet(RELEASE_COMMAND_SPAWN_BLOCK_AS_IT_STOOD)
    assert unmet == CONSUMER_IDS, (
        "these anchors are satisfied by the spawn block that was already on "
        "disk, so they say nothing about attribution. Not firing: "
        + repr(sorted(CONSUMER_IDS - unmet))
    )


def test_naming_a_term_without_a_disposition_still_fires():
    """The narrow must-fire the broad one would not have caught.

    A document can name every term and decide nothing, which is the shape a
    checker keyed on vocabulary alone reports as compliant.
    """
    named_only = (
        "- `clean (exercised)` is one grade.\n"
        "- `clean (read)` is the other.\n"
        "\n"
        "A dispatch token accompanies the payload.\n"
        "\n"
        "An unattributed completion is one whose token does not match.\n"
        "\n"
        "```\n"
        "VERDICT: clean -- range <range>, <n> commits, round <1|2>\n"
        "```\n"
    )
    producer = _producer_unmet(named_only)
    assert producer == {
        "a-read-grade-never-renders-as-a-measured-one",
        "a-control-has-to-be-able-to-fail",
        "the-verdict-line-carries-the-unexercised-count",
        "has-a-no-token-reached-me-state",
    }, repr(sorted(producer))

    consumer = _consumer_unmet(named_only)
    assert consumer == {
        "names-the-unexercised-count",
        "an-unattributed-completion-does-not-clear-the-gate",
        "an-unattributed-completion-is-not-discarded",
        "has-an-arm-for-more-than-one-completion",
        "an-unexercised-class-does-not-stop-the-tag-by-itself",
        "a-read-grade-never-outweighs-a-reproduction",
    }, repr(sorted(consumer))


def test_collapsing_the_two_grades_into_one_arm_fires():
    """The positive control for the only reason the grades are two words.

    A document that mentions both grades in one breath and never separates them
    is the state where the reading inherits the measurement's standing -- and
    every other anchor here is satisfied, so nothing but the separation is under
    test.
    """
    collapsed = (
        "- Grade each clean class `clean (exercised)` or `clean (read)`, whichever fits; "
        "a control would have failed had the class been present, and a reading never "
        "renders as a measurement.\n"
        "\n"
        "The dispatch token, or `none reached me`.\n"
        "\n"
        "```\n"
        "VERDICT: clean -- range <range>, round <1|2>, <k> read but not exercised\n"
        "```\n"
    )
    unmet = _producer_unmet(collapsed)
    assert unmet == {
        "names-unattributed",
        "keeps-clean-read-apart",
        "keeps-clean-exercised-apart",
    }, repr(sorted(unmet))


def test_every_registered_term_carries_its_sentence():
    """A registry of bare names decays into boilerplate. The sentence is what
    makes the next person argue with the entry rather than extend it.
    """
    registered = list(EVIDENCE_GRADES.items()) + list(ATTRIBUTION_STATES.items())
    thin = {term: why for term, why in registered if len(why.split()) < 12}
    assert not thin, (
        "these terms are registered with no argument for why they are separate, "
        "which is the one thing this registry exists to carry: " + repr(sorted(thin))
    )


def test_the_derived_id_sets_are_the_ones_the_checkers_can_emit():
    """The control on the controls.

    Both must-fire tests compare against these sets, so a set that silently
    lost an id would make them weaker without failing. Pinning the counts makes
    an id added to a checker and never emitted -- a typo in an anchor, an
    unreachable branch -- fail here rather than pass everywhere.
    """
    assert len(PRODUCER_IDS) == 10, sorted(PRODUCER_IDS)
    assert len(CONSUMER_IDS) == 8, sorted(CONSUMER_IDS)


def test_the_reader_fails_rather_than_returning_an_empty_document(tmp_path):
    """`_doc` returning "" for a file it could not read would make every anchor
    fire at once and read as a document that says nothing.

    The deny is measured rather than assumed: root ignores the mode bit, some
    filesystems ignore it, and Windows' `os.chmod` on a file toggles a read-only
    attribute that does not stop a read. The skip sits outside any
    `pytest.raises` block, because pytest's outcome exceptions derive from
    `BaseException` and a skip raised inside one sails past it, reporting green
    over an assertion that never ran.
    """
    readable = tmp_path / "readable.md"
    readable.write_text("clean (read)\n", encoding="utf-8")
    assert _doc(readable) == "clean (read)\n", (
        "the reader does not read a readable file, so failing on an unreadable "
        "one would prove nothing"
    )

    locked = tmp_path / "locked.md"
    locked.write_text("x\n", encoding="utf-8")
    os.chmod(locked, 0o000)
    try:
        try:
            locked.read_bytes()
        except OSError:
            denied = True
        else:
            denied = False

        if not denied:
            pytest.skip(
                "chmod 000 did not stop a read of {} on this platform, so what "
                "went untested is whether _doc fails instead of returning an "
                "empty document".format(locked)
            )

        try:
            _doc(locked)
        except BaseException as exc:  # noqa: BLE001 - pytest outcomes are BaseException
            assert type(exc).__name__ == "Failed", (
                "an unreadable document reached the checkers as something other "
                "than a test failure: " + type(exc).__name__
            )
        else:
            pytest.fail(
                "_doc returned instead of failing on a document it could not read"
            )
    finally:
        os.chmod(locked, 0o600)
