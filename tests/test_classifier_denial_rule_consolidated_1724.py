"""#1724: one canonical classifier-denial rule, not three.

Before this fix, `skills/manager/phases/tick-order.md`, `skills/manager/phases/merge.md`
and `commands/release.md` each stated a different rule for the same event -- a `Blocked
by classifier` denial on a call the loop issues on its own initiative:

- tick-order.md scoped its retry-once rule narrowly to `oss_state.py`/`agent_role.py`.
- release.md stated a retry-once-and-report rule for `release_publish.py`/`gh release
  create`.
- merge.md stated no retry permission at all -- only "do not route around a denied
  merge" plus a command-string framing a sub-manager over-read as retry license.

A sub-manager applied tick-order.md's narrow rule to a `gh-pr-merge` call and a
`lane_setup.py --release` call anyway, citing "the loop's own classifier-denial
guidance" for both -- exactly the state this test pins shut: one canonical rule, stated
once in SKILL.md's hazards list, referenced (not restated) by the three phase-specific
call sites.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

SKILL_MD = REPO_ROOT / "skills" / "manager" / "SKILL.md"
TICK_ORDER_MD = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"
MERGE_MD = REPO_ROOT / "skills" / "manager" / "phases" / "merge.md"
RELEASE_MD = REPO_ROOT / "commands" / "release.md"
OSS_RULES_PY = REPO_ROOT / "scripts" / "oss_rules.py"
MERGE_GATE_JIT_MD = (
    REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss" / "merge-gate.md"
)

# A short marker unique to the canonical rule's own wording -- not merely "retry" or
# "classifier", either of which several unrelated passages in these same files already
# carry (agents/developer.md's own #1518 rule, the git-step bullet, the release.md
# resume-point prose), so a marker that could match one of those would not tell a
# consolidated rule from a merely-adjacent one.
CANONICAL_MARKER = (
    "retry the\n  identical, unmodified call once, and report the outcome either way"
)


def test_skill_md_states_the_canonical_rule_once():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.count(CANONICAL_MARKER) == 1, (
        "SKILL.md should state the classifier-denial rule's core sentence exactly "
        "once -- zero means the rule regressed out, more than one means it drifted "
        "back into being restated rather than referenced."
    )
    # And the never-retry-twice / never-reword halves are both there, not just the
    # retry-once half -- a rule that only ever says "retry" without the two "never"s
    # is the exact shape #1724's own sub-manager over-applied.
    assert "Never reword or restructure the call" in text
    assert "second denial" in text and "handed over" in text


def test_each_call_site_points_at_the_canonical_rule_instead_of_restating_it():
    """Every one of the three phase-specific files names SKILL.md's rule by reference
    (#1724) rather than spelling out its own, possibly-drifted, retry policy."""
    for path in (TICK_ORDER_MD, MERGE_MD, RELEASE_MD):
        text = path.read_text(encoding="utf-8")
        assert "#1724" in text, (
            "{} does not reference the canonical classifier-denial rule (#1724) -- "
            "a reader landing here first has no pointer to the one place the retry "
            "policy is actually decided.".format(path.name)
        )


def test_merge_md_no_longer_licenses_a_bare_retry_with_no_bound():
    """The specific misapplication #1724 reports: merge.md's command-string framing
    ("read `Blocked by classifier` as a claim about the command string, not about the
    action") read, on its own, as license to keep trying different spellings. It must
    now say in as many words that this is not licence for a second attempt."""
    text = MERGE_MD.read_text(encoding="utf-8")
    assert "not license to reword and re-send" in text
    assert "one-retry rule" in text


def test_the_scripted_merge_gate_rule_also_points_at_the_canonical_rule():
    """A self-review finding (spawned auditor, same lane): `scripts/oss_rules.py`'s
    `TOOLS_MERGE_GATE` -- a fourth, pre-existing statement of "do not route around a
    denied merge", rendered into every scaffolded repository's own
    `.claude/jit-context/tools/01-oss/merge-gate.md` -- was not one of the three files
    #1724's own issue named, and had been missed. Both the source constant and its
    tracked, generated copy in this repository's own layer must reference #1724, and
    the two must stay byte-identical (this repo ships the rule it also scaffolds with)."""
    source = OSS_RULES_PY.read_text(encoding="utf-8")
    assert "#1724" in source
    generated = MERGE_GATE_JIT_MD.read_text(encoding="utf-8")
    assert "#1724" in generated
    # The constant is generated with a leading/trailing """ this repo's own copy does
    # not carry -- compare stripped of the wrapping triple-quote and any \n it left.
    marker = source[
        source.index('TOOLS_MERGE_GATE = """') + len('TOOLS_MERGE_GATE = """') :
    ]
    marker = marker[: marker.index('"""')]
    assert marker == generated, (
        "scripts/oss_rules.py's TOOLS_MERGE_GATE and the tracked "
        ".claude/jit-context/tools/01-oss/merge-gate.md have diverged -- this "
        "repository ships the rule it also scaffolds with, so the two must match."
    )


def test_a_file_that_only_names_retry_without_the_bound_fails_the_marker():
    """Positive control for test_skill_md_states_the_canonical_rule_once: a file that
    merely mentions retrying, without the canonical rule's own exact sentence, must
    not satisfy the marker check above -- otherwise the marker is too loose to tell
    "the rule is here" from "the word retry appears somewhere"."""
    narrating = (
        "# Some Other File\n\n"
        "A denied call may be retried once before giving up, and the outcome should "
        "be written down somewhere for later.\n"
    )
    assert CANONICAL_MARKER not in narrating
