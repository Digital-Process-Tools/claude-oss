"""#757: `.claude/jit-context/tools/01-oss/supertool-required.md` is a `mode: block` rule on
`Read|Edit|Write|Glob|Grep` matched with `match: ~.*`. A block rule injects its whole body on
every refused call -- no `once` marker exists for the block branch in `pre-tool-hook.sh` -- so
its byte count is paid on every single refusal, repeated across a session. Before this issue the
file measured 90 lines / 5719 bytes, carrying both the load-bearing op substitutions and a long
explanation of the `requires:` frontmatter and the #524/#570 narrowing rationale that a reader
only needs once, not on every refusal.

This pins the file under 1 KB, that the load-bearing content (five op substitutions and the
`supertool 'ops'` triage) survived the trim verbatim, that the frontmatter fields that govern
enforcement (`tool`/`match`/`mode`) are byte-identical to before, and -- as a negative control --
that the prose which moved to `00-README.md` is actually gone from the injected file rather than
merely duplicated.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

RULE_MD = (
    REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss" / "supertool-required.md"
)
README_MD = REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss" / "00-README.md"

BYTE_CEILING = 1024

#: The five load-bearing op substitutions the issue names explicitly. Each must survive the
#: trim verbatim -- these are the actual replacement commands a blocked agent runs.
LOAD_BEARING_OPS = [
    "supertool 'read:PATH'",
    "supertool 'edit:@-'",
    "supertool 'paste:@-'",
    "supertool 'glob:PATTERN'",
    "supertool 'grep:PATTERN:PATH'",
]

#: The triage instruction the issue names explicitly as load-bearing.
LOAD_BEARING_TRIAGE = [
    "./supertool 'ops'",
    "supertool 'ops'",
]

#: Frontmatter fields that must be byte-identical before and after the trim -- these are the
#: ones that actually govern enforcement, not prose about them.
FROZEN_FRONTMATTER_LINES = [
    "tool: Read|Edit|Write|Glob|Grep",
    "match: ~.*",
    "mode: block",
    "requires: supertool",
]

#: Prose that used to live in the rule body and is now expected to have moved to
#: 00-README.md. A negative control: if this is still in the injected file, the trim did not
#: happen (or happened only in appearance).
MOVED_PROSE_MARKERS = [
    "Why `match: ~.*` and `mode: block` are not narrowed",
    "requires: supertool` frontmatter line, and what it does today",
    "jit_missing_requires()",
]


def test_rule_file_is_under_the_byte_ceiling():
    size = len(RULE_MD.read_bytes())
    assert size < BYTE_CEILING, (
        "supertool-required.md is {} bytes, over the {} byte ceiling -- its whole body "
        "re-injects on every refused Read/Edit/Write/Glob/Grep call, so its size is a "
        "per-refusal cost (#757)".format(size, BYTE_CEILING)
    )


def test_load_bearing_op_substitutions_survive_the_trim():
    body = RULE_MD.read_text(encoding="utf-8")
    missing = [op for op in LOAD_BEARING_OPS if op not in body]
    assert not missing, "op substitution(s) lost in the trim: {}".format(missing)


def test_load_bearing_triage_instruction_survives_the_trim():
    body = RULE_MD.read_text(encoding="utf-8")
    missing = [line for line in LOAD_BEARING_TRIAGE if line not in body]
    assert not missing, "triage instruction(s) lost in the trim: {}".format(missing)


def test_enforcement_frontmatter_is_byte_identical():
    body = RULE_MD.read_text(encoding="utf-8")
    missing = [line for line in FROZEN_FRONTMATTER_LINES if line not in body]
    assert not missing, (
        "enforcement-governing frontmatter changed during the trim (must stay byte-identical): "
        "{}".format(missing)
    )


def test_moved_prose_is_actually_gone_from_the_injected_file():
    """Negative control paired with the positive ones above: the point of the trim is that
    this text stops costing anything per refusal, which only holds if it left the injected
    file rather than being kept there in addition to a copy elsewhere.
    """
    body = RULE_MD.read_text(encoding="utf-8")
    still_present = [marker for marker in MOVED_PROSE_MARKERS if marker in body]
    assert not still_present, (
        "prose that was supposed to move out of the per-refusal injected file is still "
        "there: {}".format(still_present)
    )


def test_moved_prose_landed_in_the_readme():
    """The other half of the negative control: the content must not simply have been
    deleted -- it has to be readable somewhere, and 00-README.md is unindexed by the rule
    engine (JIT_ENTRY_SKIP), so it costs nothing per refusal.
    """
    assert README_MD.exists(), (
        "00-README.md does not exist -- the moved prose has nowhere to land"
    )
    readme_body = README_MD.read_text(encoding="utf-8")
    still_missing = [
        marker for marker in MOVED_PROSE_MARKERS if marker not in readme_body
    ]
    assert not still_missing, (
        "prose expected to have moved to 00-README.md is not there either -- it was deleted, "
        "not moved: {}".format(still_missing)
    )


def test_the_readme_body_matches_the_constant_shipped_into_scaffolded_repos():
    """The parity #577 established for the rule, now owed by 00-README.md too.

    #757 made this file load-bearing: `test_supertool_rule_states_the_absent_case_294.py`
    and `test_supertool_rule_requires_field_524.py` now read their moved facts out of it,
    and `scripts/oss_rules.py`'s `TOOLS_AGENT_RULE_DECISION` is what a scaffolded
    repository actually receives. Without this comparison the two directions are
    asymmetric in exactly the way #577's own docstring warns about: a stale `.md` here is
    a file this repository's own sessions read and would eventually notice, while a stale
    constant ships the wrong rationale into somebody else's repository where nobody here
    ever sees it.

    Line endings and trailing whitespace are normalised for the same reason #577
    normalises them -- a Windows checkout's CRLF is not drift -- and nothing else is,
    so a one-sided wording edit still fails.
    """

    def _normalise(text):
        return "\n".join(
            line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
        )

    disk = _normalise(README_MD.read_text(encoding="utf-8"))
    constant = _normalise(oss_rules.TOOLS_AGENT_RULE_DECISION)
    assert disk == constant, (
        "the tracked 00-README.md and scripts/oss_rules.py's TOOLS_AGENT_RULE_DECISION "
        "have drifted. The constant is what /oss:scaffold writes into every managed "
        "repository, and the layer is replaced wholesale on install, so whichever of "
        "these two is stale reaches either every scaffolded repo or nobody (#577, #757)."
    )


def test_the_readme_parity_check_would_catch_a_one_sided_edit():
    """The positive control for the comparison above: a sameness assertion also passes
    when the normaliser flattens everything, so this proves it can still fail.
    """

    def _normalise(text):
        return "\n".join(
            line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
        )

    disk = README_MD.read_text(encoding="utf-8")
    assert _normalise(disk) != _normalise(disk + "a one-sided edit\n"), (
        "the normaliser used by the parity check above collapses a real difference, so "
        "that check cannot fail and pins nothing"
    )
