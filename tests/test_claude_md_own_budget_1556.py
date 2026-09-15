"""#1556: `CLAUDE.md` was the largest single document any agent in the loop
loads, loaded whole on every session, and the only one of the four budgeted
subjects (`agents/*.md`, `skills/manager/**`, `commands/tick.md` and
`commands/run.md`) with no ceiling and no test. `scripts/claude_md_budget.py`
is the missing fourth module; this is its test, the same shape as
`tests/test_agent_definition_budget_491.py`.

Not asserted here, and deliberately not attempted: whether any given
paragraph earns its size -- that stays a human judgement call, same as every
other budgeted subject. What this asserts: the size is recorded, visible,
and a crossing fails loudly instead of drifting.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_md_budget  # noqa: E402


def test_claude_md_is_at_or_under_its_budget():
    results = claude_md_budget.check()
    over = [r for r in results if r["state"] == "over"]
    assert not over, "over budget (#1556), replace-don't-append: " + ", ".join(
        f"{r['path']} is {r['size']}B against a budget of {r['budget']}B" for r in over
    )


def test_check_reports_missing_rather_than_silently_passing():
    # Third state: a budgeted path that vanished must not read as "ok" just
    # because there is nothing there to be over budget.
    orig = claude_md_budget.BUDGETS
    claude_md_budget.BUDGETS = {"CLAUDE-does-not-exist-1556.md": (10, 20)}
    try:
        results = claude_md_budget.check()
    finally:
        claude_md_budget.BUDGETS = orig
    assert results == [
        {
            "path": "CLAUDE-does-not-exist-1556.md",
            "state": "missing",
            "size": None,
            "budget": 20,
            "baseline": 10,
        }
    ]


def test_check_flags_a_file_that_grew_past_its_budget():
    # Positive control paired with the two silence-preserving tests above:
    # the check must actually fire, not just refrain from firing.
    orig = claude_md_budget.BUDGETS
    claude_md_budget.BUDGETS = {"CHANGELOG.md": (1, 2)}
    try:
        results = claude_md_budget.check()
    finally:
        claude_md_budget.BUDGETS = orig
    assert results[0]["state"] == "over"
    assert results[0]["size"] > 2


def test_repo_root_finds_the_git_checkout():
    root = claude_md_budget.repo_root()
    assert (root / ".git").exists()
