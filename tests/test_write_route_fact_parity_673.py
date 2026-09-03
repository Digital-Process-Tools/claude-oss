"""#673: `tests/test_content_invariants.py` checks the developer brief's
write-route paragraph and its pasted-into-briefs twin in the manager loop
each against a floor -- does this copy name `paste`, does it name `path` and
`content` -- and never against *each other*. Two copies clearing the same
floor can still disagree about a fact neither test looks at, and nothing
would notice.

The premise this issue opened with -- normalized equality between two
worked-example TOML blocks -- no longer holds: `eb273b5` removed the
walkthrough from `skills/manager/phases/dispatch.md` entirely, so there is
no second block left to diff. The question the maintainer's follow-up
comment reframes it as is which facts a condensed, pasted-into-every-brief
blockquote and the fuller agent definition must still agree on, verbatim,
because they are the kind of fact a paraphrase quietly loses: a machine's
literal output string, or a fixed list of names.

**Decision recorded here** (see the pull request body for the full
argument): both copies must carry, byte-for-byte, the read-only op roster,
the exact field lists for `edit:@-` and `paste:@-`, the literal error string
a missing `op` entry actually produces, and the `literal_backslashes` escape
hatch's name. They may legitimately differ on everything else -- the fuller
developer.md carries the "payload is parsed, never evaluated" explanation
and the `supertool 'ops'` / `help:edit` / `help:paste` discoverability
pointers with no equivalent in the condensed blockquote, and that is not a
gap: an agent already standing inside its own definition can explore those:
a dispatched agent staring at a brief cannot.

This is the shape `tests/test_supertool_rule_sync_577.py` established for a
pair that must match completely; here only five named facts must, so the
comparison is per-fact rather than per-document.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from developer_docs import DeveloperBrief  # noqa: E402
from test_content_invariants import MANAGER_SKILL, _collapse  # noqa: E402

DEVELOPER_MD = DeveloperBrief()  # spine + agents/developer/*.md (#939)

#: The real error `supertool 'batch:@-'` produces for an `[[ops]]` entry with
#: no `op` field -- measured directly (2026-08-29):
#:
#:     $ supertool 'batch:@-' <<'EOF'
#:     [[ops]]
#:     path = "x"
#:     content = "x"
#:     EOF
#:     ERROR: batch op missing 'op' field
#:
#: Both documents quoted `batch op missing op field` -- no quotes around
#: `op` -- which is not what the tool prints. The two copies agreeing with
#: each other is exactly why nothing caught this: a pairwise-parity check
#: proves the copies match, not that either one is right, so this constant
#: is asserted against the measured tool output as well as between the two
#: documents.
BATCH_OP_MISSING_ERROR = "batch op missing 'op' field"

#: Extractors: each pulls one named fact out of a whitespace-collapsed copy of
#: a document. A `None` return means the document does not state the fact at
#: all -- reported as a finding rather than crashing the comparison.
_OP_ROSTER_RE = re.compile(r"Batch 6-7 ops per call — (.*?) — never one \w+ per file")
_PASTE_FIELDS_RE = re.compile(r"paste:@-'?\`?[^.;]*?carrying `(path)`(?: and| ,)? `(content)`")
_EDIT_FIELDS_RE = re.compile(r"edit:@-'?\`?[^.;]*?carrying `(path)`, `(old)` and `(new)`")
_BATCH_ERROR_RE = re.compile(r"fails[^`]*`(batch op missing[^`]*)`")


def _op_roster(text):
    m = _OP_ROSTER_RE.search(text)
    return m.group(1) if m else None


def _paste_fields(text):
    m = _PASTE_FIELDS_RE.search(text)
    return m.groups() if m else None


def _edit_fields(text):
    m = _EDIT_FIELDS_RE.search(text)
    return m.groups() if m else None


def _batch_error(text):
    m = _BATCH_ERROR_RE.search(text)
    return m.group(1) if m else None


def _escape_hatch_named(text):
    return "literal_backslashes" in text


#: name -> extractor. Every one of these is asserted equal across the two
#: documents in `test_shared_facts_agree_between_the_two_copies`.
FACT_EXTRACTORS = {
    "read-only op roster": _op_roster,
    "paste:@- field list": _paste_fields,
    "edit:@- field list": _edit_fields,
    "batch missing-op error string": _batch_error,
    "literal_backslashes escape hatch named": _escape_hatch_named,
}


def _facts(text):
    return {name: fn(text) for name, fn in FACT_EXTRACTORS.items()}


def test_shared_facts_agree_between_the_two_copies():
    dev = _collapse(DEVELOPER_MD.read_text(encoding="utf-8"))
    loop = _collapse(MANAGER_SKILL.read_text(encoding="utf-8"))
    dev_facts = _facts(dev)
    loop_facts = _facts(loop)
    disagreements = {
        name: (dev_facts[name], loop_facts[name])
        for name in FACT_EXTRACTORS
        if dev_facts[name] != loop_facts[name]
    }
    assert not disagreements, (
        "agents/developer.md and the manager loop's pasted-into-briefs write-route "
        "material disagree about a fact that must be identical, not paraphrased "
        "(#673): {}".format(disagreements)
    )


def test_the_shared_facts_are_actually_findable_in_both_documents():
    """A `None` on both sides would satisfy the equality check above for the
    wrong reason -- neither document states the fact at all. This is the
    third state: findable-and-equal, findable-and-disagreeing (above), or
    not-findable at all (here)."""
    dev = _collapse(DEVELOPER_MD.read_text(encoding="utf-8"))
    loop = _collapse(MANAGER_SKILL.read_text(encoding="utf-8"))
    missing = {
        name: ("developer.md" if fn(dev) is None else None, "manager loop" if fn(loop) is None else None)
        for name, fn in FACT_EXTRACTORS.items()
        if fn(dev) is None or fn(loop) is None
    }
    assert not missing, "a shared fact is not stated at all in one copy: {}".format(missing)


def test_the_batch_error_string_matches_the_measured_tool_output():
    """Parity between the two documents is necessary but not sufficient --
    they can agree with each other and both be wrong about what the tool
    actually prints, which is exactly what had happened here."""
    dev = _collapse(DEVELOPER_MD.read_text(encoding="utf-8"))
    loop = _collapse(MANAGER_SKILL.read_text(encoding="utf-8"))
    assert _batch_error(dev) == BATCH_OP_MISSING_ERROR, _batch_error(dev)
    assert _batch_error(loop) == BATCH_OP_MISSING_ERROR, _batch_error(loop)


# --- must-fire controls: prove the parity check can actually fail ----------

_DEV_SNIPPET = (
    "Batch 6-7 ops per call — `read`, `grep`, `glob`, `map`, `around`, `between`, "
    "`tree` — never one read per file. Changing a file — `supertool 'edit:@-'` "
    "with a heredoc carrying `path`, `old` and `new`. Creating one — "
    "`supertool 'paste:@-'` with a heredoc carrying `path` and `content`. Omit "
    "`op` on any entry and the call fails with `batch op missing 'op' field` — a "
    "failed call. `literal_backslashes = true` exists for a real backslash."
)


def test_the_parity_check_fires_when_a_copy_drops_one_roster_entry():
    """Must-fire: a condensed copy silently loses one op from the roster --
    the exact drift #673 says nothing currently catches."""
    narrowed = _DEV_SNIPPET.replace("`map`, ", "")
    assert _op_roster(_DEV_SNIPPET) != _op_roster(narrowed)
    assert _op_roster(narrowed) is not None  # still findable, just wrong


def test_the_parity_check_fires_when_the_batch_error_string_drifts():
    """Must-fire: the exact loophole this test suite closes -- both copies
    agreeing on a wrong string is invisible to a pairwise-only comparison."""
    wrong = _DEV_SNIPPET.replace(
        "batch op missing 'op' field", "batch op missing op field"
    )
    assert _batch_error(wrong) != BATCH_OP_MISSING_ERROR


def test_the_facts_are_findable_in_the_control_snippet():
    """Sanity: the snippet used by the must-fire controls above is itself a
    positive case for every extractor, so a control that "fires" by going to
    `None` instead of to a wrong-but-present value is not mistaken for one
    that actually exercises the comparison."""
    facts = _facts(_DEV_SNIPPET)
    missing = [name for name, value in facts.items() if value is None]
    assert not missing, missing
