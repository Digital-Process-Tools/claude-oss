"""The manager skill states facts about supertool's op inventory. Those rot.

#195 is the instance: the skill said `there is no gh-pr-edit`, supertool shipped one,
and the raw `gh pr edit` the sentence sanctioned instead was the single publishing
path in this loop with no closing-reference check and no read-back on what it wrote.
#240 is the filing that the instance was fixed and the class was not.

The two directions do not fail alike, and that asymmetry is what these checks encode.
An op NAMED here that supertool later removed fails at the call -- loudly, writing
nothing. A sentence saying an op does NOT exist routes the reader to a raw call that
runs. Only the negative is silent, and only the negative is checked here.

Both checks are "must not fire" assertions over a corpus that is legitimately empty
today, so each is paired with a positive control built from the literal text this
document carried before #195. Without the control, an empty corpus and a broken
matcher are the same green tick -- which is the defect this repository is named after.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "manager" / "SKILL.md"

# The exact shape #195 carried. Kept as a literal rather than read from git: CI
# checks out at depth 1, so the pre-#195 blob is not reachable from a CI tree.
PRE_195 = """that already exists, and there is no op for it: `gh-pr-create` consumes the payload once and there
is no `gh-pr-edit`. Use raw `gh`, which the op table above already sanctions for writes nothing
wraps:

```bash
gh pr edit <N> --body-file <a file holding the agent's body plus your appended section>
```
"""

# An op name as this document spells one: `gh-pr-edit`, `gh-issue-create`.
# Scoped to the `gh-` prefix and two hyphens, the same shape `_op_names` accepts:
# unscoped, it made "there is no `dry-run` flag" a failure about op inventory.
OP_TOKEN = r"gh-[a-z0-9]+(?:-[a-z0-9]+)+"

# The second alternative in each class is the typographic apostrophe (U+2019),
# written as an escape so this source stays ASCII; `re` resolves \uXXXX itself.
_NOT = r"(?:is\s+not|isn['\u2019]?t)"
_DOES_NOT = r"(?:does\s+not|doesn['\u2019]?t)"

# Every surface form of "supertool has no such op" that turned up when the shapes
# were enumerated rather than guessed. The first draft matched four forms and an
# audit produced four more it let through -- a guard nominally on and effectively
# off. The docstring promise is the whole class, so a form found missing gets
# added here with a control below; the controls are what keep the list honest.
#
# Run against whitespace-collapsed text on purpose: in the pre-#195 document the
# words "there is no `gh-pr-edit`" straddled a line break, so a line-oriented
# matcher would have reported the file clean.
NEGATIVE_CLAIM_RE = re.compile(
    r"(?:there\s+(?:is|are)\s+no|ha[sv]e?\s+no|\bno)\s+"
    r"(?:op\s+(?:for|named|called)\s+)?`(" + OP_TOKEN + r")`"
    r"|`("
    + OP_TOKEN
    + r")`\s+(?:"
    + _DOES_NOT
    + r"\s+exist|"
    + _NOT
    + r"\s+(?:an\s+op|available|shipped))"
)

# The fence marker is allowed leading whitespace: a fenced block nested in a list
# item is ordinary Markdown, and anchoring at column 0 would read one as absent
# rather than as unindented.
FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)

# Must fire. Each was measured against the first draft of NEGATIVE_CLAIM_RE, and
# every one but the first went undetected there.
ROT_FORMS = [
    "supertool has no `gh-pr-edit` op",
    "there is no op for `gh-pr-edit`",
    "no op named `gh-pr-edit` exists yet",
    "`gh-pr-edit` isn't available",
    "`gh-pr-edit` doesn't exist",
    "there are no `gh-pr-edit` ops",
    "`gh-pr-edit` is not shipped",
]

# Must NOT fire: a hyphenated term that is not an op name, a negative claim that
# names no op, and an op named in the ordinary affirmative. Without these the
# widening above is unfalsifiable.
NON_ROT_FORMS = [
    "there is no `dry-run` flag on this command",
    "there is no op for tagging, releasing or deleting a ref",
    "correct a published body with `gh-pr-edit`",
    "`gh-pr-edit` refuses a dropped closing reference",
]


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _claimed_absent(text):
    found = set()
    for match in NEGATIVE_CLAIM_RE.finditer(_collapse(text)):
        found.add(match.group(1) or match.group(2))
    return found


def _op_names(text):
    """Every `gh-<verb>-<noun>` op this document names in backticks."""
    names = set()
    for token in re.findall(r"`(gh-[a-z0-9-]+)", text):
        names.add(token.split(":")[0].rstrip("-"))
    return {name for name in names if name.count("-") >= 2}


def _raw_forms(op_names):
    """`gh-pr-edit` -> `gh pr edit`: the raw call the op supersedes."""
    return dict((name, name.replace("-", " ")) for name in op_names)


def _fenced_raw_calls(text, raw_forms):
    hits = []
    for block in FENCE_RE.findall(text):
        for name, raw in sorted(raw_forms.items()):
            if raw in block:
                hits.append((name, raw))
    return hits


def test_the_skill_is_readable():
    assert SKILL.is_file(), "{}: absent -- every check below would be vacuous".format(
        SKILL
    )


def test_op_names_are_found_at_all():
    """Without this, both checks below pass on an empty corpus."""
    names = _op_names(SKILL.read_text(encoding="utf-8"))
    assert "gh-pr-edit" in names, sorted(names)
    assert len(names) >= 3, sorted(names)


def test_no_op_is_asserted_not_to_exist():
    absent = _claimed_absent(SKILL.read_text(encoding="utf-8"))
    assert not absent, (
        "the manager skill asserts supertool has no {} -- an inventory claim that was "
        "only true when it was written, and the one that fails silently. Probe with "
        "supertool 'ops' and state the rule, not the inventory (#195, #240).".format(
            sorted(absent)
        )
    )


def test_the_negative_matcher_fires_on_the_sentence_that_rotted():
    """Positive control for the check above."""
    assert _claimed_absent(PRE_195) == set(["gh-pr-edit"]), sorted(
        _claimed_absent(PRE_195)
    )


def test_the_negative_matcher_fires_on_every_form_it_promises():
    """The docstring promises a class, not a wording. Each form is a control."""
    missed = [
        form for form in ROT_FORMS if _claimed_absent(form) != set(["gh-pr-edit"])
    ]
    assert not missed, "NEGATIVE_CLAIM_RE let {} of {} rot forms through: {}".format(
        len(missed), len(ROT_FORMS), missed
    )


def test_the_negative_matcher_does_not_fire_on_ordinary_prose():
    """The other half. A matcher that fires on everything reports the same green."""
    wrong = [form for form in NON_ROT_FORMS if _claimed_absent(form)]
    assert not wrong, "NEGATIVE_CLAIM_RE fired on prose that claims nothing: {}".format(
        wrong
    )


def test_no_fenced_block_makes_a_raw_call_an_op_supersedes():
    text = SKILL.read_text(encoding="utf-8")
    hits = _fenced_raw_calls(text, _raw_forms(_op_names(text)))
    assert not hits, (
        "a fenced command block in the manager skill invokes {} while the same "
        "document names {} for it -- the raw route is the one with no "
        "closing-reference check and no read-back (#195, #240).".format(
            sorted(raw for _, raw in hits), sorted(name for name, _ in hits)
        )
    )


def test_the_fence_matcher_fires_on_the_block_that_rotted():
    """Positive control for the check above."""
    hits = _fenced_raw_calls(PRE_195, _raw_forms(set(["gh-pr-edit", "gh-pr-create"])))
    assert hits == [("gh-pr-edit", "gh pr edit")], hits
