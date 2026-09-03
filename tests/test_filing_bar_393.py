"""#393: the filing bar and the three receipts must exist in the documents that route findings.

The defect: every ``report-for-filing`` item had exactly one receipt -- a new issue -- and the
manager skill never consumed the clusters the triager is required to propose. So one defect class
became seven sibling issues and the board grew at ~25 rows a day with nothing in the loop able to
say no.

These are prose contracts, so the test holds the *routing vocabulary* both documents must share,
paired positive/negative per the repo rule: every "must not appear" sits beside a "must appear"
in the same document, so a vanished file cannot pass the negative half by accident.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from developer_docs import DeveloperBrief  # noqa: E402
from manager_docs import ManagerLoop  # noqa: E402

#: The manager loop's whole prose -- SKILL.md plus every phase file it defers
#: to. The checks below ask "does the loop say X", never "does one file say
#: X"; pinned to the spine alone they would have gone quietly narrower than
#: their own subject the moment a paragraph moved into a phase file.
SKILL = ManagerLoop(REPO_ROOT)
DEVELOPER = DeveloperBrief()  # spine + agents/developer/*.md (#939)
AUDITOR = REPO_ROOT / "agents" / "auditor.md"
TRIAGER = REPO_ROOT / "agents" / "triager.md"


def _text(path):
    return path.read_text(encoding="utf-8")


class TestThreeReceipts:
    """SKILL.md's report-for-filing contract names three receipts, not one."""

    def test_positive_control_section_exists(self):
        assert "report-for-filing" in _text(SKILL)

    def test_new_issue_route_named(self):
        assert "**a new issue**" in _text(SKILL)

    def test_class_issue_route_named(self):
        assert "**a comment on the class issue**" in _text(SKILL)

    def test_below_bar_route_named(self):
        assert "**a line in the pull request**" in _text(SKILL)

    def test_single_receipt_sentence_gone(self):
        # The old contract: "the issue you open is the receipt" -- one receipt, always an issue.
        # Positive control is test_positive_control_section_exists above: the section still exists,
        # so this negative cannot pass by the file having been emptied.
        assert "the issue you open is the receipt" not in _text(SKILL)


class TestBarIsDefined:
    """The intake section defines the bar instead of gesturing at one."""

    def test_positive_control_intake_section_exists(self):
        assert "Raising the bar on what counts as a finding is not throttling" in _text(SKILL)

    def test_bar_definition_present(self):
        assert "The bar, stated so it can be applied" in _text(SKILL)

    def test_class_issue_shape_present(self):
        assert "One class, one issue" in _text(SKILL)


class TestClustersAreConsumed:
    """The triager proposes clusters; the manager skill must be the consumer."""

    def test_positive_control_triager_still_proposes_only(self):
        assert "Propose only" in _text(TRIAGER)

    def test_skill_reads_proposed_clusters(self):
        assert "proposed cluster" in _text(SKILL)


class TestAgentsRouteClassInstances:
    """The two finding-producing agents route an already-filed class to its issue."""

    def test_developer_names_class_issue_in_reason(self):
        assert "class the tracker already carries" in _text(DEVELOPER)

    def test_auditor_filing_suggestion_checks_tracker(self):
        assert "already carries the class" in _text(AUDITOR)
