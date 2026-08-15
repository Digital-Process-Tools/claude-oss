"""The release gate's arm for a finding that arrived without a row (#175), and
for a checklist whose own version it cannot name (#176).

Both are the same shape as everything else here: a state the vocabulary defines
and the consumer has no arm for, so the state renders as its cheapest neighbour.

#175. `agents/release-auditor.md` and `agents/auditor.md` define two answers a
finding can carry instead of a ranking row -- `unranked` (classified, no row
fits) and `could not rank` (the table never reached me). `commands/release.md`
blocked on "a finding in a row the ranking table marks blocking", a positive
membership test. A finding with no row at all is in no blocking row, so the
exception never fired and the two-round cap carried it forward. A rank that
could not be computed read exactly like a rank that is not blocking.

#176. The audit that found #175 was itself briefed from an installed plugin
cache two releases old, whose checklist predated the ranking requirement. That
is `could not rank` arriving in the wild, and it was visible only because one
agent volunteered it. So the gate now reads which checklist it is about to gate
with, and "I could not tell" is a state of that read rather than its silence.

## Why this is a file of its own and not another content invariant

The failure was a rule stated in one document and absent from its consumer, so
what is worth more than either edit is the join. These checks are producer ->
consumer: the vocabulary is asserted where it is *defined*, and every term is
then required to have an arm where it is *acted on*. A term renamed in the
agent files fails here until the gate has an arm under the new name.

## Three states, including this file's own

Every checker below is a function over text, run twice: against the real file,
where it must come back clean, and against synthetic text written to violate
exactly one thing, where it must fire. A checker that cannot fire passes on
prose nobody constrained, which is the defect these tests are about wearing the
harness's clothes. And a file that would not read is a failure, never an empty
set of findings -- `_doc` fails rather than returning "".
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_COMMAND = REPO_ROOT / "commands" / "release.md"
RELEASE_AUDITOR = REPO_ROOT / "agents" / "release-auditor.md"
AUDITOR = REPO_ROOT / "agents" / "auditor.md"

# The vocabulary, as a registry with a sentence each rather than a discovery
# run. A regex over prose would have its own third state -- "the defining
# paragraph moved, so I extracted nothing" -- and would report that as a clean
# join. Adding a term costs one entry here and one arm in the gate, which is
# the whole point.
ROWLESS_STATES = {
    "unranked": (
        "the finding was classified and no row in the ranking table fits. The "
        "rows are a record of what has already gone wrong rather than a "
        "partition of what can, so this is not a minor finding and must not be "
        "demoted to one."
    ),
    "could not rank": (
        "the table never reached the agent, so no row could be computed at "
        "all. This is a fact about the wiring, not about the code under audit, "
        "and it must never render as unranked."
    ),
}

# Words that make a chunk say what happens, rather than merely naming a state.
# Deliberately broad: this asserts that a disposition was written down, not
# which one was chosen. Which one is the maintainer's argument to have.
DISPOSITION_WORDS = ("block", "stops", "carry", "does not")


def _doc(path):
    """A document that would not read is a failure with its own name. Returning
    "" would make every `in` check below fire at once and read like a document
    that says nothing, which is a different fact.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail("could not read {}: {!r}".format(path, exc))


def _chunks(text):
    """Split prose into bullet items and paragraphs.

    The unit matters. Lines are too small -- a wrapped bullet would look like a
    state named with no disposition beside it. Paragraphs are too large -- a
    bullet list is one paragraph, so two states listed as two bullets would
    look like one collapsed arm. Break on a blank line or on the start of a new
    top-level bullet, and a two-bullet list is two chunks.
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


def _rowless_vocabulary_missing_from(text):
    folded = text.lower()
    return {term for term in ROWLESS_STATES if term not in folded}


def _rowless_arms_unmet(text):
    """What `commands/release.md` owes a finding that arrived without a row."""
    unmet = set()
    folded = text.lower()
    chunks = [chunk.lower() for chunk in _chunks(text)]

    for term in ROWLESS_STATES:
        slug = term.replace(" ", "-")
        if term not in folded:
            unmet.add("names-" + slug)
            unmet.add("says-what-happens-to-" + slug)
            continue
        arms = [chunk for chunk in chunks if term in chunk]
        if not any(word in arm for arm in arms for word in DISPOSITION_WORDS):
            unmet.add("says-what-happens-to-" + slug)

    # The two must not share one arm. Collapsing them re-creates the defect one
    # layer down: "I could not compute a rank" would inherit whatever was
    # decided for "no row fits", and the decision would be invisible.
    others = list(ROWLESS_STATES)
    for term in ROWLESS_STATES:
        rest = [other for other in others if other != term]
        alone = [
            chunk
            for chunk in chunks
            if term in chunk and not any(other in chunk for other in rest)
        ]
        if not alone:
            unmet.add("keeps-{}-apart".format(term.replace(" ", "-")))

    return unmet


# ------------------------------------------------ #176, the checklist in effect

CHECKLIST_ANCHOR = "checklist in effect"
CHECKLIST_THIRD_STATE = "could not tell"


def _checklist_read_unmet(text):
    """What the release command owes the question "which checklist am I gating
    with", in `commands/release.md`.
    """
    unmet = set()
    folded = text.lower()
    if CHECKLIST_ANCHOR not in folded:
        unmet.add("reads-which-checklist-is-in-effect")
    if CHECKLIST_THIRD_STATE not in folded:
        unmet.add("has-a-could-not-tell-state")
    if "never renders as a match" not in folded:
        unmet.add("could-not-tell-never-renders-as-a-match")
    # A repo that merely installed the plugin legitimately runs whatever it
    # installed. Stopping its release over a version skew it did not choose
    # trades a reporting gap for a release nobody can cut, which is the same
    # trade `scope: null` already refuses one gate over.
    if "annotate" not in folded:
        unmet.add("annotates-rather-than-stopping-a-repo-that-installed-it")
    return unmet


def _auditor_checklist_unmet(text):
    """The producer half: the agent has to say which checklist reached it, or
    say that it could not tell. Nothing else can measure this -- the gate reads
    what is on its own disk, and the agent is the only thing that knows what
    arrived in its brief.
    """
    unmet = set()
    folded = text.lower()
    if CHECKLIST_ANCHOR not in folded:
        unmet.add("reports-which-checklist-reached-it")
    if CHECKLIST_THIRD_STATE not in folded:
        unmet.add("has-a-could-not-tell-state")
    return unmet


# ----------------------------------------------------------- the joins themselves


def test_the_agent_files_still_define_both_rowless_states():
    """The producer end of the join. If a term is renamed here, every consumer
    assertion below would go on passing against a term nothing emits -- a join
    that holds because both ends moved out from under it.
    """
    for path in (RELEASE_AUDITOR, AUDITOR):
        missing = _rowless_vocabulary_missing_from(_doc(path))
        assert not missing, (
            "{} no longer defines {}, so the release gate's arm for it is "
            "wired to a state nothing emits. Rename it in ROWLESS_STATES and "
            "in commands/release.md together, or the gate silently stops "
            "covering it.".format(path.name, sorted(missing))
        )


def test_the_release_gate_has_an_arm_for_a_finding_with_no_row():
    unmet = _rowless_arms_unmet(_doc(RELEASE_COMMAND))
    assert not unmet, (
        "commands/release.md blocks on membership in a blocking row, and a "
        "finding that arrived without a row is in no row at all -- so the "
        "exception does not fire and the two-round cap carries it forward "
        "(#175). Unmet:\n  " + "\n  ".join(sorted(unmet))
    )


def test_the_release_command_names_the_checklist_it_is_gating_with():
    unmet = _checklist_read_unmet(_doc(RELEASE_COMMAND))
    assert not unmet, (
        "commands/release.md spawns the audit without recording which copy of "
        "the definitions it is about to gate with, so an audit run against a "
        "checklist older than the rules it gates reads as a clean one "
        "(#176). Unmet:\n  " + "\n  ".join(sorted(unmet))
    )


def test_the_release_auditor_reports_which_checklist_reached_it():
    unmet = _auditor_checklist_unmet(_doc(RELEASE_AUDITOR))
    assert not unmet, (
        "agents/release-auditor.md does not have to say which checklist "
        "arrived in its brief, so the one time it did was volunteered "
        "(#176). Unmet:\n  " + "\n  ".join(sorted(unmet))
    )


# ------------------------------------------------------------ positive controls
#
# Each checker above asserts an absence. An absence assertion passes when the
# harness is broken, so each one is paired here with text that must make it
# fire, in the same fixture.


def test_the_rowless_arm_check_fires_on_a_gate_that_says_nothing():
    says_nothing = (
        "## The gates are not configurable\n\n"
        "A security audit of the delta since the last tag passed. Two rounds, "
        "hard cap. Except a finding in a row the ranking table marks "
        "blocking, which is not carry-forward material.\n"
    )
    unmet = _rowless_arms_unmet(says_nothing)
    expected = {
        "names-unranked",
        "says-what-happens-to-unranked",
        "keeps-unranked-apart",
        "names-could-not-rank",
        "says-what-happens-to-could-not-rank",
        "keeps-could-not-rank-apart",
    }
    assert unmet == expected, (
        "the rowless-arm check does not fire on the pre-#175 gate text, so it "
        "would also pass on it. Not firing: "
        + repr(sorted(expected - unmet))
    )


def test_the_rowless_arm_check_fires_when_the_two_states_share_one_arm():
    """The case the issue names as the way to re-create the defect a layer
    down: both states present, a disposition stated, and no way to tell which
    of the two it was decided for.
    """
    collapsed = "- An `unranked` or `could not rank` finding blocks the tag.\n"
    unmet = _rowless_arms_unmet(collapsed)
    assert unmet == {"keeps-unranked-apart", "keeps-could-not-rank-apart"}, (
        "one arm covering both states passes the check, so `could not rank` "
        "can inherit whatever was decided for `unranked` invisibly. Got: "
        + repr(sorted(unmet))
    )


def test_the_rowless_arm_check_fires_on_states_named_with_no_disposition():
    """Naming the two is not the fix. The issue's requirement is that what
    happens to a rowless finding is *stated*, either way.
    """
    named_only = (
        "- A finding may come back `unranked`.\n"
        "- A finding may come back `could not rank`.\n"
    )
    unmet = _rowless_arms_unmet(named_only)
    assert unmet == {
        "says-what-happens-to-unranked",
        "says-what-happens-to-could-not-rank",
    }, (
        "two states named with nothing said about either passes, which is the "
        "gap #175 describes with the names filled in. Got: "
        + repr(sorted(unmet))
    )


def test_the_rowless_arm_check_passes_text_that_meets_it():
    """The must-fire cases above all assert a non-empty result, and a checker
    that returned every name unconditionally would satisfy all three. This is
    the other half: minimal text that meets the contract comes back clean.
    """
    meets_it = (
        "- **`unranked`** -- no row fits. It blocks the tag until it is "
        "ranked.\n"
        "- **`could not rank`** -- the table never reached the agent. That "
        "stops the tag.\n"
    )
    assert _rowless_arms_unmet(meets_it) == set()


def test_the_checklist_checks_fire_on_documents_that_say_nothing():
    says_nothing = "Spawn the auditor and read what it says.\n"
    command_unmet = _checklist_read_unmet(says_nothing)
    auditor_unmet = _auditor_checklist_unmet(says_nothing)
    assert command_unmet == {
        "reads-which-checklist-is-in-effect",
        "has-a-could-not-tell-state",
        "could-not-tell-never-renders-as-a-match",
        "annotates-rather-than-stopping-a-repo-that-installed-it",
    }, repr(sorted(command_unmet))
    assert auditor_unmet == {
        "reports-which-checklist-reached-it",
        "has-a-could-not-tell-state",
    }, repr(sorted(auditor_unmet))


def test_the_checklist_checks_pass_text_that_meets_them():
    meets_it = (
        "Record the checklist in effect: the version of the definitions this "
        "spawn will gate with. Three states -- it matches, it differs, or "
        "**could not tell**, which never renders as a match. It annotates.\n"
    )
    assert _checklist_read_unmet(meets_it) == set()
    assert _auditor_checklist_unmet(meets_it) == set()


def test_the_vocabulary_check_fires_on_an_agent_that_defines_neither():
    missing = _rowless_vocabulary_missing_from("An agent that ranks nothing.\n")
    assert missing == set(ROWLESS_STATES), repr(sorted(missing))


def test_every_registered_state_carries_its_sentence():
    """A registry of bare names decays into boilerplate. The sentence is what
    makes the next person argue with the entry rather than extend it.
    """
    thin = {
        term: why
        for term, why in ROWLESS_STATES.items()
        if len(why.split()) < 12
    }
    assert not thin, (
        "these states are registered with no argument for why they are "
        "separate, which is the one thing this registry exists to carry: "
        + repr(sorted(thin))
    )
