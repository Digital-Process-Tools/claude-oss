"""#524 wrote `requires: supertool` into the frontmatter on the reasoning that an
unrecognised key is inert, so shipping it early would cost nothing and back-fill the day
the upstream reader landed. #570 is that day: `claude-jit-context` 0.6.0 ships the reader
(`common.sh`'s `jit_missing_requires()`, `pre-tool-hook.sh`'s `requires_missing` /
`can_refuse` and the injected `degrade_note`), so the rule's own prose describing the field
as inert had gone stale on every machine carrying that release -- and this file's own
measurement is what caught it: `test_no_shipped_claude_jit_context_script_reads_requires_yet`
asserted no cached script mentioned `requires` and failed the moment 0.6.0 was cached here.

That old assertion is retired rather than loosened -- reversing which side of "does a
cached release read requires:" is the expected answer would make the test pass against
either state, which pins nothing. What replaces it measures the SAME fact in the direction
that is now expected to hold: the newest cached release DOES read the field. If a future
release regresses that (or if the newest cached copy is older than 0.6.0 on some machine),
this file is expected to go red again the same way it did for #570, which is the signal
that the rule's prose needs re-reading rather than re-trusting.

The other three tests here pin what the rule now SAYS about that behaviour -- the replacement
sentence, not the retired one -- and the care #524's own review already applied once still
applies: the new assertions must not also pass against the pre-#570 body.

`test_the_rule_still_blocks_rather_than_reminding` in
`test_supertool_rule_states_the_absent_case_294.py` is the control this file must not
disturb: `mode: block` is unchanged by any of this -- the degrade is upstream's `pre-tool-hook.sh`
softening its OWN enforcement of a block row when the binary is missing, not a change to what
this repository's frontmatter declares.
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


def test_the_rule_says_the_field_is_now_honoured():
    body = _body()
    assert "203" in body, (
        "the rule does not point a reader at the upstream issue that shipped the "
        "reader half of this fix -- without it there is no way to tell whether the "
        "degrade this field promises is live"
    )
    assert "570" in body, (
        "the rule does not point a reader at the issue that caught the prose going "
        "stale (#570) -- the same class can recur and needs the same trail"
    )
    # Anchored on a phrase from the NEW paragraph itself, not on words ("not", "read")
    # that either the pre-#524 or the pre-#570 body already contained in unrelated
    # sentences -- an earlier version of this exact mistake passed against the OLD
    # body verbatim and pinned nothing, caught in review (#524).
    assert "**It is honoured.**" in body, (
        "the rule no longer says in as many words that the requires: field is read "
        "by a shipped claude-jit-context release -- it shipped in 0.6.0 (#570), and "
        "prose still describing it as inert would read as done what is not, or as "
        "undone what is now live"
    )
    assert (
        "No shipped `claude-jit-context` release reads a `requires:` field"
        not in body
    ), (
        "the rule still carries the retired #524 sentence claiming nothing reads "
        "requires: -- that became false the moment 0.6.0 shipped the reader (#570)"
    )


def test_the_block_mode_is_unchanged_by_adding_the_field():
    """The field is inert today. Adding it must not, by itself, change what this rule
    already does -- that would be claiming a fix the upstream half has not landed.
    """
    assert oss_rules._field(_body(), "mode") == "block"


def test_newest_installed_claude_jit_context_reads_requires():
    """A measurement, not a belief (#570, the inverse of #524's own).

    #524's version of this test asserted no cached release read `requires:` yet, and
    it was written to go red the day that stopped being true -- which is exactly what
    happened here when `claude-jit-context` 0.6.0 landed in the cache. That old
    assertion is retired rather than flipped in place: reversing which side of the
    fact is expected would make the test pass against either state, pinning nothing.

    This measures the SAME fact -- does an installed release read the field -- in the
    direction the rule's rewritten prose now claims: the NEWEST cached release does.
    Three states, not two: no cache at all is the skip this already was under #524;
    the newest cached release reading `requires` is the pass this now asserts; the
    newest cached release NOT reading it would mean the rule's "It is honoured" prose
    is itself stale (an upstream regression, or a stale cache on this machine) and
    this test is meant to go red exactly the way its predecessor did for #570.
    """
    import glob
    import os

    cache_root = os.path.expanduser(
        "~/.claude/plugins/cache/dpt-plugins/claude-jit-context"
    )
    version_dirs = [
        d
        for d in glob.glob(os.path.join(cache_root, "*"))
        if os.path.isdir(os.path.join(d, "scripts"))
    ]
    if not version_dirs:
        import pytest

        pytest.skip("no claude-jit-context cache on this machine -- untested here")

    def _version_key(path):
        parts = os.path.basename(path).split(".")
        return tuple(int(p) if p.isdigit() else p for p in parts)

    newest = max(version_dirs, key=_version_key)
    scripts = glob.glob(os.path.join(newest, "scripts", "*.sh"))
    hits = []
    for path in scripts:
        with open(path, encoding="utf-8", errors="replace") as fh:
            if "requires" in fh.read():
                hits.append(path)
    assert hits, (
        "the newest cached claude-jit-context release ({}) does not mention "
        "`requires` anywhere under scripts/ -- the rule's rewritten prose claims "
        "the field is honoured as of 0.6.0; re-measure before trusting either "
        "(#570): {}".format(os.path.basename(newest), newest)
    )
