"""No file under tests/ states pyyaml is unavailable while the pytest job installs it.

#312: seven test files justified reading `.github/workflows/*.yml` as text with the same
sentence -- pyyaml is not a dependency of this repo. #303/#311 (`460fe90`) added `pyyaml`
to the pytest job's own `pip install` line so `test_shell_leg_budget_303.py` could parse
that job's `run:` body instead of matching it with a regex. The reason went false at that
commit; none of the seven files were touched, because the implementer who made it false
was not the one who wrote it.

This does not assert pyyaml is unavailable in general -- an absent package is a true fact
on plenty of machines. It asserts the specific sentence a maintainer would read as a
design justification does not appear while the workflow that actually runs these tests
installs the package that sentence claims is missing. `test_shell_leg_budget_303.py`
itself is not caught by this: it says pyyaml may be absent *locally* and names the
workflow as the place it is installed, which is true and is not the sentence #312 is
about.

Read the `pip install` line out of the workflow itself rather than hardcode "yes it is
installed", so a later revert of #311 makes this test go quiet instead of lying about a
premise that no longer holds.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

#: The stale sentence #312 is about. Deliberately not the substring `pyyaml`, or every
#: honest use of the word -- including the one two paragraphs up -- would self-match.
STALE_CLAIM = re.compile(r"pyyaml is not a dependency")


def _pytest_job_installs_pyyaml():
    """Whether the workflow's own `pip install` line names pyyaml.

    Read from the file rather than assumed true, so this test is the thing that goes
    quiet -- not silently wrong -- if #311 is ever reverted.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "pip install" in line and "pyyaml" in line:
            return True
    return False


def test_the_workflow_still_installs_pyyaml_on_the_pytest_job():
    """Positive control for the check below.

    If this goes false, `test_no_file_claims_pyyaml_is_absent_while_it_is_installed`
    below stops checking anything -- so it is asserted here rather than only assumed by
    the check that depends on it.
    """
    assert _pytest_job_installs_pyyaml(), (
        "the pytest job no longer installs pyyaml -- the check below has nothing to "
        "check against and should be revisited, not left silently vacuous"
    )


def test_the_scan_catches_a_planted_claim():
    """Positive control: prove the pattern matches the sentence it exists to catch.

    Without this, a scan that matched nothing could mean either 'the claim is gone' or
    'the pattern is wrong' -- the same rendering this repository is named after.
    """
    planted = (
        "Deliberately not a YAML parse -- pyyaml is not a dependency of this repo."
    )
    assert STALE_CLAIM.search(planted), "the control string itself should match"


def test_no_file_claims_pyyaml_is_absent_while_it_is_installed():
    """The finding #312 exists to close.

    Every `tests/*.py` file is scanned for the sentence, except this one -- it quotes
    the sentence on purpose, to test for it, and would otherwise flag itself. A hit means
    a stated design reason is false: a maintainer reading it would believe something the
    workflow it describes no longer does.
    """
    if not _pytest_job_installs_pyyaml():
        import pytest

        pytest.skip("pyyaml is not installed by the pytest job -- nothing to check yet")

    offenders = []
    for path in sorted((REPO_ROOT / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue  # this file quotes the sentence on purpose, to test for it
        text = path.read_text(encoding="utf-8")
        if STALE_CLAIM.search(text):
            offenders.append(path.name)

    assert not offenders, (
        "these files claim pyyaml is not a dependency while the pytest job installs it "
        "(see #312): " + ", ".join(offenders)
    )
