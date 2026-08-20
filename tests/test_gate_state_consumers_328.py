"""Every document that restates `scaffolded_changelog_gate`'s contract has an
arm for every state the function can actually return (#328).

#325 gave the gate a fourth state, `present-other-dir`. `scripts/oss_config.py`
and `scripts/release_version.py` grew arms for it. `commands/changelog.md`'s
embedded resolver did not -- it branched on `present` and `unknown` and let
everything else fall through to `NOT-ADOPTED`, so a repository whose gate the
new code can now locate correctly got `/oss:changelog` refusing outright. And
`commands/scaffold.md` still described the contract as "present ... absent".
Neither failed while it was wrong. A contract stated in four documents was
changed in two.

## Why the state list is derived and the consumer list is not

The two halves of a producer -> consumer join go stale in opposite directions,
so they are built differently on purpose.

The **states** are read out of the producer's own source -- the `return "..."`
literals inside `def scaffolded_changelog_gate`. That is the half that just
failed: a state was added to the code and the documents did not follow. A
hand-written registry would have to be updated by the same commit that adds the
state, so it would have gone green on exactly the change it exists to catch.
Derivation cannot. (`tests/test_release_gate_rowless_findings.py` registers its
vocabulary by hand and is right to: its producer is prose, where an extractor
has a third state of its own -- "the defining paragraph moved, so I found
nothing" -- and would report that as a clean join. Here the producer is code and
the extraction has a checkable failure, asserted below.)

The **consumers** cannot be derived from the contract: "which documents describe
this" is not a fact on disk. So `GATE_STATE_CONSUMERS` is hand-written, and that
is the weaker half -- #321 is the open filing about the equivalent tuple in the
rowless test being incomplete for precisely this reason. One cheap staleness is
caught anyway: a file under `commands/` or `scripts/` that names the producer
and is on neither list fails below. A document that restates the contract
without naming the function is not reachable that way, and is not claimed to be.

## Naming a state means naming it as a delimited literal

The bar is a delimited occurrence -- backticked in prose, quoted in code --
never the bare word. "absent", "present" and "unknown" are ordinary English and
appear all over both command files about other subjects entirely: measured on
`commands/scaffold.md` before this fix, a bare-substring test passes for three
of the four states. A check a document already satisfies by accident is the
absence this repository is named after wearing a green tick.

## Three states, including this file's own

Every checker here is a function over text, run against the real document, where
it must come back clean, and against synthetic text written to break exactly one
thing, where it must fire for a named reason. A checker that cannot fire passes
on prose nobody constrained. And a document or a function body that could not be
read is a failure with its own name, never an empty set of findings.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PRODUCER = REPO_ROOT / "scripts" / "oss_config.py"
PRODUCER_FUNCTION = "scaffolded_changelog_gate"

CHANGELOG_COMMAND = REPO_ROOT / "commands" / "changelog.md"
SCAFFOLD_COMMAND = REPO_ROOT / "commands" / "scaffold.md"
RELEASE_VERSION = REPO_ROOT / "scripts" / "release_version.py"

# Enforced now: both are inside #328's file set.
ENFORCED_CONSUMERS = (CHANGELOG_COMMAND, SCAFFOLD_COMMAND)

# Listed, not enforced -- and listed so the census of consumers is complete
# rather than trimmed to what one lane could reach. `_fragment_dir` has explicit
# arms for `present`, `present-other-dir` and `unknown` and then a bare trailing
# `return None, NO_DIRECTORY` that serves `absent`. Its behaviour is right
# today; its *spelling* is a catch-all, so a fifth state would render as "never
# adopted" -- the same class one file over. Making that an explicit arm is one
# line in a file held by another lane while #328 was implemented, so it is
# deferred with a reason rather than reached into.
#
# The deferral cannot rot silently: the test below fails the moment the entry
# stops being an exception, which is this repository's rule for exception lists.
DEFERRED_CONSUMERS = {
    RELEASE_VERSION: (
        "_fragment_dir serves `absent` from a trailing catch-all `return` "
        "rather than a named arm; adding one is outside #328's file set"
    ),
}

GATE_STATE_CONSUMERS = ENFORCED_CONSUMERS + tuple(DEFERRED_CONSUMERS)

# A state is named when it appears wrapped in one of these. Both halves of the
# wrap are searched independently rather than as a pair, which is deliberately
# lax about mixed quoting and strict about the thing that matters: a bare word.
DELIMITERS = ("`", chr(34), chr(39))


def _doc(path):
    """Text, or a failure with its own name. Returning "" would make every
    check below fire at once and read like a document that names nothing, which
    is a different fact about the world.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail("could not read {}: {!r}".format(path, exc))


def _function_body(text, name):
    """The source of the top-level `def name(...)` in `text`.

    Raises `LookupError` when there is no such function. The caller turns that
    into a named failure: "the producer moved" and "the producer declares no
    states" are two facts, and collapsing them would let a rename report a
    stateless contract.
    """
    start = re.search(r"^def " + re.escape(name) + r"\(", text, re.MULTILINE)
    if start is None:
        raise LookupError("no top-level `def {}(` found".format(name))
    rest = text[start.end():]
    end = re.search(r"^(?:def |class |@)", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def producer_states(text):
    """Every state `scaffolded_changelog_gate` can return, read off its source.

    `return "literal"` and `return "literal", detail` both count; a `return` of
    a variable does not, and could not -- which is why the degenerate result is
    asserted against rather than trusted.
    """
    body = _function_body(text, PRODUCER_FUNCTION)
    return set(re.findall(r'return\s+"([a-z][a-z-]*)"', body))


def states_unnamed_by(text, states):
    """The states this document does not name as a delimited literal."""
    unnamed = set()
    for state in states:
        wrapped = [
            left + state + right for left in DELIMITERS for right in DELIMITERS
        ]
        if not any(candidate in text for candidate in wrapped):
            unnamed.add(state)
    return unnamed


def resolver_blocks(text):
    """Every fenced code block in a command file that calls the gate.

    Raises `LookupError` when none does. Scoping the changelog check to the
    block matters: naming `present-other-dir` in a sentence somewhere in the
    file would satisfy a whole-document check while the resolver kept falling
    through to `NOT-ADOPTED`.
    """
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    hits = [block for block in blocks if PRODUCER_FUNCTION in block]
    if not hits:
        raise LookupError("no fenced code block calls {}".format(PRODUCER_FUNCTION))
    return hits


# --- the join itself -------------------------------------------------------


def test_the_producer_still_declares_a_multi_state_contract():
    """The derivation's own third state. If this file cannot read states out of
    the producer, every consumer check below would pass vacuously.
    """
    try:
        states = producer_states(_doc(PRODUCER))
    except LookupError as exc:
        pytest.fail("{}: {}".format(PRODUCER, exc))
    assert len(states) >= 2, (
        "read only {!r} out of `def {}` in {} -- a one-state contract needs no "
        "join, so this is far more likely to be an extraction that stopped "
        "working than a contract that collapsed".format(
            sorted(states), PRODUCER_FUNCTION, PRODUCER
        )
    )
    assert "present-other-dir" in states, (
        "the state #325 added is gone from the producer; if it was renamed, "
        "rename it in every consumer too -- making that rename expensive to "
        "get wrong is what this file is for"
    )


def test_the_producer_extraction_reads_every_state_of_the_real_function():
    """Bound the derivation against the real file, so a regex that quietly
    matched only the first `return` could not pass the join below.
    """
    assert producer_states(_doc(PRODUCER)) == {
        "absent",
        "unknown",
        "present",
        "present-other-dir",
    }


@pytest.mark.parametrize("path", ENFORCED_CONSUMERS, ids=lambda p: p.name)
def test_every_enforced_consumer_names_every_gate_state(path):
    states = producer_states(_doc(PRODUCER))
    unnamed = states_unnamed_by(_doc(path), states)
    assert not unnamed, (
        "{} restates `{}`'s contract but has no arm for {} -- the producer "
        "returns {}. Name each state as a delimited literal (backticked in "
        "prose, quoted in code); the bare word does not count, because "
        "absent and present are ordinary English and already appear in these "
        "files about other subjects.".format(
            path.relative_to(REPO_ROOT),
            PRODUCER_FUNCTION,
            sorted(unnamed),
            sorted(states),
        )
    )


def test_the_changelog_resolver_branches_on_every_gate_state():
    """Whole-document naming is not enough for the one consumer that *executes*
    the contract. #328's actual defect was inside the fenced resolver.
    """
    states = producer_states(_doc(PRODUCER))
    try:
        blocks = resolver_blocks(_doc(CHANGELOG_COMMAND))
    except LookupError as exc:
        pytest.fail("{}: {}".format(CHANGELOG_COMMAND, exc))
    unnamed = states_unnamed_by("\n".join(blocks), states)
    assert not unnamed, (
        "the FRAGMENTS_DIR resolver in commands/changelog.md branches on none "
        "of {} -- so those states fall through to whichever arm is last, which "
        "is how `present-other-dir` came to print NOT-ADOPTED and exit 1 for a "
        "repository whose fragments the gate can locate.".format(sorted(unnamed))
    )


def test_the_deferred_consumer_is_still_deferred():
    """An exception list that has drifted is a licence. When this fails, the
    entry has been fixed -- promote it into ENFORCED_CONSUMERS and delete the
    entry; do not relax the assertion.
    """
    states = producer_states(_doc(PRODUCER))
    for path, reason in DEFERRED_CONSUMERS.items():
        unnamed = states_unnamed_by(_doc(path), states)
        assert unnamed, (
            "{} is listed in DEFERRED_CONSUMERS ({}) but now names every gate "
            "state. Move it into ENFORCED_CONSUMERS and remove the deferral."
            .format(path.relative_to(REPO_ROOT), reason)
        )


def test_the_consumer_census_lists_every_file_that_calls_the_gate():
    """A tuple that omits a consumer is #321. This does not derive the list --
    it cannot -- but it catches the cheapest way for it to go stale.
    """
    listed = set(GATE_STATE_CONSUMERS)
    callers = set()
    for directory in ("commands", "scripts"):
        for path in sorted((REPO_ROOT / directory).rglob("*")):
            if path == PRODUCER or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if PRODUCER_FUNCTION in text:
                callers.add(path)
    missing = sorted(str(p.relative_to(REPO_ROOT)) for p in callers - listed)
    assert not missing, (
        "{} name `{}` and are in neither ENFORCED_CONSUMERS nor "
        "DEFERRED_CONSUMERS. Add each, enforced if it can be fixed now and "
        "deferred with a reason if it cannot.".format(missing, PRODUCER_FUNCTION)
    )


# --- positive controls: every checker above must be able to fire ------------


def test_the_state_check_fires_on_a_document_missing_one_state():
    text = "handles `present`, `absent` and `unknown`."
    unnamed = states_unnamed_by(
        text, {"present", "absent", "unknown", "present-other-dir"}
    )
    assert unnamed == {"present-other-dir"}


def test_the_state_check_is_not_satisfied_by_the_bare_word():
    """The must-fire half, and the reason the delimiter is in the rule at all:
    this text says all four words and constrains nothing.
    """
    text = (
        "An absent directory is a failure. A wrong-but-present flag is worse. "
        "Whether it ran is unknown, and it may be present other dir."
    )
    unnamed = states_unnamed_by(
        text, {"present", "absent", "unknown", "present-other-dir"}
    )
    assert unnamed == {"present", "absent", "unknown", "present-other-dir"}


def test_the_state_check_passes_text_that_names_all_four():
    """The must-not-fire half. Without it, the two checks above would also pass
    against a checker that reported every state unnamed no matter what it read.
    """
    text = (
        "`present` falls back, `present-other-dir` carries the directory, "
        "`absent` refuses and `unknown` says why."
    )
    assert (
        states_unnamed_by(
            text, {"present", "absent", "unknown", "present-other-dir"}
        )
        == set()
    )


def test_the_state_check_accepts_code_quoting_as_well_as_backticks():
    text = "if state == 'present-other-dir':\n    print(detail)\n"
    assert states_unnamed_by(text, {"present-other-dir"}) == set()


def test_naming_the_longer_state_does_not_also_satisfy_the_shorter_one():
    """`present-other-dir` contains `present`. If the wrap were not required on
    both sides, this fixture would report `present` as named and the join would
    have a hole exactly where #328 sat.
    """
    text = "only `present-other-dir` is named here."
    assert states_unnamed_by(text, {"present", "present-other-dir"}) == {"present"}


def test_the_producer_extraction_fails_loudly_when_the_function_is_gone():
    with pytest.raises(LookupError):
        producer_states("def something_else(x):\n    return \"present\"\n")


def test_the_producer_extraction_stops_at_the_next_function():
    """A body that ran on past its own `def` would harvest states from
    unrelated functions and report a contract nobody wrote.
    """
    text = (
        "def scaffolded_changelog_gate(root):\n"
        "    return \"present\", \"\"\n"
        "\n\n"
        "def other(x):\n"
        "    return \"borrowed\"\n"
    )
    assert producer_states(text) == {"present"}


def test_the_resolver_block_extraction_fails_loudly_when_no_block_calls_it():
    with pytest.raises(LookupError):
        resolver_blocks("# a command file\n\n```bash\necho hi\n```\n")


def test_the_resolver_block_extraction_finds_the_calling_block_only():
    text = (
        "```bash\necho unrelated\n```\n\n"
        "```bash\nstate = oss_config.scaffolded_changelog_gate('.')\n```\n"
    )
    blocks = resolver_blocks(text)
    assert len(blocks) == 1
    assert "unrelated" not in blocks[0]
