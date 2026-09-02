"""#880: a tick performs exactly one dispatch. A lane that comes back red, or
whose base moves under it, is resumed via its own agent -- never re-dispatched
fresh at the same issue -- unless that agent is genuinely gone, which is its
own named third state (`agent-unreachable`), distinct from an ordinary
`resumed`.

The rule has to be stated in all three places #880 names: the dispatch phase
file (the argument), `agents/sub-manager.md` (the form the sub-manager reads
it in), and `commands/tick.md` step 5 (where a reader would otherwise assume
dispatch can happen more than once). Every assertion below is paired with a
negative control on a fixture string, per this repo's own rule that a
"must fire" needs a "must not fire" beside it -- a pattern that matches
everything checks nothing.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


DISPATCH = (REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md").read_text(encoding="utf-8")
SUB_MANAGER = (REPO_ROOT / "agents" / "sub-manager.md").read_text(encoding="utf-8")
TICK = (REPO_ROOT / "commands" / "tick.md").read_text(encoding="utf-8")

DOCS = {
    "skills/manager/phases/dispatch.md": DISPATCH,
    "agents/sub-manager.md": SUB_MANAGER,
    "commands/tick.md": TICK,
}

# --------------------------------------------------------- positive controls


def test_every_document_states_one_dispatch_per_tick():
    """Each of the three files #880 names must say a tick dispatches once."""
    pattern = re.compile(r"one dispatch", re.IGNORECASE)
    missing = [name for name, text in DOCS.items() if not pattern.search(text)]
    assert not missing, "these files do not state the one-dispatch rule: {0}".format(missing)


def test_every_document_states_resume_over_redispatch():
    """Each document must name resuming the lane's own agent as the remedy for
    a red lane or a moved base, not a fresh spawn."""
    pattern = re.compile(r"resum\w*.{0,400}re-dispatch|re-dispatch\w*.{0,400}resum", re.IGNORECASE | re.DOTALL)
    missing = [name for name, text in DOCS.items() if not pattern.search(text)]
    assert not missing, "these files do not pair resume against re-dispatch: {0}".format(missing)


def test_every_document_names_sendmessage_as_the_resume_mechanism():
    missing = [name for name, text in DOCS.items() if "SendMessage" not in text]
    assert not missing, "these files never name SendMessage as the resume mechanism: {0}".format(missing)


def test_every_document_names_the_agent_unreachable_third_state():
    """A lane's own agent can genuinely be gone -- that is a real third state,
    not a silent re-dispatch, and #880 asks for it to be named."""
    missing = [name for name, text in DOCS.items() if "agent-unreachable" not in text]
    assert not missing, "these files never name the agent-unreachable state: {0}".format(missing)


def test_every_document_cites_880():
    missing = [name for name, text in DOCS.items() if "#880" not in text]
    assert not missing, "these files never cite #880: {0}".format(missing)


def test_dispatch_md_carries_the_full_argument_not_only_a_pointer():
    """dispatch.md is where the argument lives; the other two point at it
    rather than re-deriving it -- so dispatch.md alone should carry the cost
    comparison (#695, token figures) that makes the rule more than an
    assertion."""
    assert "#695" in DISPATCH
    assert re.search(r"\b\d+k[- ]\d+k\b", DISPATCH) or "150k" in DISPATCH


def test_sub_manager_and_tick_point_at_dispatch_md_rather_than_duplicate_it():
    """The two shorter documents should point at dispatch.md for the full
    argument rather than re-typing it -- checked as a citation of the file,
    not as a hand-count of words, per this repo's own parity-against-source
    reasoning (test_write_route_fact_parity_673.py)."""
    for name, text in (("agents/sub-manager.md", SUB_MANAGER), ("commands/tick.md", TICK)):
        assert "skills/manager/phases/dispatch.md" in text, (
            "{0} does not point at dispatch.md for the full argument".format(name)
        )


# --------------------------------------------------------- negative controls


def test_fixture_with_no_rule_does_not_match_one_dispatch_pattern():
    """The positive control's opposite: unrelated prose must not accidentally
    satisfy the pattern, or the check above proves nothing."""
    fixture = "This section describes how to review a pull request and merge it on green."
    assert not re.search(r"one dispatch", fixture, re.IGNORECASE)


def test_fixture_with_no_rule_does_not_match_resume_pattern():
    fixture = "Dispatch developer and triager agents; review their diffs before merging."
    pattern = re.compile(r"resum\w*.{0,400}re-dispatch|re-dispatch\w*.{0,400}resum", re.IGNORECASE | re.DOTALL)
    assert not pattern.search(fixture)


def test_fixture_with_no_rule_does_not_name_agent_unreachable():
    fixture = "A lane that finishes cleanly needs nothing further from the tick."
    assert "agent-unreachable" not in fixture


def test_fixture_with_no_rule_does_not_cite_880():
    fixture = "See #866 for the declined-dispatch citation rule."
    assert "#880" not in fixture
