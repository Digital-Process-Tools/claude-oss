"""#765: a lane does not run the repository's whole ``test_command``.

Decision taken by the maintainers on 2026-09-02 and recorded in
``docs/overview.md`` as want 6. The brief used to present the full local suite
as optional-with-criteria, and the criteria were the problem rather than the
wording: a lane complying with them ran a 27m36s suite on one platform and
reported failures CI did not have as facts about the default branch. Two lanes
did it independently on one afternoon, so it is systemic.

Two bounds this must not over-reach, both asserted below rather than trusted:

* **The targeted run stays mandatory.** Red-before-fix is the one claim CI is
  structurally unable to produce, because CI only ever runs the branch as
  proposed with the fix already present. A change that removed the full run and
  weakened the targeted one would have removed the only local evidence worth
  having.
* **``tests.full``'s three states are unchanged.** #765 changes which value a
  lane should report, not what the values mean, and ``could-not-run`` must keep
  never folding into ``not-run`` -- that is #632's guarantee and this issue
  explicitly preserves it.

Python 3.9 compatible.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_budgets import repo_root  # noqa: E402


def _developer():
    return (repo_root() / "agents" / "developer.md").read_text(encoding="utf-8")


#: The sentence #765 was filed against, reduced to the claim rather than its
#: exact punctuation: the full suite offered as an option the lane weighs.
_OPTIONAL_RE = re.compile(
    r"full suite is optional|full run optional|full suite[^.]{0,40}\boptional\b",
    re.IGNORECASE,
)

#: The rebase clause, removed with the rest. Kept as its own pattern because it
#: was the one part of the old rule stated as mandatory, so a partial revert
#: would most plausibly bring this back alone.
_REBASE_RE = re.compile(r"mandatory after a rebase", re.IGNORECASE)


def test_the_brief_does_not_offer_the_full_suite_as_an_option():
    text = _developer()
    hit = _OPTIONAL_RE.search(text)
    assert hit is None, (
        "agents/developer.md still presents the full test_command as optional: "
        "{!r}".format(text[max(0, hit.start() - 60):hit.end() + 60] if hit else "")
    )


def test_the_rebase_clause_is_gone():
    """It was the strongest form of the rule, argued from three pull requests
    going red in one day. CI runs the rebased branch, so the gate is covered;
    what the local run bought was finding it earlier, which is not worth a
    suite the same document now says not to trust on one platform."""
    assert _REBASE_RE.search(_developer()) is None, (
        "the rebase clause survived, so the full local run is still mandatory "
        "in the one case the old rule was most confident about"
    )


def test_the_brief_tells_the_lane_not_to_run_it():
    """A removal is not the same as an instruction. Deleting the criteria and
    saying nothing leaves a lane to decide for itself, which is the state that
    produced two false pull request bodies."""
    text = _developer().lower()
    assert "do not run the repo's whole `test_command`" in text or (
        "do not run" in text and "test_command" in text
    ), "the brief does not tell the lane not to run the whole test_command"


def test_the_targeted_run_is_still_mandatory():
    """The bound. CI cannot produce red-before-fix, so removing the full run
    must not touch this."""
    assert "targeted run is not optional" in _developer(), (
        "the targeted run's mandatory framing was weakened alongside the full "
        "suite's removal -- CI cannot produce a red-before-fix"
    )


def test_ci_is_named_as_the_authority_rather_than_speed():
    """#765 says asserting speed would be wrong: the Windows leg ran over 30
    minutes against a 27m36s local run. The argument is breadth and
    mandatoriness, and a brief that argued speed would be making a false claim
    a lane could check."""
    text = _developer()
    assert "merge gate" in text or "authority for the whole matrix" in text, text[:0]
    assert "not faster" in text, (
        "the brief does not say CI is broader rather than faster, so a reader "
        "may infer a speed claim #765 measured as false"
    )


def test_tests_full_keeps_its_three_states():
    """#632's guarantee, which #765 preserves rather than replaces."""
    text = _developer()
    for state in ("ran", "not-run", "could-not-run"):
        assert state in text, state
    assert "never folds into" in text or "never folding into" in text, (
        "the could-not-run/not-run separation lost its statement"
    )


def test_the_expected_value_is_named():
    """A field whose meaning changed and whose expected value is unstated
    leaves the manager crediting a `ran` exactly as before."""
    text = _developer().lower()
    assert "not-run" in text and "finding" in text, text[:0]
    assert "expected value is `not-run`" in text, (
        "the brief does not say which value a lane should now report"
    )


def test_the_patterns_fire_on_the_old_wording():
    """Must-fire control. Without it, every assertion above also passes when
    the patterns stop matching anything -- an extractor that finds nothing
    reports a compliant document, which is this repository's defect class."""
    old = (
        "**The full suite is optional -- the repo's whole `test_command` -- and "
        "the criteria are the point.** Worth the wall-clock when the change is "
        "in the core, and **mandatory after a rebase onto the default branch**, "
        "without exception."
    )
    assert _OPTIONAL_RE.search(old) is not None
    assert _REBASE_RE.search(old) is not None
