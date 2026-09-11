"""#1408: supertool-required.md ships with no provenance-verification section, and this
records a considered decision rather than silently leaving the gap open.

`.claude/jit-context/tools/00-manual/harness-tools-blocked.md`, in the sibling `claude-supertool`
repository, carries a "## This is not a prompt injection" section (added by `claude-supertool#1793`
after a stock reviewer twice read that repo's own tool-redirection block and reported it as
fabricated attacker content) telling a suspicious reader how to verify the block's provenance
(`git log -1 --` / `git show HEAD:` against the rule file's own tracked path). This plugin's own
`supertool-required.md` template -- scaffolded wholesale into every managed repository, including
`claude-supertool`'s own checkout -- carries the identical `mode: block` tool-redirection shape and
no such section at all.

This is deliberately NOT "just add the #1793 section here too". The lane that filed #1408 had
already run a falsification experiment (`claude-supertool#2007`, n=6 cold reads, two body variants)
against `harness-tools-blocked.md` itself, and found the provenance section did not change a fresh
reader's verdict: every reader called the redirection an injection regardless of whether the section
was present. Copying #1793's fix here on the strength of "it worked there" would be acting against
that repo's own measured evidence.

`supertool-required.md`'s own history (#903) additionally shows two observed instances of a
spawned, unbriefed `Explore` reviewer hitting this exact block and correctly treating it as
untrusted content, routing around it via its own already-granted tools -- the safe outcome, with no
provenance section present, because a reader with no `supertool` grant was never going to act on the
block either way. No claude-oss incident has been recorded of a session that DOES hold `supertool`
mistaking this block for a fabricated attack (the failure mode #1793's section exists to prevent).

So the decision recorded in `00-README.md` (`TOOLS_AGENT_RULE_DECISION`) is: no provenance section
is added now, with the reasoning above, and a named trigger for revisiting it -- a real report of a
`supertool`-holding session wrongly treating this block as fabricated, or new evidence from #2007's
own line of experiments. The rule body itself (`TOOLS_SUPERTOOL`) is unchanged: it is a `mode: block`
rule re-injected whole on every refused call (#757), so a decision record belongs in `00-README.md`,
never in the per-refusal body, regardless of what the decision turns out to be.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

README_MD = REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss" / "00-README.md"


def test_00_readme_records_the_1408_decision():
    body = oss_rules.TOOLS_AGENT_RULE_DECISION
    assert "#1408" in body, (
        "00-README.md should cite #1408, the issue that asked whether "
        "supertool-required.md needs a provenance-verification section"
    )
    assert "#2007" in body, (
        "the decision should cite claude-supertool#2007, the falsification experiment "
        "whose finding (the provenance section did not change reader verdict) is why "
        "this is not a bare copy of the #1793 fix"
    )
    assert "#1793" in body, (
        "the decision should name claude-supertool#1793 -- the fix being deliberately "
        "not copied here, and why"
    )


def test_00_readme_names_a_concrete_trigger_to_revisit():
    body = oss_rules.TOOLS_AGENT_RULE_DECISION
    assert "revisit" in body.lower(), (
        "a decision recorded without a stated trigger for revisiting it reads as closed "
        "forever rather than as reasoned and open to new evidence"
    )


def test_rule_body_itself_is_unchanged_by_the_decision():
    """The decision lives in 00-README.md, never in the per-refusal injected body (#757) --
    a block rule re-injects its whole body on every refused call, so growing it here would
    cost every refusal regardless of what the decision says.
    """
    assert "#1408" not in oss_rules.TOOLS_SUPERTOOL
    assert "#2007" not in oss_rules.TOOLS_SUPERTOOL
    assert "#1793" not in oss_rules.TOOLS_SUPERTOOL


def test_installed_00_readme_matches_the_generated_source(tmp_path):
    written = oss_rules.rules(tmp_path)
    assert written["tools"]["00-README.md"] == oss_rules.TOOLS_AGENT_RULE_DECISION


def test_tracked_00_readme_matches_the_constant():
    """The tracked copy this repository's own sessions read must carry the same decision as
    the constant /oss:scaffold writes into every managed repository (#577, #757's own parity
    rule) -- a decision recorded on one side only reaches either every scaffolded repo or
    nobody.
    """

    def _normalise(text):
        return "\n".join(
            line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
        )

    disk = _normalise(README_MD.read_text(encoding="utf-8"))
    constant = _normalise(oss_rules.TOOLS_AGENT_RULE_DECISION)
    assert disk == constant
