"""#411: the third receipt has a name, and the three documents that use it agree on which.

#393 gave a ``report-for-filing`` item three receipts -- a new issue, a comment on the class
issue, or a named line in the pull request. The report schema encoded two outcomes, so a lane
that correctly decided "below the bar, this goes in the pull request body" had to spell it
``report-for-filing`` and put the disclaimer in prose. The maintainer read the label first and
nearly filed it.

That is #254 with the labels swapped. ``filed`` was removed because past tense reads as *done*;
``report-for-filing`` misreads here because it reads as *do this*. ``below-bar`` is neither: it
has no verb and no tense, so it names where the finding sits relative to the intake bar rather
than an act anybody is being asked to perform or being told was performed.

These are prose contracts joined to a machine-readable one, so every check below is a join --
the value the documents name has to be a value the schema accepts -- and every "must appear"
sits beside a control that fires on the wording it replaced.
"""

import json
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
SCHEMA = REPO_ROOT / "schemas" / "agent-report.schema.json"

VALUE = "below-bar"
ANCHOR_FIELD = "pr_anchor"

DOCUMENTS = (("skills/manager/SKILL.md", SKILL), ("agents/developer.md", DEVELOPER))


def _text(path):
    return path.read_text(encoding="utf-8")


def _schema():
    return json.loads(_text(SCHEMA))


def _third_receipt_unmet(text):
    """What a document is missing before it can route the third receipt.

    Both halves are load-bearing and neither implies the other: the value is what a
    maintainer reads in the report, and the anchor is the only reason the claim behind
    it is checked rather than promised. A document naming one and not the other sends
    an agent to write an item the validator refuses.
    """
    missing = []
    if VALUE not in text:
        missing.append("the value `{}` the third receipt is recorded under".format(VALUE))
    if ANCHOR_FIELD not in text:
        missing.append(
            "`{}`, the quoted fragment that makes the pull-request receipt "
            "checkable".format(ANCHOR_FIELD)
        )
    return missing


def test_the_documents_that_route_findings_exist():
    """A vanished file would pass every "not in" below for the wrong reason."""
    for name, path in DOCUMENTS:
        assert path.is_file(), "{} is gone; the checks below would be vacuous".format(name)
    assert SCHEMA.is_file()


def test_both_documents_name_the_value_the_third_receipt_is_recorded_under():
    offenders = []
    for name, path in DOCUMENTS:
        for missing in _third_receipt_unmet(_text(path)):
            offenders.append("{}: does not name {}".format(name, missing))
    assert not offenders, (
        "The filing bar defines three receipts. A document that names only two leaves an "
        "agent spelling the third as `report-for-filing`, which is the label the maintainer "
        "reads as *file this*:\n  " + "\n  ".join(offenders)
    )


def test_the_check_fires_on_the_pre_411_wording():
    """Must-fire control, paired with the must-not-fire above.

    The real documents before this change said `report-for-filing` and nothing else. If
    `_third_receipt_unmet` returned nothing for that text it would return nothing for
    anything, and the test above would pass against every document ever written.
    """
    before = (
        "You will find defects nobody filed. Both answers are legitimate and your report "
        "records which one you took -- `action` is `fixed` or `report-for-filing`."
    )
    assert len(_third_receipt_unmet(before)) == 2, (
        "the pre-411 wording is not reported as missing both halves, so the check above "
        "cannot fail"
    )


def test_a_document_stating_both_halves_is_not_reported():
    """The other direction: the check must not demand a spelling nobody uses."""
    after = (
        "Below the bar and recorded in the pull request body instead: `below-bar`, with a "
        "`pr_anchor` quoting the line of the body that carries it."
    )
    assert _third_receipt_unmet(after) == []


def test_the_schema_accepts_the_value_the_documents_name():
    """The join. Prose and schema drifting apart is what #411 is, one layer up.

    Both surveys, because both record the same act: `adjacent` is what the agent found on
    its own and `review.findings` is what a spawn handed it, and a finding is below the bar
    or not regardless of who noticed it.
    """
    schema = _schema()
    actions = schema["$defs"]["adjacent"]["properties"]["action"]["enum"]
    dispositions = schema["$defs"]["finding"]["properties"]["disposition"]["enum"]
    assert VALUE in actions, "adjacent.action cannot spell the third receipt"
    assert VALUE in dispositions, "finding.disposition cannot spell the third receipt"


def test_the_value_reads_as_neither_an_instruction_nor_a_completed_act():
    """The naming judgment, pinned so a later rename has to re-take it.

    `filed` failed by being past tense (#254): a maintainer scanning states reads it as
    done. `report-for-filing` fails here by being an imperative: the same maintainer reads
    it as a job. Both failures are a *verb* being attributed -- to the agent in the first
    case, to the reader in the second. The value carries no verb, so there is nothing to
    attribute; it states where the finding sits, and where it sits is what the maintainer
    is being asked not to overturn silently.
    """
    for spelling in ("filed", "file-in-pr", "note-in-pr", "put-in-pr", "report-in-pr"):
        assert spelling != VALUE, (
            "{!r} names an act somebody performs or performed, which is the reading "
            "failure both previous values had".format(spelling)
        )
    dispositions = _schema()["$defs"]["finding"]["properties"]["disposition"]["enum"]
    assert "filed" not in dispositions
