"""A test run's verdict is never delegated to a spawned agent (#874).

Observed live in the fleet: a developer lane handed the full test suite to an
`Explore` agent and reported the summary that came back, rather than the
run's own output. `Explore` is a read-only search agent whose whole value is
compression -- it reads excerpts and returns a conclusion, not a file dump --
so a suite that never finished, one that finished red and was described
charitably, and one that genuinely passed all three render as the identical
confident sentence. That is this repository's own defect class
(`CLAUDE.md`'s "An absence produced by the tool, read as an absence in the
world"), one level down, with a spawned agent standing in for the tool that
produced the absence.

The behavioural half is not enforceable from here, and the issue says so in
as many words: nothing in this repository can stop an agent from spawning
another and believing what it says. `tests/test_agent_grant_is_total.py` is
the precedent for that shape -- it guards the honest advisory rather than
pretending to enforce a boundary supertool alone can hold. This module is the
same instrument pointed at a narrower claim: the rule is stated in
`agents/developer.md`, in the place a lane reads it, and it names the three
things #874's own "Test shape" section asks for -- what a lane runs, what it
does not, and what a spawned agent may not be asked for.

Each check carries a negative control: a fixture built by deleting the exact
sentence under test proves the assertion would fail on prose that lacks it,
so a check that passes on an unrelated file is not mistaken for one that
verified anything.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVELOPER = REPO_ROOT / "agents" / "developer.md"


def _text():
    return DEVELOPER.read_text(encoding="utf-8")


def test_developer_md_exists():
    assert DEVELOPER.exists(), "agents/developer.md is missing -- every check below would vacuously pass"


def test_a_delegated_test_run_verdict_is_never_treated_as_a_receipt():
    """The rule this issue asks for: the run itself happens in the lane's own
    transcript, never as a sentence handed back by a spawned agent."""
    text = _text()
    assert "verdict is never delegated" in text, (
        "agents/developer.md does not state that a test run's verdict is "
        "never delegated to a spawned agent (#874)"
    )
    # Negative control: the identical file with that one sentence removed
    # must fail the same assertion, or the check is not testing anything.
    without_it = text.replace(
        "**A test run's verdict is never delegated (#874).**", ""
    )
    assert without_it != text, "fixture construction did not remove the sentence -- control is void"
    assert "verdict is never delegated" not in without_it


def test_names_what_a_spawned_agent_may_not_be_asked_for():
    """A spawned agent may locate or explain a failure, never run the suite
    and report the verdict as though it were a receipt."""
    text = _text()
    assert "may locate a failing test" in text and "explain one" in text, (
        "agents/developer.md does not name what a spawned agent may still "
        "be asked for (locate/explain), only what it may not (#874)"
    )
    without_it = text.replace(
        "A spawned agent may locate a failing test,\n   explain one, or review a diff", "<removed>"
    )
    assert without_it != text, "fixture construction did not remove the target text -- control is void"


def test_explains_why_explore_specifically_is_the_wrong_shape():
    """The issue's first defect: `Explore` summarises by design, so its
    return is a claim rather than a receipt -- this must be said, not just
    implied by the ban on delegation."""
    text = _text()
    assert "summary written by an agent whose job is to summarise" in text, (
        "agents/developer.md does not explain why a summarising agent's "
        "test-run report is a claim rather than a receipt (#874)"
    )
    without_it = text.replace(
        "a summary written by an agent whose job is to summarise", "a summary"
    )
    assert without_it != text, "fixture construction did not remove the target text -- control is void"
    assert "summary written by an agent whose job is to summarise" not in without_it


def test_states_the_enforceability_limit_rather_than_implying_it():
    """#874 is explicit: this rule is advice with a receipt, the same
    standing as tests/test_agent_grant_is_total.py's subject. A version of
    this rule that omits that limit overstates what a content check can do."""
    text = _text()
    assert "test_agent_grant_is_total.py" in text.split("verdict is never delegated")[1][:2000], (
        "agents/developer.md's delegated-test-run rule does not point at "
        "the precedent for its own unenforceability (#874)"
    )


def test_full_suite_guidance_is_not_duplicated_or_contradicted():
    """This rule is about *where* a run happens, not a second, competing
    statement of *what* runs. The existing '#765' guidance (narrowed, never
    the whole test_command) must still be the only place that scope is set."""
    text = _text()
    assert text.count("Do not run the repo's whole `test_command` (#765)") == 1
    # The new rule references but does not restate the scope rule -- it
    # should not itself contain a second `test_command` scoping sentence.
    section_start = text.index("verdict is never delegated")
    section_end = text.index("No narration turn")
    section = text[section_start:section_end]
    assert "Do not run the repo's whole" not in section, (
        "the delegated-test-run rule restates the test_command scoping "
        "rule's imperative instead of pointing at it -- two documents "
        "drifting is #673's own class"
    )
