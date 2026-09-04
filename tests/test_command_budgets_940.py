"""#940: `commands/tick.md` is 3rd-largest prose file in the loop and nothing
budgeted it -- `agent_budgets.py` covers `agents/*.md`, `skill_phases.py`
covers `skills/manager/**`, `commands/` fell through the gap. Same shape as
both, deliberately: the module docstring in `agent_budgets.py` already gives
the argument (turn-1 context, bytes x turns) and it applies to a file every
tick reads with the same force -- restated briefly here, not duplicated.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import command_budgets  # noqa: E402


def test_every_budgeted_command_is_at_or_under_its_budget():
    results = command_budgets.check()
    over = [r for r in results if r["state"] == "over"]
    assert not over, "over budget (#940), replace-don't-append: " + ", ".join(
        f"{r['path']} is {r['size']}B against a budget of {r['budget']}B"
        for r in over
    )


def test_check_reports_missing_rather_than_silently_passing():
    orig = command_budgets.BUDGETS
    command_budgets.BUDGETS = {"commands/does-not-exist-940.md": (10, 20)}
    try:
        results = command_budgets.check()
    finally:
        command_budgets.BUDGETS = orig
    assert results == [
        {
            "path": "commands/does-not-exist-940.md",
            "state": "missing",
            "size": None,
            "budget": 20,
            "baseline": 10,
        }
    ]


def test_check_flags_a_file_that_grew_past_its_budget():
    # Positive control paired with the missing-file test above: the check
    # must actually fire, not just refrain from firing.
    orig = command_budgets.BUDGETS
    command_budgets.BUDGETS = {"CHANGELOG.md": (1, 2)}
    try:
        results = command_budgets.check()
    finally:
        command_budgets.BUDGETS = orig
    assert results[0]["state"] == "over"
    assert results[0]["size"] > 2


def test_tick_md_is_budgeted():
    # #940's own subject: a new commands/*.md file must not silently escape
    # the budget the way tick.md did before this module existed.
    assert "commands/tick.md" in command_budgets.BUDGETS


def test_repo_root_finds_the_git_checkout():
    root = command_budgets.repo_root()
    assert (root / ".git").exists()
