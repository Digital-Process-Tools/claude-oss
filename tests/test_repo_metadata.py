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


def test_every_actionable_finding_names_the_command_that_fixes_it():
    """A finding that does not say what to do next gets read and not acted on. This
    covers the actionable states -- missing, thin, too-long -- where there is
    something to run. The "unknown" state is different: there is no fix to name
    because the thing itself was never determined (see the test below).
    """
    findings = scaffold.check_metadata({"description": "", "topics": []})
    assert findings, "no findings -- the check below would vacuously pass"
    for finding in findings:
        assert "gh repo edit" in finding["detail"]


def test_the_unknown_state_names_how_to_recheck_not_a_fix():
    """A probe of the wrong shape has not established that topics are missing, so the
    finding must not read like the actionable ones -- it names how to get a probe of
    the right shape, not a `gh repo edit` command for a state nobody confirmed.
    """
    finding = scaffold.check_metadata({"description": "ok"})[0]
    assert finding["state"] == "unknown"
    assert "gh repo edit" not in finding["detail"]
    assert "gh repo view" in finding["detail"]


def test_nothing_is_ever_suggested():
    """No finding proposes a description or a topic. Confirming the absence of a
    behaviour needs the assertion to be about content, not about a flag.
    """
    for finding in scaffold.check_metadata({}):
        assert "suggest" not in finding["detail"].lower()
        assert finding.get("suggested") is None


# ---------------------------------------------------------------- repositoryTopics
#
# `/oss:scaffold` tells the caller to run `gh repo view --json description,repositoryTopics`
# and feed the result straight to check_metadata. `gh` returns topics as
# `repositoryTopics: [{"name": "..."}, ...]`, not the flat string list the old tests above
# use under the `topics` key. Both shapes are accepted -- the caller should not have to
# know the internal contract, and a shape neither function understands must say so instead
# of reading as "no topics" (#8).


def test_repositoryTopics_shape_from_gh_is_read():
    probe = {
        "description": "Batched file operations for autonomous runs.",
        "repositoryTopics": [{"name": "ai"}, {"name": "claude"}, {"name": "automation"}],
    }
    assert scaffold.check_metadata(probe) == []


def test_repositoryTopics_below_minimum_is_thin_not_missing():
    probe = {"description": "ok", "repositoryTopics": [{"name": "solo"}]}
    findings = scaffold.check_metadata(probe)
    assert _fields(findings) == {"topics"}
    assert findings[0]["state"] == "thin"


def test_repositoryTopics_of_dicts_does_not_raise_attributeerror():
    """The exact reproduction from #8: renaming the key alone made check_metadata call
    .strip() on a dict and crash. It must neither crash nor report the topics as missing
    outright -- two topics is genuinely thin (MIN_TOPICS is 3), which is the correct
    answer once the crash is gone, not "missing" and not silence.
    """
    probe = {"description": "ok", "repositoryTopics": [{"name": "ai"}, {"name": "claude"}]}
    findings = scaffold.check_metadata(probe)
    assert findings[0]["state"] == "thin"


def test_a_probe_with_neither_topics_key_is_unknown_not_missing():
    """No `repositoryTopics`, no `topics` -- the probe is the wrong shape entirely, which
    is not the same fact as "this repo has zero topics". Reporting it as missing hands
    over a `gh repo edit --add-topic` command for a repo whose topics were never checked.
    """
    findings = scaffold.check_metadata({"description": "ok"})
    assert _fields(findings) == {"topics"}
    assert findings[0]["state"] == "unknown"


def test_malformed_repositoryTopics_entries_are_unknown_not_missing():
    """Entries that are neither a string nor a `{"name": ...}` object -- some shape
    nobody anticipated -- must not be silently dropped and read as a clean zero.
    """
    probe = {"description": "ok", "repositoryTopics": [1, 2, 3]}
    findings = scaffold.check_metadata(probe)
    assert _fields(findings) == {"topics"}
    assert findings[0]["state"] == "unknown"


def test_repositoryTopics_takes_precedence_over_legacy_topics_key():
    probe = {
        "description": "ok",
        "repositoryTopics": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        "topics": [],
    }
    assert scaffold.check_metadata(probe) == []

def test_the_metadata_vocabulary_is_keyed_by_field_and_state_together():
    """The control behind the registered `missing` collision (#134).

    `check_metadata` returns ONE list holding two vocabularies -- its own description
    states and whatever `_check_topics` produced -- under one `state` key. `missing`
    is in both, so a caller writing `if f["state"] == "missing"` gets two unrelated
    situations, which is the shape #134 was filed about.

    It is kept rather than renamed on one condition, and this is the condition:
    `field` is always there, so the real key is the pair. `tests/
    test_state_vocabularies.py` registers the collision with that sentence and names
    this test as what makes it true, so the sentence is not self-certifying.
    """
    findings = scaffold.check_metadata({"description": "", "topics": []})
    assert len(findings) == 2, "the collision is not reachable, so nothing below is a test"

    states = sorted(f["state"] for f in findings)
    assert states == ["missing", "missing"], (
        "the two sites no longer share a state name. If one was renamed, the "
        "MULTI_SITE_STATES entry for check_metadata:missing is now stale."
    )

    for finding in findings:
        assert finding.get("field"), (
            "a finding in this vocabulary carries no `field`, so the only thing "
            "telling its two `missing` sites apart is gone: {!r}".format(finding)
        )
    pairs = sorted((f["field"], f["state"]) for f in findings)
    assert pairs == [("description", "missing"), ("topics", "missing")]
    assert len(set(pairs)) == len(pairs), "(field, state) is not a key either"


def test_every_finding_this_vocabulary_can_emit_carries_a_field():
    """The sweep above proves it for one pair of states. This drives every reachable
    finding, so a new arm added without a `field` fails here rather than at whatever
    reads it.
    """
    probes = [
        {"description": "", "topics": []},
        {"description": "x" * (scaffold.MAX_DESCRIPTION + 1), "topics": ["solo"]},
        {"description": "ok"},
        {"description": "ok", "repositoryTopics": [7]},
    ]
    seen = set()
    for probe in probes:
        findings = scaffold.check_metadata(probe)
        assert findings, "probe {!r} produced nothing -- the loop below is vacuous".format(probe)
        for finding in findings:
            assert finding.get("field"), "no field on {!r}".format(finding)
            seen.add(finding["state"])
    assert seen == {"missing", "too-long", "thin", "unknown"}, sorted(seen)
