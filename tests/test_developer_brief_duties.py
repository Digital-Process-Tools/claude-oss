"""Guards on agents/developer.md's rules about *the fix*, not about the report.

Companion to test_triager_duties.py and to test_content_invariants.py, which
holds the cross-document prose guards. These are the developer brief's own, and
they share one property: each is a duty the brief already discharges when
*writing up* the work and never states as a rule for *doing* it.

Every anchor is matched against a flattened copy of the document -- lowercased,
every run of whitespace collapsed to one space -- because these documents wrap
at 100 columns and a multi-word anchor lands across a newline the moment a
paragraph is reflowed. A checker whose finding is about its own reading,
dressed as a finding about the file, is the defect this plugin is named after
pointed at the test suite.

The negative control is PRIOR: the four passages of the document as they stood
before this change, quoted from the pre-change file rather than paraphrased.
Every anchor added here is asserted absent from it, because an anchor that
already matched the wording on disk is a guard with no teeth, and five of those
have shipped in this repository already. PRIOR is paired with LIVE_BEFORE --
wording that was on disk before this change and is still on disk now -- so that
an empty, truncated or mis-read PRIOR fails loudly instead of satisfying every
"must not match" assertion for the wrong reason.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVELOPER = REPO_ROOT / "agents" / "developer.md"


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space."""
    return " ".join(text.lower().split())


def _developer():
    return _flatten(DEVELOPER.read_text(encoding="utf-8"))


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


# The passages this change amends, as they stood before it. Anything a new
# anchor matches in here is wording that was already on disk.
PRIOR = """
Use triple-single-quoted literal strings for the field values. **A literal block processes no
escapes**, so write exactly the bytes you want on disk -- doubling a backslash puts two on disk, and
that is a bug no validator will catch because the file still parses. Validators run after the write
and roll the file back on a syntax failure.

4. **Cross-platform is not your machine.** CI runs Linux, macOS and Windows. Before you report, audit
   for: path separators and suffix matches that behave differently with backslashes; a drive letter
   read as a hostname because the colon precedes the first slash; hardcoded POSIX literals in test
   assertions; platform-specific exception types, so a narrow `except` never fires; an unspawnable
   binary raising a spawn error instead of reaching its own "the tool failed" arm; and a character the
   console's codepage cannot represent. **A green local run is not evidence about the other legs.**
   Say which platform claims are **observed** and which are **reasoned**.

**A review that did not execute must never render as a review that found nothing.** That holds for
both spawns, for an empty final message from either one, and for each of the auditor's classes
separately: report `did not run` where it did not run. An absence you produced is not an absence in
the world.

The fields, their enumerations and a worked example are in the schema. What the old prose report
asked for has not changed, only where it goes: files, red and green, review, platform claims,
unfiled findings, the note path.
"""

# Wording that was on disk before this change and is still on disk after it.
# If PRIOR cannot be read, these fail -- which is what stops the "must not
# match" assertions above from passing vacuously.
LIVE_BEFORE = [
    "a literal block processes no escapes",
    "cross-platform is not your machine",
    "an absence you produced is not an absence in the world",
]


def test_the_developer_document_exists_and_is_prose():
    """Positive control. Every check below is an `in` against this file's text,
    so an empty or missing file satisfies none of them for the wrong reason --
    and a suite that could not find the document would report every duty as
    absent, which is a finding about the harness wearing the costume of a
    finding about the file.
    """
    assert DEVELOPER.is_file(), "agents/developer.md is missing"
    assert len(_developer()) > 8000, "agents/developer.md is too short to be the brief"


def test_the_negative_control_is_readable():
    """The must-fire half of the control pair.

    Every anchor added by this change is asserted absent from PRIOR. That
    assertion also passes when PRIOR is empty, truncated, or flattened by a
    function that returns nothing -- so it is paired with wording known to be
    in PRIOR and known to still be in the live document. If this fails, every
    "was red before" claim below is unsupported and must be read as `did not
    run`, not as passed.
    """
    assert _unmet(PRIOR, LIVE_BEFORE) == [], "PRIOR is not the pre-change document"
    assert _unmet(DEVELOPER.read_text(encoding="utf-8"), LIVE_BEFORE) == [], (
        "the live document lost wording the control depends on"
    )


# --- The duties themselves ------------------------------------------------

ADJACENT_POLICY = [
    "fix it or file it",
    "blast radius is still one sentence long",
    "a fix reaching into another live agent's lane is a filing, not a fix",
    "a bundled fix not called out in the report",
]

PLATFORM_FIX_RULES = [
    "makes the assertion vacuous",
    "sweep the file for the class",
]

THIRD_STATE_AS_DESIGN = [
    "what it prints when it cannot look",
    "do not trade the loud bug for the quiet one",
    "shadow a different bug on the same line",
]

PAYLOAD_NOT_EVALUATED = [
    "parsed, never evaluated",
    "put a real newline in the literal",
]

DUTIES = [
    pytest.param(ADJACENT_POLICY, id="adjacent-fix-or-file"),
    pytest.param(PLATFORM_FIX_RULES, id="platform-rules-about-the-fix"),
    pytest.param(THIRD_STATE_AS_DESIGN, id="third-state-as-a-design-rule"),
    pytest.param(PAYLOAD_NOT_EVALUATED, id="payload-parsed-never-evaluated"),
]


@pytest.mark.parametrize("anchors", DUTIES)
def test_the_duty_is_stated_in_the_brief(anchors):
    assert _unmet(DEVELOPER.read_text(encoding="utf-8"), anchors) == []


@pytest.mark.parametrize("anchors", DUTIES)
def test_the_anchors_were_red_against_the_pre_change_wording(anchors):
    """The must-not-fire half. An anchor matching PRIOR is one that would have
    passed before a word of this change was written.
    """
    matched = [anchor for anchor in anchors if anchor in _flatten(PRIOR)]
    assert matched == [], f"toothless anchors, already on disk: {matched}"


def test_the_platform_rules_about_the_fix_land_inside_section_four():
    """A producer/consumer join, not a placement preference.

    The review section instructs the agent to hand the auditor section 4
    **verbatim**, on the stated grounds that a third copy of the platform list
    would drift. So a platform rule written anywhere else in this document is a
    rule the auditor is never handed -- present in the brief, absent from the
    only reader the brief routes it to, and indistinguishable in review from a
    rule that was never written.
    """
    text = DEVELOPER.read_text(encoding="utf-8")
    start = text.find("4. **Cross-platform is not your machine.**")
    assert start != -1, "section 4 no longer opens with the wording the review section cites"
    end = text.find("\n5. **", start)
    assert end != -1, "section 4 has no following item 5 to bound it"
    section_four = text[start:end]
    assert _unmet(section_four, PLATFORM_FIX_RULES) == [], (
        "a platform rule sits outside section 4, so the auditor never receives it"
    )


def test_the_review_section_still_hands_section_four_over_verbatim():
    """The control for the test above: it bounds section 4 and asserts content
    inside it, which stays green if the instruction that makes section 4 the
    auditor's source is ever deleted. Then the join it guards would be gone and
    the guard would not say so.
    """
    assert _unmet(
        DEVELOPER.read_text(encoding="utf-8"),
        ["hand it §4 above", "verbatim in the brief"],
    ) == []


def test_the_adjacent_policy_matches_the_vocabulary_the_schema_enforces():
    """The policy tells the agent when to fix and when to file. The schema is
    what records the answer, so the two halves have to use one vocabulary: a
    brief naming a disposition the schema refuses is a rule that cannot be
    complied with, and the failure surfaces at validation time in someone
    else's session.
    """
    import json

    schema = json.loads(
        (REPO_ROOT / "schemas" / "agent-report.schema.json").read_text(encoding="utf-8")
    )
    adjacent = schema["$defs"]["adjacent"]["properties"]
    assert set(adjacent["action"]["enum"]) == {"fixed", "report-for-filing"}
    assert "in_blast_radius" in adjacent

    brief = _developer()
    for token in ("`fixed`", "`report-for-filing`", "`in_blast_radius`"):
        assert _flatten(token) in brief, f"the brief never names {token}"
