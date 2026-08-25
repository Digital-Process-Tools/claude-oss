"""#524: the rule blocks unconditionally, and the presence check it lacks is not ours
to add unilaterally.

`supertool-required.md` ships `mode: block` with no way to say "block, unless the binary
cannot be found" -- frontmatter has no field for that. `claude-jit-context`'s own tracker
(#203 there) has agreed to build one, spelled `requires: <tool>`, probed with `command -v`
at fire time and named in the injected context when it degrades a block to a warn. As of
`claude-jit-context` 0.5.0 -- the newest cached release -- no script under `scripts/`
mentions the word `requires` at all: the field has not shipped (measured, not assumed;
see the note in `oss_rules.py` beside `TOOLS_SUPERTOOL`).

So this repository's half is narrower than "wire up the degrade": write the field now, so
that the day the upstream hook starts reading it, this rule needs no further edit, and say
in the rule's own text that writing it today changes nothing yet. `jit_frontmatter()` in
`claude-jit-context/scripts/common.sh` reads a frontmatter field by matching `<name>: ` at
line start and returns nothing for a name it was not asked for -- an unrecognised key is
inert, never a parse error, which is what makes shipping the field before its reader exists
safe rather than merely optimistic. That claim is asserted here as a fact about the current
constant (the field is present, the mode is unchanged), not driven through the installed
hook -- driving it would only show the field being ignored, which is the state already
described in prose above.

`test_the_rule_still_blocks_rather_than_reminding` in
`test_supertool_rule_states_the_absent_case_294.py` is the control this file must not
disturb: `mode: block` stays exactly as effective today as it was before this field
existed, because nothing yet reads `requires:` to soften it.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

RULE = "supertool-required.md"


def _body():
    return oss_rules.RULES["tools"][RULE]


def test_the_rule_declares_requires_supertool():
    body = _body()
    assert oss_rules._field(body, "requires") == "supertool", (
        "the rule carries no requires: field naming the binary its block depends on -- "
        "the day claude-jit-context reads one, this rule has to already be shipping it, "
        "or the degrade lands nowhere (#524)"
    )


def test_the_rule_says_the_field_is_not_yet_honoured_by_anything_shipped():
    body = _body()
    assert "203" in body, (
        "the rule does not point a reader at the upstream issue tracking the reader "
        "half of this fix -- without it there is no way to tell whether the degrade "
        "this field promises is live"
    )
    assert "not" in body and ("honour" in body or "read" in body), (
        "the rule does not say in as many words that no shipped claude-jit-context "
        "version reads requires: yet -- writing the field silently would read as done"
    )


def test_the_block_mode_is_unchanged_by_adding_the_field():
    """The field is inert today. Adding it must not, by itself, change what this rule
    already does -- that would be claiming a fix the upstream half has not landed.
    """
    assert oss_rules._field(_body(), "mode") == "block"


def test_no_shipped_claude_jit_context_script_reads_requires_yet():
    """A measurement, not a belief -- and the reason half 1 has to stay documentation
    rather than working code. If this ever finds a hit, the prose above is stale and
    the rule can start claiming the degrade for real.
    """
    import glob
    import os

    cache_root = os.path.expanduser(
        "~/.claude/plugins/cache/dpt-plugins/claude-jit-context"
    )
    scripts = glob.glob(os.path.join(cache_root, "*", "scripts", "*.sh"))
    if not scripts:
        import pytest

        pytest.skip("no claude-jit-context cache on this machine -- untested here")
    hits = []
    for path in scripts:
        with open(path, encoding="utf-8", errors="replace") as fh:
            if "requires" in fh.read():
                hits.append(path)
    assert not hits, (
        "a shipped claude-jit-context script now mentions `requires` -- the field may "
        "be live; re-read it and update this rule and this test rather than trusting "
        "this comment (#524): {}".format(hits)
    )
