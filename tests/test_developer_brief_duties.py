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

The negative control is PRIOR: the four passages of the document this change
amends, as they stood before it. Every anchor added here is asserted absent
from it, because an anchor that already matched the wording on disk is a guard
with no teeth, and five of those have shipped in this repository already. PRIOR
is paired with LIVE_BEFORE -- wording that was on disk before this change and is
still on disk now -- so that an empty, truncated or mis-read PRIOR fails loudly
instead of satisfying every "must not match" assertion for the wrong reason.

**PRIOR is abridged, and that is the one thing to know before adding an anchor
to it.** Three of the four passages are elided in the middle: the cross-platform
one drops the cp1252/`UnicodeEncodeError` sentence, the review one drops the
`did not run` clause, and the report-format one drops the schema path and the
arrow mappings. Every anchor this file ships today was checked against the whole
pre-change blob (`git show <commit>~1:agents/developer.md`) and none of them
falls in an elided span. An anchor added later that does fall in one would be
asserted absent from text that never contained it, and would report as red-before
while being green-before on disk -- which is this repository's own defect class
aimed at the control that exists to prevent it. Check a new anchor against the
blob, not against PRIOR.
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

# The review passage as it stood on disk before #200, un-elided. The three
# passages above are abridged; this one is not, and must not become so -- every
# anchor in EMPTY_RETURN_POLICY falls inside it, so an elision here would assert
# an anchor absent from text that never carried it.
PRIOR_REVIEW_RETURN = """
**Your final message is the only thing that reaches you -- everything a spawn wrote before that line
is invisible to the caller.** State this in both briefs: the final message IS the return value, and
if a reviewer found nothing it must say `NO FINDINGS` and name what it checked, because a reply
ending in "findings reported above" returns empty, and an empty return is indistinguishable from a
clean one unless the brief forces the reviewer to say which it means.

**Independence lives in the reviewer; judgment stays with you.** Argue down a finding that is wrong
and say why -- that is an outcome no bounce-and-repush loop produces. Report all three under
`review.findings`, each with its disposition: what it flagged, what you fixed, what you refused.

**Do not shell out to a headless `claude` CLI.** One agent did, unbounded, with auto-accepted write
access to files it was mid-edit on. If a capability is genuinely unreachable, say so and stop.

**A review that did not execute must never render as a review that found nothing.** That holds for
both spawns, for an empty final message from either one -- treat it as `did not run`, never as
clean, and say so in your own report rather than silently omitting the review -- and for each of the
auditor's classes separately: report `did not run` where it did not run. An absence you produced is
not an absence in the world.
"""

# The report-validation step exactly as it stood on disk before #212, un-elided.
# Every anchor in VALIDATOR_SKEW_POLICY falls inside this span, so an elision here
# would assert an anchor absent from text that never carried it. It is quoted from
# `git show 584509c:agents/developer.md` -- the two numbered steps around the fenced
# command, plus the sentence that follows the fence, because that is the whole of
# what the document said about which validator to run: it named one, and said
# nothing about there being a second. Em dashes are transcribed as `--`, the same
# convention PRIOR and PRIOR_REVIEW_RETURN above already use, so this is not a
# byte-exact copy; no anchor below spans one, and `_flatten` does not fold dashes,
# so an anchor that did span one would report red-before while being green-before
# on disk. Check a new anchor against the blob, not against this constant.
PRIOR_REPORT_VALIDATION = """
2. Validate it before you hand it over. A report that does not validate is not a report:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py" <path>
   ```

3. Reply with the absolute path and **at most two lines** -- the same sentence you put in `summary`,
   plus anything that genuinely cannot wait a turn: a permission block, a refusal you expect an
   argument about.

The fields, their enumerations and a worked example are in
`${CLAUDE_PLUGIN_ROOT}/schemas/agent-report.schema.json`. Read it once; it carries the descriptions
this section would otherwise duplicate and drift from.
"""

# Wording that was on disk before this change and is still on disk after it.
# If PRIOR cannot be read, these fail -- which is what stops the "must not
# match" assertions above from passing vacuously.
LIVE_BEFORE = [
    "a literal block processes no escapes",
    "cross-platform is not your machine",
    "an absence you produced is not an absence in the world",
    "an empty return is indistinguishable from a clean one",
    "a report that does not validate is not a report",
]


def _prior():
    """Every pre-change passage this file controls against, as one blob."""
    return PRIOR + PRIOR_REVIEW_RETURN + PRIOR_REPORT_VALIDATION


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
    assert _unmet(_prior(), LIVE_BEFORE) == [], "PRIOR is not the pre-change document"
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
    "sweep the rest of that file for the class",
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

# #200: a spawn that executes and returns an empty final message. The brief
# already covered a spawn that never ran and a spawn whose name did not resolve.
# It did not cover the quiet one, and an honest report of it was byte-identical
# to a clean review.
EMPTY_RETURN_POLICY = [
    "returned-nothing",
    "consume its budget, and return an empty final message",
    "one fresh re-spawn, and it does not erase the first outcome",
    "granting `sendmessage` to ask the reviewer to repeat itself",
    "two samples is not a measurement",
]

# #212: `${CLAUDE_PLUGIN_ROOT}` resolves to the installed plugin cache, which is a
# different tree from the clone the report was written in. Measured on this machine:
# the cache at 0.3.0 refuses a report the clone at 0.4.0 calls `ok`, with
# `<report>: unknown key 'docs'` -- and the refusal reads as a finding about the
# report. The brief documented exactly one validator, so an agent that ran it had no
# way to see that a second answer existed.
#
# The anchors are the decisions the fix has to state, not its wording:
#   - that there are two validators and the question of which one is real;
#   - that both are run when both exist, rather than one being chosen silently;
#   - that a disagreement is named as skew rather than absorbed into the report;
#   - the identifier for "this clone is the plugin", which is stricter than "a file
#     of that name exists here" on purpose;
#   - and the third state, for when neither copy could be run at all.
VALIDATOR_SKEW_POLICY = [
    "which validator is a question with two answers",
    "run both when both exist",
    "that is schema skew",
    "a coincidence of filename is not a claim of authorship",
    "do not edit the report to satisfy the copy that refuses it",
    "neither copy ran",
]

# #254: `filed` was a review-finding disposition, and the word is past tense.
# Read at the speed a maintainer reads a report it says *this has been filed*;
# it meant *this should be filed, by you*. Twice in one day it meant nobody
# filed it. The brief has to say which of the two an agent is writing, and that
# an agent never does the filing itself -- otherwise the vocabulary changes in
# the schema and the document that teaches it keeps teaching the old reading.
FILING_IS_A_REQUEST = [
    "a disposition is not a filing",
    "`report-for-filing` is a request addressed to the maintainer",
    "you never file it yourself",
]

DUTIES = [
    pytest.param(ADJACENT_POLICY, id="adjacent-fix-or-file"),
    pytest.param(FILING_IS_A_REQUEST, id="a-filing-disposition-is-a-request"),
    pytest.param(PLATFORM_FIX_RULES, id="platform-rules-about-the-fix"),
    pytest.param(THIRD_STATE_AS_DESIGN, id="third-state-as-a-design-rule"),
    pytest.param(PAYLOAD_NOT_EVALUATED, id="payload-parsed-never-evaluated"),
    pytest.param(EMPTY_RETURN_POLICY, id="a-spawn-that-returned-nothing"),
    pytest.param(VALIDATOR_SKEW_POLICY, id="cache-vs-clone-validator-skew"),
]


@pytest.mark.parametrize("anchors", DUTIES)
def test_the_duty_is_stated_in_the_brief(anchors):
    assert _unmet(DEVELOPER.read_text(encoding="utf-8"), anchors) == []


@pytest.mark.parametrize("anchors", DUTIES)
def test_the_anchors_were_red_against_the_pre_change_wording(anchors):
    """The must-not-fire half. An anchor matching PRIOR is one that would have
    passed before a word of this change was written.
    """
    matched = [anchor for anchor in anchors if anchor in _flatten(_prior())]
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
    assert text.count("\n5. **") == 1, (
        "more than one `5. **` marker: the slice below would bound section 4 at the "
        "wrong one and truncate it, and this test would then fail without naming why"
    )
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


def test_the_validation_step_still_names_the_plugin_rooted_command():
    """The must-fire half of the skew pair, and the reason it is not redundant.

    Everything in VALIDATOR_SKEW_POLICY is about *not* trusting the cache blindly,
    and every one of those anchors would still pass on a document that had deleted
    the `${CLAUDE_PLUGIN_ROOT}` invocation outright. That would be the wrong fix: in
    a managed repository the cache is the only validator there is, and a brief that
    told the agent to run `./scripts/report_schema.py` there would name a path that
    does not exist. So both spellings have to survive the change -- the plugin-rooted
    one because it is the only one a managed repo has, the local one because without
    it there is no second answer and no skew to observe.
    """
    text = DEVELOPER.read_text(encoding="utf-8")
    assert '"${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py"' in text, (
        "the brief no longer names the plugin-rooted validator, which is the only "
        "one a managed repository has"
    )
    assert "./scripts/report_schema.py" in text, (
        "the brief names no local validator, so the skew it describes cannot be observed"
    )


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
