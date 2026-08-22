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

A document that is not *there* is a fourth answer, added by #396. `tracked_paths`
asks git for the index and `readable_texts` reads the working tree, so an
uncommitted delete arrives as a path that is not on disk -- and calling that
"could not read" reddened this census on a tree with nothing wrong with it. It is
named and does not sink the completeness claim: a file that is there and will not
read might name the producer and nobody can tell, while one that has been deleted
is a document leaving the tree. Nothing fired here before #396 only because the
scope is `commands/` and `scripts/`, which the changelog fold does not touch --
an accident of scope, not a property of the guard.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PRODUCER = REPO_ROOT / "scripts" / "oss_config.py"
PRODUCER_FUNCTION = "scaffolded_changelog_gate"

CHANGELOG_COMMAND = REPO_ROOT / "commands" / "changelog.md"
SCAFFOLD_COMMAND = REPO_ROOT / "commands" / "scaffold.md"
RELEASE_VERSION = REPO_ROOT / "scripts" / "release_version.py"

# #348's producer/consumer pair. Both functions live in the same file, so
# there is exactly one `_doc` read and one `_function_body` extraction on
# each side -- see `producer_states`'s docstring for why this does not join
# `GATE_STATE_CONSUMERS`.
LAUNCHER_PRODUCER = REPO_ROOT / "scripts" / "doctor.py"
LAUNCHER_PRODUCER_FUNCTION = "oss_workspace_launcher_state"
LAUNCHER_CONSUMER_FUNCTION = "check_oss_workspace_launcher"

# Enforced. The first two were inside #328's file set; `release_version.py` joined
# them in #343, which is the deferral below coming good rather than being relaxed.
#
# #328 deferred it with a reason: `_fragment_dir` served `absent` from a bare
# trailing `return None, NO_DIRECTORY`, so a fifth state would have rendered as
# "never adopted" -- right behaviour, catch-all spelling -- and the one line that
# fixes it sat in a file another lane held at the time. #343 added exactly that
# fifth state, so the deferred risk was the one that materialised; the file now
# has a named arm per state and a trailing arm that says it recognised nothing.
#
# `CHANGELOG_COMMAND` left ENFORCED_CONSUMERS the same way #343 arrived: #347 added
# the sixth state, `present-bare-dir`, and `commands/changelog.md` is `fix/346`'s
# file for this round (it owns `scripts/assemble_changelog.py`,
# `.oss/assemble_changelog.py` and `commands/changelog.md`) -- so the one line that
# names the new state there sits in a file this lane does not hold. It is deferred
# below rather than skipped past.
ENFORCED_CONSUMERS = (SCAFFOLD_COMMAND, RELEASE_VERSION)

# Not empty as of #347. `commands/changelog.md`'s resolver already refuses a state
# it does not recognise -- its own trailing `else` prints `UNKNOWN: unrecognised
# gate state ...` and exits 1 -- so deferring the friendlier `REFUSED: <detail>`
# arm for `present-bare-dir` is a worse message, never a silent acceptance. That
# safety is asserted directly in `test_the_changelog_resolver_falls_through_safely`
# rather than taken on faith.
DEFERRED_CONSUMERS = {
    CHANGELOG_COMMAND: (
        "present-bare-dir (#347): commands/changelog.md is fix/346's file for "
        "this round; its resolver's existing catch-all else already refuses the "
        "state loudly rather than silently, so deferring costs a worse message, "
        "not a wrong one."
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

    Both arms still fail, and that is deliberate: these are the *hardcoded* consumer
    paths rather than an enumeration of the index, so a named document that is gone
    means `GATE_STATE_CONSUMERS` is stale -- a finding, not the ordinary uncommitted
    delete `readable_texts` learned to tolerate. Only the sentence differed, and it
    said `could not read` about a file that was simply not there (#396).
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pytest.fail(
            "{} is named as a gate-state consumer and is not on disk. Either it was "
            "deleted and GATE_STATE_CONSUMERS still names it, or it was renamed -- "
            "update the tuple. (Nothing failed to read here; there was nothing to "
            "read.)".format(path)
        )
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


def producer_states(text, function_name=PRODUCER_FUNCTION):
    """Every state a producer function can return, read off its source.

    `return "literal"` and `return "literal", detail` both count; a `return` of
    a variable does not, and could not -- which is why the degenerate result is
    asserted against rather than trusted.

    `function_name` defaults to `scaffolded_changelog_gate`, this file's
    original subject. #348 reuses this same derivation for a second,
    unrelated producer/consumer pair inside `scripts/doctor.py` --
    `oss_workspace_launcher_state` and `check_oss_workspace_launcher` -- so
    the extraction itself is parameterised rather than duplicated. The
    census machinery below it (`tracked_paths`, `unlisted_callers`,
    `GATE_STATE_CONSUMERS`) is deliberately NOT reused for that second pair:
    it exists to find which files, anywhere under `commands/` or `scripts/`,
    restate one gate's contract in prose, and #348's producer and consumer
    are two functions in the same file -- there is no discovery problem to
    solve, only an exhaustiveness one, which `states_unnamed_by` already
    answers on its own.
    """
    body = _function_body(text, function_name)
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


def tracked_paths(root, directories):
    """(paths, problem_or_None) -- the files git tracks under `directories`.

    Not a filesystem walk. The first version of this census walked the
    directories with `Path.rglob` and swallowed every read error, which is the
    absence-produced-by-the-tool shape; replacing that swallow with a reported
    `unreadable` list immediately turned up eleven `.pyc` files under
    `scripts/__pycache__` -- build output the walk had been silently skipping
    all along. The answer is not a suffix filter, which is #193 wearing a
    different hat, but a better question: "which files are part of this
    repository" is something git already knows, and it excludes build output by
    construction rather than by a pattern somebody has to keep current.

    git failing to answer is its own state and is never folded into "no files
    tracked" -- an empty list would let the census pass while measuring
    nothing, which is the failure this file is named after.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--"] + list(directories),
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return [], "git could not be run: {!r}".format(exc)
    if completed.returncode != 0:
        return [], "git ls-files exited {}: {}".format(
            completed.returncode,
            completed.stderr.decode("utf-8", "replace").strip(),
        )
    names = [
        chunk
        for chunk in completed.stdout.decode("utf-8", "surrogateescape").split("\0")
        if chunk
    ]
    return [Path(root) / name for name in names], None


def readable_texts(paths):
    """({path: text}, unreadable, absent) -- three lists, never one.

    A path that will not read is reported rather than skipped. Skipping it
    removes a possible consumer from the census and leaves the caller saying
    "nothing is missing" about a file it never opened.

    `absent` is the third of them and it is a different fact (#396). `tracked_paths`
    asks git for the **index**; every read here happens in the **working tree**, so
    an uncommitted delete hands this function a path that is not there. Both lists
    are named by the caller and only `unreadable` sinks the completeness claim: a
    file that is there and will not read might name the producer and nobody can
    tell, while one that has been deleted is a document leaving the tree rather
    than a hole in the census. This site is green today only because its scope is
    `commands/` and `scripts/`, which the changelog fold does not touch -- an
    accident of scope, not a property of the guard.

    The exception already in hand decides which: `FileNotFoundError` is absence,
    any other `OSError` is a read that failed. No second question is put to the
    filesystem -- `exists()` swallows a short list of errnos and re-raises the rest.
    On Windows several Win32 codes fold onto ENOENT, so an unlookable path reads as
    absent there; degraded, not silent, because it is named either way.
    """
    texts = {}
    unreadable = []
    absent = []
    for path in paths:
        if path == PRODUCER:
            continue
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            absent.append((path, exc))
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append((path, exc))
    return texts, unreadable, absent


def unlisted_callers(texts, listed):
    """Files that name the producer and are on neither consumer list."""
    return {
        path
        for path, text in texts.items()
        if PRODUCER_FUNCTION in text and path not in listed
    }


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
        "present-refused-dir",
        "present-bare-dir",
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

    `CHANGELOG_COMMAND` is deferred as of #347 (see `DEFERRED_CONSUMERS`), so a
    gap here is expected right now rather than a regression -- asserted as
    exactly that below, on the same shape as `test_the_deferred_consumer_is_
    still_deferred`, rather than skipped past. `test_the_changelog_resolver_
    falls_through_safely` is what pins the gap is safe rather than silent.
    """
    states = producer_states(_doc(PRODUCER))
    try:
        blocks = resolver_blocks(_doc(CHANGELOG_COMMAND))
    except LookupError as exc:
        pytest.fail("{}: {}".format(CHANGELOG_COMMAND, exc))
    unnamed = states_unnamed_by("\n".join(blocks), states)
    if CHANGELOG_COMMAND in DEFERRED_CONSUMERS:
        assert unnamed, (
            "{} is listed in DEFERRED_CONSUMERS ({}) but its resolver now "
            "branches on every gate state. Move it into ENFORCED_CONSUMERS and "
            "remove the deferral.".format(
                CHANGELOG_COMMAND.relative_to(REPO_ROOT),
                DEFERRED_CONSUMERS[CHANGELOG_COMMAND],
            )
        )
        return
    assert not unnamed, (
        "the FRAGMENTS_DIR resolver in commands/changelog.md branches on none "
        "of {} -- so those states fall through to whichever arm is last, which "
        "is how `present-other-dir` came to print NOT-ADOPTED and exit 1 for a "
        "repository whose fragments the gate can locate.".format(sorted(unnamed))
    )


def test_the_changelog_resolver_falls_through_safely_for_the_deferred_state():
    """The deferred gap above must be a worse message, never a wrong one: the
    resolver's own trailing `else` has to still be there and still refuse.

    Without this, deferring a consumer would be indistinguishable from a
    resolver that silently accepted an unrecognised state -- exactly the #328
    shape this whole file exists to catch, one level down.
    """
    text = _doc(CHANGELOG_COMMAND)
    try:
        blocks = resolver_blocks(text)
    except LookupError as exc:
        pytest.fail("{}: {}".format(CHANGELOG_COMMAND, exc))
    joined = "\n".join(blocks)
    assert "else:" in joined, (
        "commands/changelog.md's resolver has no trailing else -- a deferred "
        "state would fall through with no refusal at all"
    )
    assert "unrecognised gate state" in joined, (
        "commands/changelog.md's resolver's catch-all no longer names what it "
        "did not understand -- a deferred state would be accepted silently "
        "rather than refused loudly"
    )


def test_the_deferred_consumer_is_still_deferred():
    """An exception list that has drifted is a licence. When this fails, the
    entry has been fixed -- promote it into ENFORCED_CONSUMERS and delete the
    entry; do not relax the assertion.

    Three outcomes, not two. The list is empty as of #343, and an empty loop is
    a green tick over nothing -- exactly the shape this file is named after. So
    emptiness skips with what went untested rather than passing: no deferral
    exists to have rotted, which is a different fact from every deferral being
    intact, and the next entry added restores the assertion automatically.
    """
    if not DEFERRED_CONSUMERS:
        pytest.skip(
            "DEFERRED_CONSUMERS is empty (release_version.py was promoted in "
            "#343), so there is no deferral to check for rot -- this control "
            "measured nothing rather than confirming anything"
        )
    states = producer_states(_doc(PRODUCER))
    for path, reason in DEFERRED_CONSUMERS.items():
        unnamed = states_unnamed_by(_doc(path), states)
        assert unnamed, (
            "{} is listed in DEFERRED_CONSUMERS ({}) but now names every gate "
            "state. Move it into ENFORCED_CONSUMERS and remove the deferral."
            .format(path.relative_to(REPO_ROOT), reason)
        )


def test_the_deferral_check_would_fire_on_a_deferral_that_came_good():
    """The must-fire half the skip above would otherwise hide. The real list is
    empty, so the assertion it guards can no longer run against anything -- and
    a control that cannot fire is the licence this file exists to refuse. This
    runs the same predicate against a document that names every state, which is
    precisely the condition that must promote an entry.
    """
    states = producer_states(_doc(PRODUCER))
    complete = " ".join("`{}`".format(state) for state in sorted(states))
    assert states_unnamed_by(complete, states) == set(), (
        "a document naming every state must read as fully covered, or the "
        "deferral check could never notice an entry that came good"
    )
    assert states_unnamed_by("names `present` only", states), (
        "a document missing states must read as incomplete, or every entry "
        "would look permanently deferred"
    )


def test_the_consumer_census_lists_every_file_that_calls_the_gate():
    """A tuple that omits a consumer is #321. This does not derive the list --
    it cannot -- but it catches the cheapest way for it to go stale.

    The census claims *completeness*, so a file it could not read sinks the
    claim rather than being skipped past. `unreadable` is asserted before
    `missing`: "no consumer was missed" and "a consumer may have been missed
    and I could not tell" are two answers, and reporting the second as the
    first is the defect this whole file is about, one layer down.
    """
    paths, problem = tracked_paths(REPO_ROOT, ("commands", "scripts"))
    assert problem is None, (
        "the consumer census could not list the repository's own files ({}), "
        "so it measured nothing -- which is not the same answer as no "
        "consumer being missing.".format(problem)
    )
    assert paths, (
        "git tracks no files under commands/ or scripts/, which cannot be "
        "true of this repository -- the census is looking somewhere wrong"
    )
    texts, unreadable, absent = readable_texts(paths)
    assert not unreadable, (
        "the consumer census could not read {} -- so it cannot claim that no "
        "consumer is missing from GATE_STATE_CONSUMERS. An unreadable file is "
        "unknown, not absent.".format(
            [(str(p), repr(e)) for p, e in unreadable]
        )
    )
    # #396. Absence is named rather than dropped, and it does not sink the claim the
    # way `unreadable` does: a path git lists and the working tree does not hold is a
    # document leaving the tree, not a file this census failed to read. The assertion
    # runs first so an uncommitted delete cannot disable the check for every other
    # file, and the absence rides along in the message; the skip below reports it on
    # the ordinary green run, where there is no message to ride on.
    caveat = ""
    if absent:
        caveat = "\n\n  Note: {} tracked path(s) are in the index and not on disk, " \
            "so the census did not read them: {}".format(
                len(absent), [str(p) for p, _e in absent]
            )
    missing = unlisted_callers(texts, set(GATE_STATE_CONSUMERS))
    assert not missing, (
        "{} name `{}` and are in neither ENFORCED_CONSUMERS nor "
        "DEFERRED_CONSUMERS. Add each, enforced if it can be fixed now and "
        "deferred with a reason if it cannot.".format(
            sorted(str(p.relative_to(REPO_ROOT)) for p in missing),
            PRODUCER_FUNCTION,
        )
        + caveat
    )
    if absent:
        pytest.skip(
            "the census is clean, but {} tracked path(s) are in the index and not on "
            "disk and were not read. This is what an uncommitted delete under "
            "commands/ or scripts/ looks like; before #396 it read as a tree that "
            "could not be read and reddened this test: {}".format(
                len(absent),
                [(str(p), repr(e)) for p, e in absent],
            )
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


def test_the_census_fires_on_a_caller_that_is_on_neither_list(tmp_path):
    """The must-fire half the census had none of. Without it, a green run
    proves the census agrees with today's file set and nothing more.
    """
    listed = tmp_path / "listed.md"
    listed.write_text("calls scaffolded_changelog_gate\n", encoding="utf-8")
    stranger = tmp_path / "stranger.md"
    stranger.write_text("also calls scaffolded_changelog_gate\n", encoding="utf-8")
    texts, unreadable, _ = readable_texts([listed, stranger])
    assert unreadable == []
    assert unlisted_callers(texts, {listed}) == {stranger}


def test_the_census_stays_silent_when_every_caller_is_listed(tmp_path):
    """The must-not-fire half. Paired with the above, this separates a census
    that discriminates from one that reports every file it sees.
    """
    listed = tmp_path / "listed.md"
    listed.write_text("calls scaffolded_changelog_gate\n", encoding="utf-8")
    quiet = tmp_path / "quiet.md"
    quiet.write_text("mentions nothing at all\n", encoding="utf-8")
    texts, _, _ = readable_texts([listed, quiet])
    assert unlisted_callers(texts, {listed}) == set()


def test_the_census_reports_a_file_it_cannot_decode_rather_than_skipping_it(
    tmp_path,
):
    """The third state of the read, and it needs no privileges and no
    platform-specific mode bits: bytes that are not UTF-8 are not UTF-8
    everywhere. A file that would have been a caller must not vanish.
    """
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe calls scaffolded_changelog_gate\n")
    texts, unreadable, _ = readable_texts([bad])
    assert bad not in texts
    assert [path for path, _exc in unreadable] == [bad]
    assert isinstance(unreadable[0][1], (UnicodeDecodeError, OSError))


def test_a_named_consumer_that_is_gone_fails_with_the_right_sentence(tmp_path):
    """The same wrong word one function over, found by dogfooding #396.

    `_doc` reads the *hardcoded* consumer paths rather than an enumeration, so it is
    not the index-versus-tree class and it is right to fail: a document named in
    `GATE_STATE_CONSUMERS` that has been deleted means the tuple is stale, which is a
    finding rather than an ordinary uncommitted delete. Only its sentence was wrong --
    it said `could not read` about a file that was simply not there, which is the
    exact wording #396 is about.

    So the verdict is unchanged and asserted here: both arms still fail. Paired with
    the unreadable arm below, which must keep its own words.
    """
    # `pytest.fail.Exception` rather than `Exception`: pytest's outcome types derive
    # from `BaseException`, so a bare `raises(Exception)` would let the failure sail
    # past and skip the enclosing test -- a green tick over an assertion that never
    # ran, which `CLAUDE.md` names as a trap. Pinning it also proves this is the
    # `fail` arm and not some other error on the way.
    gone = tmp_path / "never-written.md"
    with pytest.raises(pytest.fail.Exception) as caught:
        _doc(gone)
    message = str(caught.value)
    assert "could not read" not in message, (
        "a document that is not there is not one this process failed to read: "
        "{!r}".format(message)
    )
    assert "not on disk" in message, message
    assert str(gone) in message, message

    denied = tmp_path / "denied.md"
    denied.write_text("hello\n", encoding="utf-8")
    try:
        denied.chmod(0)
        try:
            denied.read_bytes()
        except OSError:
            pass
        else:
            pytest.skip(
                "mode 0 did not deny a read here, so this platform cannot produce a "
                "named consumer that exists and will not read. UNTESTED here: whether "
                "that arm keeps its own `could not read` wording. The absent arm above "
                "was asserted."
            )
        with pytest.raises(pytest.fail.Exception) as caught:
            _doc(denied)
        assert "could not read" in str(caught.value), (
            "the control: a file that IS there and will not read must keep the "
            "`could not read` wording, or the split has collapsed the other way; got "
            "{!r}".format(str(caught.value))
        )
    finally:
        denied.chmod(0o600)


def test_a_path_in_the_index_and_not_on_disk_is_absent_not_unreadable(tmp_path):
    """#396. `tracked_paths` asks git for the **index** and `readable_texts` reads the
    **working tree**, so an uncommitted delete arrives here as a path that is not
    there. Filing it under `unreadable` sinks the census's completeness claim and
    reddens `test_the_consumer_census_lists_every_file_that_calls_the_gate` on a tree
    with nothing wrong with it.

    This site is green today only because its scope is `commands/` and `scripts/`,
    which the changelog fold does not touch -- an accident of scope, not a property of
    the guard. Any uncommitted delete under those two directories reddens it.

    Paired with a file that is there and will not read, which is the control: a fix
    that renamed every failed read to `absent` would otherwise pass. The deny is
    measured, because root ignores the mode bit and some filesystems do too.
    """
    denied = tmp_path / "denied.md"
    denied.write_text("calls scaffolded_changelog_gate\n", encoding="utf-8")
    gone = tmp_path / "gone.md"

    try:
        denied.chmod(0)
        try:
            denied.read_bytes()
        except OSError:
            deny_took = True
        else:
            deny_took = False

        texts, unreadable, absent = readable_texts([denied, gone])

        assert [path for path, _exc in absent] == [gone], (
            "a path git lists and the working tree does not hold is not a file this "
            "process failed to read; got absent={!r} unreadable={!r}".format(
                absent, unreadable
            )
        )
        assert gone not in texts
        if deny_took:
            assert [path for path, _exc in unreadable] == [denied], (
                "the control: a file that IS there and will not read must still sink "
                "the completeness claim; got {!r}".format(unreadable)
            )
        else:
            pytest.skip(
                "mode 0 did not deny a read here, so this platform cannot produce a "
                "listed-and-unreadable file. UNTESTED here: whether a file that exists "
                "and will not read still lands in `unreadable` rather than being "
                "folded into the `absent` bucket #396 added. The absent half above was "
                "asserted."
            )
    finally:
        denied.chmod(0o600)


def test_an_absent_path_does_not_sink_the_completeness_claim(tmp_path):
    """Why absence is reported and does not refuse, where `unreadable` refuses.

    A file that is there and will not read is a hole in the census: it might name the
    producer and nobody can tell. A file that has been deleted is not a hole -- it is
    a document leaving the tree, and it will be gone from the tuple too. So it is
    named and does not decide the verdict, which is the shape #395 settled.

    The must-fire half is the assertion in the census test itself, which still refuses
    on `unreadable`; `test_the_census_reports_a_file_it_cannot_decode_rather_than_
    skipping_it` keeps that bucket filling.
    """
    listed = tmp_path / "listed.md"
    listed.write_text("calls scaffolded_changelog_gate\n", encoding="utf-8")
    gone = tmp_path / "gone.md"

    texts, unreadable, absent = readable_texts([listed, gone])

    assert unreadable == [], (
        "an uncommitted delete must not read as a tree this census could not read; "
        "got {!r}".format(unreadable)
    )
    assert [path for path, _exc in absent] == [gone]
    assert unlisted_callers(texts, {listed}) == set(), (
        "the control: the census must still work normally around the absent path, or "
        "the absent arm has cost it the files it can read"
    )


def test_the_census_reports_a_listing_it_could_not_get(tmp_path):
    """The third state of the *enumeration*. `tmp_path` is not a git
    repository, so `git ls-files` refuses -- and the census must return that
    refusal rather than an empty file list, which would pass every assertion
    after it while measuring nothing.

    If this environment has no git at all, the OSError arm answers instead and
    is equally the point; both are asserted as one, because which of the two
    fires is a fact about the runner rather than about the code.
    """
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).returncode == 0
    except OSError:
        # No git on this runner. tracked_paths then answers through its OSError
        # arm, which is the same third state this control is about, so the
        # assertions below still hold and there is nothing to skip.
        inside = False
    if inside:
        pytest.skip(
            "this runner's tmp_path ({}) is inside a git work tree, so the "
            "refusal this control needs cannot be produced here; the "
            "enumeration's problem arm went untested".format(tmp_path)
        )
    paths, problem = tracked_paths(tmp_path, ("commands",))
    assert paths == []
    assert problem, (
        "git answered nothing usable and the census reported no problem -- "
        "so an empty census would have read as a complete one"
    )


def test_the_census_enumeration_returns_no_problem_on_a_real_repository():
    """The must-not-fire half of the pair above: without it, a `tracked_paths`
    that reported a problem unconditionally would satisfy the control.
    """
    paths, problem = tracked_paths(REPO_ROOT, ("commands",))
    assert problem is None
    assert any(path.name == "changelog.md" for path in paths)


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


# --- #348: a second, unrelated producer/consumer pair, same machinery -----
#
# `check_oss_workspace_launcher` fell through a bare `else` for the one state
# (`mismatched`) it had not given a named arm, and that `else` unpacked a
# 3-tuple unconditionally -- so a future seventh state would raise rather
# than being reported, which is exactly the failure `test_every_enforced_
# consumer_names_every_gate_state` above exists to catch for the OTHER
# contract. This is the same derive-the-states check, pointed at a second
# pair, so the next state a future change adds to
# `oss_workspace_launcher_state` reddens this suite instead of reaching a
# runtime unpack three frames from wherever it was added.


def test_the_launcher_producer_declares_a_multi_state_contract():
    """The derivation's own third state, mirrored for the second pair: if
    this file cannot read states out of `oss_workspace_launcher_state`, the
    exhaustiveness check below would pass vacuously.
    """
    text = _doc(LAUNCHER_PRODUCER)
    try:
        states = producer_states(text, LAUNCHER_PRODUCER_FUNCTION)
    except LookupError as exc:
        pytest.fail("{}: {}".format(LAUNCHER_PRODUCER, exc))
    assert len(states) >= 2, (
        "read only {!r} out of `def {}` in {} -- a one-state contract needs "
        "no join, so this is far more likely to be an extraction that "
        "stopped working than a contract that collapsed".format(
            sorted(states), LAUNCHER_PRODUCER_FUNCTION, LAUNCHER_PRODUCER
        )
    )
    assert "mismatched" in states, (
        "the state #348 is about is gone from the producer; if it was "
        "renamed, rename it in the consumer too"
    )


def test_the_launcher_consumer_names_every_producer_state():
    """The exhaustiveness check itself. Scoped to the consumer FUNCTION's own
    body, not the whole file -- `scripts/doctor.py`'s docstrings already
    quote every state by name (that is how #348 was written up), so a
    whole-file search would pass even with the bare `else` this test exists
    to catch.
    """
    text = _doc(LAUNCHER_PRODUCER)
    states = producer_states(text, LAUNCHER_PRODUCER_FUNCTION)
    try:
        consumer_body = _function_body(text, LAUNCHER_CONSUMER_FUNCTION)
    except LookupError as exc:
        pytest.fail("{}: {}".format(LAUNCHER_CONSUMER_FUNCTION, exc))
    unnamed = states_unnamed_by(consumer_body, states)
    assert not unnamed, (
        "`{}` in {} has no named arm for {} -- the producer `{}` returns {}. "
        "A state reaching an unnamed catch-all that unpacks another state's "
        "`detail` shape raises instead of being reported, which breaks "
        "`exit 0 always, one VERDICT line`.".format(
            LAUNCHER_CONSUMER_FUNCTION,
            LAUNCHER_PRODUCER.relative_to(REPO_ROOT),
            sorted(unnamed),
            LAUNCHER_PRODUCER_FUNCTION,
            sorted(states),
        )
    )


def test_the_launcher_consumer_check_would_fire_on_a_state_missing_its_arm():
    """The must-fire half the check above needs a control for: without this,
    a `states_unnamed_by` call that always returned empty would satisfy the
    assertion above regardless of what the consumer actually names.
    """
    states = {"matched", "mismatched", "a-state-with-no-arm"}
    body = 'if state == "matched":\n    pass\nelif state == "mismatched":\n    pass\n'
    unnamed = states_unnamed_by(body, states)
    assert unnamed == {"a-state-with-no-arm"}, unnamed
