"""#491: turn-1 baseline (system prompt + agent definition + brief) is a
median 44% of a whole agent's cache-read consumption, and every byte in an
agent definition is re-read on every one of that agent's turns (median 55,
max 329). Nothing measured that a definition grew until this file existed.

Scope: `agents/*.md` specifically -- the files this repo's own Layout
section names as "agent definitions" (`skills/manager/SKILL.md` and
`CLAUDE.md` are read by the same mechanism but are not agent definitions in
that sense, and #491 does not ask for a budget on every large file, only
"each agent definition").

Not asserted here, and deliberately not attempted: whether any given
paragraph earns its size. That is a judgement call the issue explicitly asks
a human to keep making. What this can and does assert: the size is recorded,
visible, and a crossing fails loudly instead of drifting.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_budgets  # noqa: E402


def test_every_budgeted_definition_is_at_or_under_its_budget():
    results = agent_budgets.check()
    over = [r for r in results if r["state"] == "over"]
    assert not over, "over budget (#491), replace-don't-append: " + ", ".join(
        f"{r['path']} is {r['size']}B against a budget of {r['budget']}B" for r in over
    )


def test_check_reports_missing_rather_than_silently_passing():
    # Third state: a budgeted path that vanished must not read as "ok" just
    # because there is nothing there to be over budget.
    orig = agent_budgets.BUDGETS
    agent_budgets.BUDGETS = {"agents/does-not-exist-491.md": (10, 20)}
    try:
        results = agent_budgets.check()
    finally:
        agent_budgets.BUDGETS = orig
    assert results == [
        {
            "path": "agents/does-not-exist-491.md",
            "state": "missing",
            "size": None,
            "budget": 20,
            "baseline": 10,
        }
    ]


def test_check_flags_a_file_that_grew_past_its_budget():
    # Positive control paired with the two silence-preserving tests above:
    # the check must actually fire, not just refrain from firing.
    orig = agent_budgets.BUDGETS
    agent_budgets.BUDGETS = {"CHANGELOG.md": (1, 2)}
    try:
        results = agent_budgets.check()
    finally:
        agent_budgets.BUDGETS = orig
    assert results[0]["state"] == "over"
    assert results[0]["size"] > 2


def test_every_agents_markdown_file_is_budgeted():
    # A new file dropped into agents/ must not silently escape the budget --
    # the growth-without-a-number failure mode this issue exists to close.
    root = agent_budgets.repo_root()
    on_disk = {p.name for p in (root / "agents").glob("*.md")}
    budgeted = {Path(p).name for p in agent_budgets.BUDGETS}
    assert on_disk == budgeted, f"unbudgeted agents/*.md file(s): {on_disk - budgeted}"


def test_repo_root_finds_the_git_checkout():
    root = agent_budgets.repo_root()
    assert (root / ".git").exists()
