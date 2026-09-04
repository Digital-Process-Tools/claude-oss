"""#978: agents/sub-manager.md is told (#880) to resume a red lane's own agent
via `SendMessage`, but its frontmatter tool grant never listed `SendMessage`
-- so the mechanism the prose mandates was not available to the agent asked
to perform it. Verified against Claude Code's own sub-agent docs
(code.claude.com/docs/en/sub-agents): `SendMessage` is a documented,
frontmatter-grantable tool, not one reserved for a top-level orchestrating
session, so the fix is to grant it rather than to relabel the rule.

Positive control: sub-manager.md must actually grant it. Negative control: a
document that merely *talks about* SendMessage (dispatch.md, commands/tick.md
-- neither carries a `tools:` frontmatter line at all) is not asserted to
grant it, so this test is scoped to the one file that has a grant to check.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SUB_MANAGER = (REPO_ROOT / "agents" / "sub-manager.md").read_text(encoding="utf-8")


def _frontmatter_tools(text):
    match = re.search(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "no frontmatter block found"
    fm = match.group(1)
    tools_match = re.search(r"^tools:\s*(.+)$", fm, re.MULTILINE)
    assert tools_match, "no tools: line in frontmatter"
    return [t.strip() for t in tools_match.group(1).split(",")]


def test_sub_manager_frontmatter_grants_sendmessage():
    """The tool #880's own resume mechanism needs must actually be granted."""
    tools = _frontmatter_tools(SUB_MANAGER)
    assert "SendMessage" in tools, (
        "agents/sub-manager.md tools: line does not grant SendMessage -- the "
        "resume mechanism #880 mandates in prose is unusable without it: {0}".format(tools)
    )


def test_sub_manager_still_grants_its_prior_tools():
    """Negative control / regression guard: adding SendMessage must not have
    dropped anything the sub-manager already relied on."""
    tools = _frontmatter_tools(SUB_MANAGER)
    for expected in ("Bash", "TodoWrite", "Skill", "Agent"):
        assert expected in tools, "agents/sub-manager.md lost its {0} grant".format(expected)
