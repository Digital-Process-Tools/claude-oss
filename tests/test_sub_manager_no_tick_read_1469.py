"""#1469: a sub-manager must never be told to read or follow commands/tick.md.

A sub-manager spawned by the scheduler read agents/sub-manager.md's "read it the
same way out of habit" line as license to open commands/tick.md, whose first
instruction is `Agent(subagent_type: "oss:sub-manager", ...)`, and spawned a
second sub-manager underneath itself instead of running the tick -- three
levels deep, one extra full context paid for nothing (scheduler, sub-manager,
sub-manager, developers).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUB_MANAGER = REPO_ROOT / "agents" / "sub-manager.md"


def _text() -> str:
    return SUB_MANAGER.read_text(encoding="utf-8")


def test_no_habit_instruction_to_read_tick_md():
    text = _text()
    assert "same way out of habit" not in text, (
        "agents/sub-manager.md still tells the sub-manager to read "
        "commands/tick.md 'the same way' (out of habit) -- this is the exact "
        "instruction that led a sub-manager to open the file and act on its "
        "first line (#1469)."
    )


def test_states_tick_md_is_not_for_the_sub_manager_to_read_or_follow():
    text = _text()
    assert "never a script for you to read or" in text, (
        "agents/sub-manager.md should state outright that commands/tick.md is "
        "the scheduler's own spawn wrapper, never a script for the "
        "sub-manager to read or follow (#1469)."
    )


def test_names_the_first_line_spawn_instruction_explicitly():
    text = _text()
    assert 'Agent(subagent_type: "oss:sub-manager"' in text, (
        "agents/sub-manager.md should name commands/tick.md's own first "
        "instruction explicitly, so a sub-manager recognises the spawn as "
        "something that already happened to it rather than a step to repeat "
        "(#1469)."
    )
