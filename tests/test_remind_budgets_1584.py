"""#1584 part two: size budgets for jit-context `remind`-mode bodies.

`scripts/remind_budgets.py` is the missing fourth-plus-one budget module (same shape as
`agent_budgets.py` / `skill_phases.py` / `command_budgets.py` / `claude_md_budget.py`),
covering the five `remind` bodies #1584 shrank. This is its test, the same shape as
`tests/test_claude_md_own_budget_1556.py`.

Not asserted here: whether every remind body in the corpus is covered -- #1584's own body
names four further siblings above 2,500 B left for a follow-up sweep. What this asserts:
the five bodies actually shrunk stay shrunk, a crossing fails loudly, and the third
('missing') state does not silently read as clean.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import remind_budgets  # noqa: E402


def test_every_budgeted_remind_body_is_at_or_under_its_budget():
    results = remind_budgets.check()
    over = [r for r in results if r["state"] == "over"]
    assert not over, "over budget (#1584), replace-don't-append: " + ", ".join(
        f"{r['path']} is {r['size']}B against a budget of {r['budget']}B" for r in over
    )


def test_check_reports_missing_rather_than_silently_passing():
    # Third state: a budgeted path that vanished must not read as "ok" just
    # because there is nothing there to be over budget.
    orig = remind_budgets.BUDGETS
    remind_budgets.BUDGETS = {"does-not-exist-1584.md": (10, 20)}
    try:
        results = remind_budgets.check()
    finally:
        remind_budgets.BUDGETS = orig
    assert results == [
        {
            "path": "does-not-exist-1584.md",
            "state": "missing",
            "size": None,
            "budget": 20,
            "baseline": 10,
        }
    ]


def test_check_flags_a_file_that_grew_past_its_budget():
    # Positive control paired with the two silence-preserving tests above:
    # the check must actually fire, not just refrain from firing.
    orig = remind_budgets.BUDGETS
    remind_budgets.BUDGETS = {"CHANGELOG.md": (1, 2)}
    try:
        results = remind_budgets.check()
    finally:
        remind_budgets.BUDGETS = orig
    assert results[0]["state"] == "over"
    assert results[0]["size"] > 2


def test_repo_root_finds_the_git_checkout():
    root = remind_budgets.repo_root()
    assert (root / ".git").exists()
