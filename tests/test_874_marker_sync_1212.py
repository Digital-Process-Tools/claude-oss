"""The #874 "may not ask a spawned agent for a verdict on one" marker exists in
three places -- `agents/audit/shared.md`, `agents/auditor.md` and
`agents/release-auditor.md` -- and nothing compared them (#1212). #1210 restored
the marker into `agents/auditor.md` and `agents/release-auditor.md`'s own raw
text alongside the existing copy in `agents/audit/shared.md`, after #1071 had
deduplicated it out to the shared fragment and left only a pointer -- a fact
`tests/test_delegated_test_run_877.py` could not see because it reads each
file's own bytes directly and never resolves the pointer. Nothing then compared
the three restored copies to each other, which is the identical duplication-drift
shape `tests/test_supertool_rule_sync_577.py` already guards for a structurally
different pair (a supertool rule body duplicated between `.claude/jit-context/`
and `scripts/oss_rules.py`).

## Why substrings, not whole-paragraph equality

`agents/audit/shared.md` and `agents/auditor.md`'s own copies of the marker
paragraph are byte-identical -- #1071 originally deduplicated them from a single
shared source and #1210 restored `auditor.md`'s copy verbatim. `agents/
release-auditor.md`'s copy was **deliberately reworded** by #1210: restoring it
byte-identical to the other two re-tripped `tests/test_audit_shared_1071.py`'s own
duplication-threshold guard (168 shared 8-grams against a `< 150` ceiling), so
`release-auditor.md` carries the same four required substrings inside different
surrounding prose (132 shared 8-grams after the reword). A byte-identical
three-way comparison would therefore be WRONG -- it would either fail forever on
the intentionally-reworded copy, or (if loosened to accommodate it) stop catching
genuine drift. So this guard checks that a fixed set of load-bearing substrings --
the ones a maintainer reading any single copy relies on to state the rule
correctly -- survive identically in all three files, and leaves the prose around
them free to vary.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

SHARED_MD = REPO_ROOT / "agents" / "audit" / "shared.md"
AUDITOR_MD = REPO_ROOT / "agents" / "auditor.md"
RELEASE_AUDITOR_MD = REPO_ROOT / "agents" / "release-auditor.md"

HEADING = "## Test behaviour is reasoned, not run"

#: The substrings a maintainer actually depends on staying identical across all
#: three copies -- the #874 citation, the core prohibition, and the two
#: backtick-quoted words the finding-classification vocabulary hinges on.
#: Extracted from `agents/audit/shared.md`'s own canonical paragraph; verified
#: (below) to actually appear there, so a typo in this tuple is caught rather
#: than silently never matching anything.
REQUIRED_SUBSTRINGS = (
    "may not run the suite, and may not ask a spawned agent for a verdict on one",
    "(#874)",
    "`reasoned`, never `observed`",
)


def _section(text, heading):
    """The prose between `heading` and the next `## ` heading (or EOF)."""
    idx = text.find(heading)
    assert idx != -1, "heading {!r} not found".format(heading)
    rest = text[idx + len(heading) :]
    nxt = rest.find("\n## ")
    return rest if nxt == -1 else rest[:nxt]


def _normalize(text):
    """Whitespace-only normalisation -- a line wrap must never register as drift,
    the same contract `test_supertool_rule_sync_577.py` uses for CRLF/trailing
    whitespace, generalised to cover mid-paragraph line breaks too (the reworded
    `release-auditor.md` copy wraps the marker sentence differently)."""
    return " ".join(text.split())


def _marker_section(path):
    return _section(path.read_text(encoding="utf-8"), HEADING)


# --- 1. the two byte-identical copies stay byte-identical ---------------------------


def test_shared_and_auditor_marker_paragraphs_are_byte_identical():
    """#1071 deduplicated these from one shared source and #1210 restored
    `auditor.md`'s copy verbatim -- these two have no reason to differ at all, so
    this pair is held to the stricter, whole-paragraph bar `test_supertool_rule_
    sync_577.py` uses, not just the substring bar the reworded third copy gets."""
    shared_body = _marker_section(SHARED_MD).strip()
    auditor_body = _marker_section(AUDITOR_MD).strip()
    assert shared_body == auditor_body, (
        "agents/audit/shared.md and agents/auditor.md's own copies of the #874 "
        "'may not ask a spawned agent for a verdict on one' marker have diverged "
        "(#1212)"
    )


# --- 2. the reworded copy still carries every required substring -------------------


def test_release_auditor_carries_the_required_substrings():
    body = _normalize(_marker_section(RELEASE_AUDITOR_MD))
    missing = [s for s in REQUIRED_SUBSTRINGS if _normalize(s) not in body]
    assert not missing, (
        "agents/release-auditor.md's reworded copy of the #874 marker is missing "
        "required substring(s) {!r} (#1212)".format(missing)
    )


def test_shared_itself_carries_the_required_substrings():
    """Positive control, other half: pins that `REQUIRED_SUBSTRINGS` is actually
    drawn from the canonical text, so a typo in the tuple above is caught here
    rather than silently never matching anything anywhere."""
    body = _normalize(_marker_section(SHARED_MD))
    missing = [s for s in REQUIRED_SUBSTRINGS if _normalize(s) not in body]
    assert not missing, (
        "REQUIRED_SUBSTRINGS drifted from shared.md itself: {!r}".format(missing)
    )


def test_auditor_itself_carries_the_required_substrings():
    body = _normalize(_marker_section(AUDITOR_MD))
    missing = [s for s in REQUIRED_SUBSTRINGS if _normalize(s) not in body]
    assert not missing, missing


# --- 3. control pair: must fire on a genuine one-sided edit, must not fire on ------
# --- the current, intentionally-reworded three-copy state --------------------------


def test_control_current_repo_state_does_not_fire():
    """Confirms the guard is clean against the real, current, intentionally
    reworded three-copy state left by #1210 -- the whole reason a substring
    design was chosen over whole-paragraph equality."""
    test_shared_and_auditor_marker_paragraphs_are_byte_identical()
    test_release_auditor_carries_the_required_substrings()


def test_control_a_one_sided_edit_to_the_core_prohibition_is_caught():
    """Positive control: edit just one copy's core prohibition (as if someone had
    hand-fixed a typo in only one of the three files) and confirm the substring
    check on that copy fails while the untouched two still pass."""
    canonical = _marker_section(SHARED_MD)
    edited = canonical.replace(
        "may not ask a spawned agent for a verdict on one",
        "may ask a spawned agent for a verdict on one",  # the drift: dropped "not"
    )
    assert _normalize(canonical) != _normalize(edited)
    normalized = _normalize(edited)
    missing = [s for s in REQUIRED_SUBSTRINGS if _normalize(s) not in normalized]
    assert missing, (
        "the control edit dropped the word 'not' from the core prohibition and "
        "should have broken at least one required substring, but the guard would "
        "have missed it"
    )


def test_control_a_one_sided_edit_to_the_issue_citation_is_caught():
    """A second, independent one-sided edit: the #874 citation itself drifting
    (e.g. renumbered by hand in only one copy) must also be caught."""
    canonical = _marker_section(SHARED_MD)
    edited = canonical.replace("(#874)", "(#1212)")
    assert _normalize(canonical) != _normalize(edited)
    normalized = _normalize(edited)
    missing = [s for s in REQUIRED_SUBSTRINGS if _normalize(s) not in normalized]
    assert missing, (
        "the control edit renumbered the #874 citation and should have broken "
        "the guard's required-substring check"
    )


def test_control_line_wrap_alone_does_not_count_as_drift():
    """The reworded release-auditor.md copy wraps the marker sentence across a
    line break the other two copies do not have -- that alone must never register
    as drift, the same contract test_supertool_rule_sync_577.py pins for CRLF."""
    a = "one (#874). A finding"
    b = "one\n(#874). A finding"
    assert _normalize(a) == _normalize(b)
