"""#903: supertool-required.md fires on a spawned read-only reviewer too.

The rule (`TOOLS_SUPERTOOL`, rendered as `01-oss/tools/supertool-required.md`) is `mode:
block` on `Read|Edit|Write|Glob|Grep` with `match: ~.*`. It fires on every matching call
in the tree -- including a spawned `Explore` reviewer's own Read/Edit/Write/Glob/Grep
calls during a developer lane's self-review, which is what #903 reported.

Narrowing the trigger to exclude a spawned subagent was considered and is not possible
today: the PreToolUse hook payload this rule is matched against carries no field naming
which agent (main session vs. a dispatched subagent) issued the call, so there is no
signal in the subject to narrow on. The fix landed here is the "state it explicitly"
branch the issue offered as an alternative to narrowing -- `00-README.md`
(`TOOLS_AGENT_RULE_DECISION`) is the file `supertool-required.md`'s own body points a
reader at for exactly this kind of "why does this rule stay this wide" question, so the
statement belongs there.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402


def test_00_readme_states_the_rule_reaches_a_spawned_subagent_too():
    body = oss_rules.TOOLS_AGENT_RULE_DECISION
    assert "#903" in body, (
        "00-README.md should cite #903 where it states whether "
        "supertool-required.md reaches a spawned subagent"
    )
    assert "no field" in body or "no signal" in body, (
        "the statement should say WHY narrowing is not possible today: the hook "
        "payload carries nothing naming which agent issued the call"
    )


def test_00_readme_gives_guidance_for_an_unbriefed_subagent_that_hits_the_block():
    body = oss_rules.TOOLS_AGENT_RULE_DECISION
    assert "Explore" in body, (
        "the guidance should name the concrete case #903 reported (an Explore "
        "reviewer), not just speak abstractly of 'a subagent'"
    )


def test_installed_00_readme_matches_the_generated_source(tmp_path):
    written = oss_rules.rules(tmp_path)
    assert written["tools"]["00-README.md"] == oss_rules.TOOLS_AGENT_RULE_DECISION
