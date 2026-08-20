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
to it.** *Four passages* below means the four passages bundled inside the `PRIOR`
string, not the number of `PRIOR_*` constants in the file -- there are six of
those, and the two counts used to coincide, which is the kind of coincidence that
gets read the wrong way once and then quoted. They stopped coinciding when #275
added `PRIOR_EMPTY_RETURN_SORT`, and drifted further apart when the version-4
`closes` duty added `PRIOR_PR_PAYLOAD`; the sentence is kept rather than deleted
because the reading it warns against is the one a reader arrives with. The five
constants beside `PRIOR` are un-elided and each says
so in its own comment. Three of the four passages inside `PRIOR` are elided in the middle: the cross-platform
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

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVELOPER = REPO_ROOT / "agents" / "developer.md"
PROSE = sorted((REPO_ROOT / "skills").rglob("SKILL.md")) + sorted(
    (REPO_ROOT / "agents").glob("*.md")
)

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


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

# The dependency-reporting section exactly as it stood on disk before #290,
# un-elided, because every anchor in GUEST_REPO_ROUTING falls inside this span and
# an elision would assert an anchor absent from text that never carried it. Em
# dashes are transcribed as `--`, the same convention the constants above use, so
# this is not a byte-exact copy; no anchor below spans one, and `_flatten` does not
# fold dashes, so an anchor that did span one would report red-before while being
# green-before on disk.
PRIOR_DEPENDENCY_REPORTING = """
## A defect in a declared dependency is reported, never worked around silently

You will sometimes trip over a bug that is not in this repo at all but in something the project
declares as a dependency. Routing around it and saying nothing leaves the board that owns the fix
unaware of a defect somebody has already reproduced -- and **getting it onto that tracker is part of
finishing the work**, not a favour to another project.

**You do not perform the filing.** Opening an issue on another repository is publishing, and your
publishing clause is unconditional: **do not open the upstream issue**, do not comment on one. You
hand the maintainer what they need to open it in one call, in `adjacent`, with `action` set to
`report-for-filing`:

- **which declared dependency** it is, by the name the manifest uses -- never a repo slug you
  inferred, and never a tracker you guessed at;
- **the reproduction**, the same standard as a local finding;
- **which row, and what its embargo column says.** Look the finding up in the ranking table the
  manager skill owns, and report both verdicts the row carries. **A finding whose row answers yes
  in the embargo column must not become a public issue on somebody else's tracker** -- it goes down
  the **embargo** path, meaning whatever private reporting channel that project's own security
  policy names: a security tab, a disclosure address or a form. The word *embargo* is unlikely to
  appear in the policy; read the policy. Say so in the item; the maintainer is the one who routes
  it, and this is the sentence that stops the routing being a reflex.

  **Read the embargo column, not the blocking one.** They are two questions -- what we may ship
  against whether their users are exposed while a fix is written -- and they disagree on one row.
  Do not copy the set into your report: name the row you read and the column's answer, so a change
  to the table reaches this routing instead of being outvoted by a stale list.
- **For an arbitrary third-party dependency, say that too.** Filing there is a judgement rather than
  a duty: there may be no filing rights, no relationship, and a public tracker is a disclosure
  channel. A dependency the same maintainer owns is the unambiguous case.

Three outcomes and the third is the one that gets lost: **reported** to the maintainer for filing;
**could not identify the dependency or its tracker**, said as that rather than dropped; and
**deliberately not reported**, which **is a decision with a reason** -- already fixed upstream, or
already filed -- and never something that happens because nobody decided. A defect found, judged
worth reporting, and then silently not reported reads exactly like a dependency with no defects.
"""

# The empty-return subsection exactly as it stood on disk before #275, un-elided.
# Every anchor in REFERRED_BUT_UNSTATED that lands in this subsection is asserted
# absent from it, so an elision here would assert an anchor absent from text that
# never carried it. Transcribed from `git show origin/main:agents/developer.md`
# with em dashes written as `--`, the same convention the constants above use; no
# anchor below spans one.
#
# **It is deliberately not part of `_prior()`.** `_prior()` is the control for
# every duty in DUTIES, and this constant is the document *after* #200 -- so
# folding it in would make #200's own anchors (`returned-nothing`, `consume its
# budget, ...`) match the control and report as toothless, which they are not.
# A shared control only works while every duty it controls predates all of it.
# The #275 anchors get this constant through a check of their own below.
# The pull request payload subsection exactly as it stood on disk before this
# change, un-elided, transcribed from `git show f58aed3:agents/developer.md`.
# Every anchor in CLOSING_REFERENCE_DUTY falls inside this span, so an elision
# here would assert an anchor absent from text that never carried it. Em dashes
# are transcribed as `--`, the same convention the constants above use; no
# anchor spans one.
PRIOR_PR_PAYLOAD = """
### The pull request is yours to write -- the title as much as the body

Write it to `<worktree_root>/reports/<branch>-<UTC timestamp>.pr.json` and record it under `pr_body`.
**A file the forge can consume unchanged, not a markdown body** -- JSON with four fields:

{"title": "...", "body": "...", "head": "<your branch>", "base": "<default branch>"}

Markdown is the shape the next step refuses, and the refusal lands on somebody else after your
session has ended: they read your body, wrap it, and **invent a title**. The title is the sentence
most people read, and after a squash it is the only part of the pull request that survives into the
log -- so it belongs to whoever did the work. That is not a formatting detail, it is the whole point.
The validator opens this file and checks it, including that `head` is the branch you are on.

The orchestrator hands the path to the forge; it does not re-narrate your evidence into a body of its
own. **This is the default, not something to be asked for.** You hold the evidence, so this deletes a
translation step that costs about a thousand tokens and loses detail on the way -- it does not move
judgment, because the orchestrator still reads the body before it opens anything.

If you did not write one, say so in the field with a reason. `not-written` is a state; an absent file
the orchestrator discovers later is not.
"""

PRIOR_EMPTY_RETURN_SORT = """
### When a spawn runs and comes back empty

That rule has a loud half and a quiet half, and only the loud half was ever written down. A spawn
that errors is handled below. This is the other one: a spawn can **execute, consume its budget, and
return an empty final message** -- the review happened, the conclusions are gone. Reported honestly
and structurally that is `findings: []` under `state: checked`, which is byte-identical to a clean
review, and it has already cost this repository real findings that nobody can now recover.

So it gets its own state. `review.classes` and `review.findings` carry a fourth one,
**`returned-nothing`**, that no other survey in the report can spell -- `checked` would render a real
review as a clean one, and `not-checked` claims nobody looked, which understates what is missing.
The validator refuses it without a reason.

**How you decide you are in it.** Both briefs already require a sentinel -- `NO FINDINGS`, and what
was checked -- precisely so silence is distinguishable from cleanliness. So read **the final message
you actually received** and sort it in three: it names findings; or it says `NO FINDINGS` and names
what it checked; or it is empty, whitespace-only, or says neither of those. The third is
`returned-nothing`. Do not infer a verdict from what you believe the spawn did while it ran -- you
did not see that, and a transcript you happen to hold is evidence about your own session, not a
return value.

**What the report must say, and it is a required field rather than good manners.** Set the state to
`returned-nothing` and put in `reason` which spawn came back empty and **what is lost, counted**.
Anything you can re-derive from your own context goes in `items` with disposition `open`, never
`fixed`: you are reconstructing somebody else's reading and cannot check the reconstruction. Say in
the same breath how many you could not recover at all. `returned-nothing` carrying items is the
normal shape, not a contradiction -- and `checked` is unavailable to you from the moment one spawn
comes back empty, however completely the other one answered.

**One fresh re-spawn, and it does not erase the first outcome.** Spawn a new agent of the same type
with the same brief, once, and stop there; a second empty return is a finding, not a third attempt.
Whatever the retry hands back, the state stays `returned-nothing` and the reason names both
attempts. Converting *the reviewer said nothing* into *no findings* is the bug; converting it into
*I retried and it worked, nothing to see* is the same bug one layer up.

**Decided against, so that it is a decision rather than an omission: granting `SendMessage` to ask
the reviewer to repeat itself.** That was the missing capability the agents who hit this named, and
it is still the wrong answer. It widens a delegated agent from *spawns its own reviewers* to *can
address any live agent*, including the sibling lanes working other issues in the same round; and it
does not recover the lost message anyway, because an agent asked to repeat regenerates -- what comes
back is a fresh review wearing the first one's authority. A fresh spawn buys the same thing and
says what it is.

**None of this is a finding about a particular agent type.** It was the same reviewer type both
times it was observed and the auditor half returned normally both times, but that is two
observations across two agent types, two briefs and two task shapes, and nothing separates those
three explanations. **Two samples is not a measurement**, so nothing in this subsection names an
agent type: the rule is mechanism-agnostic and applies to whatever you spawned.
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
    "getting it onto that tracker is part of",
    # From PRIOR_PR_PAYLOAD, so a mis-read of that passage fails loudly rather
    # than satisfying every CLOSING_REFERENCE_DUTY "must not match" for free.
    "`not-written` is a state; an absent file",
]

# The same pairing, for PRIOR_EMPTY_RETURN_SORT alone. It is not folded into
# LIVE_BEFORE because LIVE_BEFORE is checked against `_prior()`, which does not
# include that constant -- see the comment on it.
LIVE_BEFORE_EMPTY_RETURN = [
    "do not infer a verdict from what you believe the spawn did while it ran",
    "what is lost, counted",
]


def _prior():
    """Every pre-change passage this file controls against, as one blob."""
    return (
        PRIOR
        + PRIOR_REVIEW_RETURN
        + PRIOR_REPORT_VALIDATION
        + PRIOR_DEPENDENCY_REPORTING
        + PRIOR_PR_PAYLOAD
    )


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
    # Reworded by #275: the count moved from two to three, so the sentence that
    # refused to name an agent type had to survive a change to its own numeral.
    # The durable half is that a handful of correlated observations is not a
    # measurement, which is what the anchor now pins.
    "a handful of samples is not a measurement",
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

# #290: the loop runs as a guest inside somebody else's repository, and the
# documents covered a defect in a *declared* dependency and a defect in the host
# project's own code. The tooling running the agent is neither -- nothing declares
# itself as its own dependency -- so a defect in it had no stated destination and
# the nearest tracker wins by default.
#
# The anchors are the decisions, not the wording:
#   - that the tooling is a dependency in every way except the manifest;
#   - the ownership split, which is the sentence that stops the rule pushing only
#     one way and sending the host project's own bugs upstream;
#   - that the loop's own board is asked for rather than inferred, and the name of
#     the call that answers;
#   - and that the answers which are not a URL are not "there is no tracker" --
#     the third state, which is what #290 is actually about.
#
# Deliberately absent: the accessor's state tokens. This document names the call
# and lets the reader run it; enumerating its answers here would be a second copy
# of a fact that lives in `scripts/doctor.py`, arriving with the same authority and
# proofread by nobody. `test_the_brief_names_the_accessor_without_copying_it`
# below holds that, and derives the tokens from the accessor rather than spelling
# them, so the two cannot drift apart.
GUEST_REPO_ROUTING = [
    "in every way except the manifest",
    "the split is who owns the code, never who is standing closest",
    "do not infer a slug for it. ask",
    "`loop_repository()`",
    "do not mean there is no tracker",
]

# #275 and #296: the third failure of the return contract, and the one the sentinel
# did not cover. A spawn executes, reads the diff, forms conclusions, and hands back
# a sentence *referring* to findings it never states -- "two confirmed findings
# reported above", "findings reported above (3 total)". Not empty, so it does not
# trip the empty-return rule #200 built; not `NO FINDINGS`, so it is not clean; and
# it sounds like a delivery, which is why it is worse than a crash.
#
# Two independent populations, which is why one anchor set covers both filings:
#   - #275: three of roughly seven review spawns in one session (2026-08-16), in
#     this repository. One lost finding's only surviving trace was the name of a
#     file nobody then opened.
#   - #296: three of three developer runs in one fleet day (2026-08-18), in
#     claude-supertool, nine findings claimed and eight never recoverable.
# Same mechanism, different repositories, different diffs, different agents that
# did not know about each other -- so the shape is the mechanism, not one habit.
#
# The anchors are the decisions the fix has to state, not its wording:
#   - the sentence itself, which goes into both spawn briefs;
#   - the shape that makes the omission arithmetic rather than a judgement, so that
#     the parent compares two numbers instead of reading tone;
#   - that the caller's sort gains a fourth arm, since a message that gestures at
#     findings is `returned-nothing` however confident it sounds;
#   - that the residue -- a count, a subject, a filename -- is recorded and is not
#     the finding;
#   - that the fix is named as a request rather than sold as a boundary, which is
#     the one claim this repository has been burned by making before;
#   - and that the intervention is recorded as an experiment, because whether a
#     sentence in a brief changes a model's behaviour is not knowable from here.
REFERRED_BUT_UNSTATED = [
    "a finding you refer to but do not state is a finding that does not exist",
    "opens with `findings: <n>`",
    "and then states exactly that many findings",
    "refers to findings it does not state",
    "sort it in four",
    "record the residue, and do not mistake it for the finding",
    "this fix is a request to the spawn, not a boundary on it",
    "the brief sentence is an experiment, not a fix",
]

# Day-one gap in the version-4 report contract (#274 / PR #334, `f58aed3`).
# `pr_body.closes` became required whenever `pr_body.state` is `written`, and this
# brief -- the one every developer lane reads -- never mentioned the field, so the
# next lane through writes exactly what its brief says and is refused.
#
# The anchors are deliberately NOT the field list. The schema is the single copy of
# that and the brief already points at it; a second copy here is the restatement
# this repository keeps paying for. What the anchors pin is the half a pointer
# cannot carry -- the body has to bind the keyword, and the body is composed once,
# before any validator speaks:
#   - that the keyword must survive rendering, which is the failure mode field
#     documentation cannot prevent: four agent-written payloads across two sessions
#     bound nothing, and one of them backticked the whole line;
#   - that a shared keyword over two numbers closes only the first, so the count of
#     `Closes` lines is the count of issues;
#   - that the line goes in while the body is written, not after a refusal, since
#     by then the repair spans two files;
#   - and that the deliberate arm exists at all, because an agent who does not know
#     `closes-nothing` is available will either force a false close or stall. Its
#     spelling and its required `reason` stay in the schema.
CLOSING_REFERENCE_DUTY = [
    "required whenever `pr_body.state` is `written`",
    "it deliberately closes nothing",
    "the schema carries the spellings",
    "outside code spans and html comments",
    "backticked is not bound",
    "one `closes` line per issue",
    "closes only `#a`",
    "write the line while you write the body",
]

DUTIES = [
    pytest.param(CLOSING_REFERENCE_DUTY, id="pr-body-closes-and-a-bound-keyword"),
    pytest.param(ADJACENT_POLICY, id="adjacent-fix-or-file"),
    pytest.param(GUEST_REPO_ROUTING, id="guest-repo-tooling-routing"),
    pytest.param(FILING_IS_A_REQUEST, id="a-filing-disposition-is-a-request"),
    pytest.param(PLATFORM_FIX_RULES, id="platform-rules-about-the-fix"),
    pytest.param(THIRD_STATE_AS_DESIGN, id="third-state-as-a-design-rule"),
    pytest.param(PAYLOAD_NOT_EVALUATED, id="payload-parsed-never-evaluated"),
    pytest.param(EMPTY_RETURN_POLICY, id="a-spawn-that-returned-nothing"),
    pytest.param(VALIDATOR_SKEW_POLICY, id="cache-vs-clone-validator-skew"),
    pytest.param(REFERRED_BUT_UNSTATED, id="a-spawn-that-referred-without-stating"),
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


def _accessor_states(tmp_path):
    """Drive `loop_repository` through every outcome it has and return them.

    Nothing here spells a state token. The three fixtures are the three *situations*
    -- a manifest that says, a manifest that does not, and no manifest -- and the
    tokens come back from the accessor. That is what makes the assertions below a
    join with `scripts/doctor.py` rather than a second transcription of it.
    """
    said = tmp_path / "said"
    (said / ".claude-plugin").mkdir(parents=True)
    (said / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "x", "repository": "https://example.invalid/x"}', encoding="utf-8"
    )
    silent = tmp_path / "silent"
    (silent / ".claude-plugin").mkdir(parents=True)
    (silent / ".claude-plugin" / "plugin.json").write_text('{"name": "x"}', encoding="utf-8")
    return [
        doctor.loop_repository(plugin_root=said),
        doctor.loop_repository(plugin_root=silent),
        doctor.loop_repository(plugin_root=tmp_path / "absent"),
    ]


def test_the_brief_names_the_accessor_without_copying_it(tmp_path):
    """The join #290 turns on, and the decision it forced.

    The brief has to send a guest-repo tooling defect somewhere, and the somewhere
    is derived rather than inferred. Two ways to write that were available: name the
    call and let the reader run it, or enumerate what it can answer. The second puts
    a fact that lives in `scripts/doctor.py` into a document nobody diffs against it
    -- this repository's governing rule, and the failure mode is a brief confidently
    describing states the accessor stopped having.

    So this holds both halves at once, and neither half is sufficient alone. The
    must-fire half: the brief names a call that exists and is importable, so a rename
    or a deletion lands here rather than in a guest repo at filing time. The must-not
    half: no prose document spells the accessor's answers back, sweeping every skill
    and agent rather than only the one being edited, because the second copy is as
    harmful in whichever document acquires it.

    And the count. The brief says three states, which is a checkable claim rather
    than a copy of their names, so it is checked -- if the accessor ever collapses
    two or grows a fourth, the sentence in the brief goes stale silently and nothing
    else would notice.
    """
    states = _accessor_states(tmp_path)
    assert len({problem for _url, problem in states}) == 3, (
        "the brief says `loop_repository()` answers in three states; the accessor "
        "no longer has three: {}".format(states)
    )
    resolved = [url for url, problem in states if problem is None]
    assert len(resolved) == 1 and resolved[0], "no state of the accessor returns a url"

    brief = _developer()
    assert "`loop_repository()`" in brief, (
        "the brief no longer names the call, so a guest-repo tooling defect has no "
        "derivation and an agent is back to inferring a slug"
    )

    tokens = sorted({problem for _url, problem in states if problem is not None})
    assert tokens, "the accessor reports no failing state, so there is nothing to guard"
    copied = [
        (path.relative_to(REPO_ROOT).as_posix(), token)
        for path in PROSE
        for token in tokens
        if "`{}`".format(token) in path.read_text(encoding="utf-8")
    ]
    assert copied == [], (
        "a document quotes the accessor's own state names back at the reader: {}. "
        "Name the call; let it answer.".format(copied)
    )


# --- #275/#296: placement, and the refusal to credit the intervention --------

# The rules a spawn brief is written from have to sit in the section that writes
# the spawn briefs. Stated anywhere else they are present in the document and
# absent from the moment they are used -- the same producer/consumer join the
# section-four test above guards, one section over.
#
# It is the whole of REFERRED_BUT_UNSTATED rather than a hand-picked subset, and
# that is a correction rather than a preference: the first version listed three of
# the eight, so the other five were checked only by
# `test_the_duty_is_stated_in_the_brief`, which greps the whole document. A later
# edit relocating one of those five into `## Untrusted input` would have left the
# suite green on exactly the regression the paragraph above says this check exists
# to catch -- a guard nominally on and effectively off for most of what it claims,
# which is the shape this repository is named after. Deriving it from the one list
# means an anchor cannot be added to the duty and forgotten here.
REFERRED_BUT_UNSTATED_IN_REVIEW_SECTION = list(REFERRED_BUT_UNSTATED)


def _review_section(text):
    """The whole of `## Review your own diff ...`, subsections included.

    Bounded by the next h2. Returns None rather than an empty string when either
    bound is missing, so a caller cannot mistake "the section is not there" for
    "the section is there and says nothing" -- which is the reading this file
    exists to keep separable.
    """
    start = text.find("## Review your own diff before you hand it back")
    if start == -1:
        return None
    end = text.find("\n## ", start + 1)
    if end == -1:
        return None
    return text[start:end]


def _misplaced_referred_rules(text):
    """Which of the spawn-brief rules are stated outside the review section."""
    section = _review_section(text)
    if section is None:
        return {"no-review-section"}
    return set(_unmet(section, REFERRED_BUT_UNSTATED_IN_REVIEW_SECTION))


def test_the_referred_anchors_were_red_against_the_empty_return_subsection():
    """The tight control for #275, and the one that matters.

    `_prior()` predates #200, so a #275 anchor is trivially absent from it. The
    text this change actually amends is the post-#200 empty-return subsection,
    which already talks about spawns, final messages and `returned-nothing` --
    so that is where a toothless anchor would hide. Paired with its own must-fire
    half, because an empty or mistyped constant satisfies every "absent" claim.
    """
    assert _unmet(PRIOR_EMPTY_RETURN_SORT, LIVE_BEFORE_EMPTY_RETURN) == [], (
        "PRIOR_EMPTY_RETURN_SORT is not the pre-#275 subsection"
    )
    assert _unmet(DEVELOPER.read_text(encoding="utf-8"), LIVE_BEFORE_EMPTY_RETURN) == [], (
        "the live document lost wording this control depends on"
    )
    matched = [a for a in REFERRED_BUT_UNSTATED if a in _flatten(PRIOR_EMPTY_RETURN_SORT)]
    assert matched == [], f"toothless anchors, already on disk: {matched}"


def test_the_referred_but_unstated_rules_land_inside_the_review_section():
    misplaced = _misplaced_referred_rules(DEVELOPER.read_text(encoding="utf-8"))
    assert misplaced == set(), (
        "a rule the spawn briefs are written from sits outside the review section, "
        "so it is never read at the moment it is used: " + repr(sorted(misplaced))
    )


def test_the_placement_check_fires_when_the_rules_sit_outside_that_section():
    """The must-fire half. The same sentences, present in the document and after
    the section that uses them, must be reported as misplaced -- otherwise the
    check above passes on any document that merely contains the words, which is
    what a flat `in` against the whole file would have done.
    """
    elsewhere = (
        "## Review your own diff before you hand it back\n\n"
        "Spawn two agents against your own committed diff.\n\n"
        "## Untrusted input\n\n" + "\n".join(REFERRED_BUT_UNSTATED) + "\n"
    )
    assert _misplaced_referred_rules(elsewhere) == set(
        REFERRED_BUT_UNSTATED_IN_REVIEW_SECTION
    )

    # And the other direction, so the check is not merely reporting back whatever
    # it is handed. The same sentences inside the section must report nothing
    # missing -- without this, a `_misplaced_referred_rules` that always returned
    # its whole anchor list would satisfy the assertion above.
    inside = (
        "## Review your own diff before you hand it back\n\n"
        + "\n".join(REFERRED_BUT_UNSTATED)
        + "\n\n## Untrusted input\n"
    )
    assert _misplaced_referred_rules(inside) == set()

    assert _misplaced_referred_rules("nothing here") == {"no-review-section"}


def test_the_intervention_is_recorded_as_an_experiment_and_not_credited():
    """The deliverable most likely to be dropped, per the filing itself.

    A sentence added to a brief to change a model's behaviour cannot be shown to
    work from inside the session that adds it. So the document has to carry the
    baseline it is measured against, has to say that the observed difference
    between spawn types is confounded rather than explanatory, and has to say
    that nothing downstream is relaxed on the strength of it. Without the last
    one the re-spawn rule quietly becomes optional, which is the same defect one
    layer up: an unmeasured mitigation read as a measured one.
    """
    text = DEVELOPER.read_text(encoding="utf-8")
    section = _review_section(text)
    assert section is not None, "no review section to hold the experiment record"
    unmet = _unmet(
        section,
        [
            "the brief sentence is an experiment, not a fix",
            "three of roughly seven review spawns",
            "confound",
            "nothing below is relaxed on the strength of it",
        ],
    )
    assert unmet == [], "the experiment is not recorded: " + repr(unmet)

    # And the mitigation it must not have relaxed is still stated in full.
    assert _unmet(text, EMPTY_RETURN_POLICY) == [], (
        "the re-spawn policy the experiment must leave alone has been weakened"
    )


def _fourth_state_token():
    """The one state a review survey has and an ordinary survey does not.

    Derived from the schema rather than spelled here, so a rename upstream lands
    on this test instead of leaving the brief teaching a token the validator
    refuses. `survey` is the control: subtracting it is what makes this "the
    state that exists because a spawn can go quiet" rather than "the fourth
    string in a list", which would move if the enum were merely reordered.
    """
    import json

    schema = json.loads(
        (REPO_ROOT / "schemas" / "agent-report.schema.json").read_text(encoding="utf-8")
    )
    review = set(schema["$defs"]["review_survey"]["properties"]["state"]["enum"])
    plain = set(schema["$defs"]["survey"]["properties"]["state"]["enum"])
    return review - plain


def _gesture_arm_missing_the_state(text, token):
    """Is the gesturing-return arm stated without naming the state it maps to?

    Returns a set of what is missing, so "the arm is absent" and "the arm is
    there and names no state" come back as different values rather than as one
    falsy answer.
    """
    section = _review_section(text)
    if section is None:
        return {"no-review-section"}
    folded = _flatten(section)
    missing = set()
    if "refers to findings it does not state" not in folded:
        missing.add("no-gesture-arm")
    if _flatten(token) not in folded:
        missing.add("no-state-token")
    return missing


def test_the_gesturing_arm_maps_to_the_state_the_schema_actually_has():
    """The producer/consumer join for #275/#296, and the reason it is not prose.

    The brief's new arm tells the agent that a message *referring* to findings it
    never states is not a clean review. That instruction is only worth anything
    if it names a state the validator will accept: a brief routing the agent to a
    token `scripts/report_schema.py` refuses is a rule that cannot be complied
    with, and the failure surfaces at validation time in somebody else's session.

    So the token is derived from the schema and asserted present in the section
    that states the arm. Both halves are needed: without the derivation this is a
    second transcription of a fact that lives in the schema, and without the
    section bound it passes on any document that happens to contain the word.
    """
    tokens = _fourth_state_token()
    assert len(tokens) == 1, (
        "a review survey no longer has exactly one state an ordinary survey lacks; "
        "the brief's routing for a spawn that went quiet has no single destination: "
        "{}".format(sorted(tokens))
    )
    token = tokens.pop()

    assert _gesture_arm_missing_the_state(DEVELOPER.read_text(encoding="utf-8"), token) == set(), (
        "the brief states the gesturing-return arm without routing it to the state "
        "the schema has for it, or does not state the arm at all"
    )


def test_the_gesturing_arm_check_fires_on_a_document_that_is_missing_either_half():
    """The must-fire half, and it is two halves because the check has two.

    A single "did it pass" assertion above would stay green on a document that
    dropped the arm, on one that dropped the state, and on one with no review
    section at all -- three different failures rendering as one absence, which is
    the defect this repository is named after aimed at its own guard.
    """
    token = "returned-nothing-sentinel-not-a-real-state"
    both = (
        "## Review your own diff before you hand it back\n\n"
        "Spawn two agents.\n\n"
        "## Untrusted input\n"
    )
    assert _gesture_arm_missing_the_state(both, token) == {"no-gesture-arm", "no-state-token"}

    arm_only = (
        "## Review your own diff before you hand it back\n\n"
        "A message that refers to findings it does not state is not a clean review.\n\n"
        "## Untrusted input\n"
    )
    assert _gesture_arm_missing_the_state(arm_only, token) == {"no-state-token"}

    state_only = (
        "## Review your own diff before you hand it back\n\n"
        "Set the state to " + token + ".\n\n"
        "## Untrusted input\n"
    )
    assert _gesture_arm_missing_the_state(state_only, token) == {"no-gesture-arm"}

    assert _gesture_arm_missing_the_state("nothing here", token) == {"no-review-section"}


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
