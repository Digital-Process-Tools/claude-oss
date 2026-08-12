"""Repo description and topics.

Empty on every new repo by default, which is why nobody notices: an absence that looks
exactly like every other new repo. They are also the only thing a person sees before
deciding whether to click.

The rule under all of these: report what is missing, suggest nothing. A generated
description is written in the voice of a tool that has not read the code, and a guessed
topic list is how a repo ends up tagged for something it does not do.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


def _fields(findings):
    return {f["field"] for f in findings}


def test_a_repo_with_both_is_clean():
    findings = scaffold.check_metadata(
        {"description": "Batched file operations for autonomous runs.", "topics": ["a", "b", "c"]}
    )
    assert findings == []


def test_a_missing_description_is_reported():
    findings = scaffold.check_metadata({"description": "", "topics": ["a", "b", "c"]})
    assert _fields(findings) == {"description"}
    assert findings[0]["state"] == "missing"


def test_a_whitespace_description_counts_as_missing():
    findings = scaffold.check_metadata({"description": "   ", "topics": ["a", "b", "c"]})
    assert findings[0]["state"] == "missing"


def test_an_absent_description_key_counts_as_missing():
    """The forge omits the key rather than sending null, and an omission read as
    'nothing to report' is the defect this whole plugin is about.
    """
    assert _fields(scaffold.check_metadata({"topics": ["a", "b", "c"]})) == {"description"}


def test_an_over_long_description_is_reported_as_truncated_not_missing():
    findings = scaffold.check_metadata(
        {"description": "x" * (scaffold.MAX_DESCRIPTION + 1), "topics": ["a", "b", "c"]}
    )
    assert findings[0]["state"] == "too-long"


def test_missing_topics_are_reported():
    findings = scaffold.check_metadata({"description": "ok", "topics": []})
    assert _fields(findings) == {"topics"}
    assert findings[0]["state"] == "missing"


def test_thin_topics_are_reported_separately_from_missing_ones():
    """One topic is a different problem from no topics, and the fix differs."""
    findings = scaffold.check_metadata({"description": "ok", "topics": ["solo"]})
    assert findings[0]["state"] == "thin"


def test_empty_strings_do_not_count_as_topics():
    findings = scaffold.check_metadata({"description": "ok", "topics": ["", "  "]})
    assert findings[0]["state"] == "missing"


def test_both_missing_are_reported_together():
    findings = scaffold.check_metadata({})
    assert _fields(findings) == {"description", "topics"}


def test_every_finding_names_the_command_that_fixes_it():
    """A finding that does not say what to do next gets read and not acted on."""
    for finding in scaffold.check_metadata({}):
        assert "gh repo edit" in finding["detail"]


def test_nothing_is_ever_suggested():
    """No finding proposes a description or a topic. Confirming the absence of a
    behaviour needs the assertion to be about content, not about a flag.
    """
    for finding in scaffold.check_metadata({}):
        assert "suggest" not in finding["detail"].lower()
        assert finding.get("suggested") is None
