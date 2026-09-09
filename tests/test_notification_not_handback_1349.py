"""#1349: a task-notification firing is not the same fact as "this sub-manager's
turn ended permanently". A spawned `oss:sub-manager` notified `TICK: completed /
TICK-ENDS: work-started`, and step 7 (before this fix) read that as grounds to
spawn a second `oss:sub-manager` -- the same task-id notified again ~50 minutes
later with more work done in between, so two sub-managers ran concurrently over
the same board for about an hour, duplicating cost and nearly dispatching a fix
for a PR another live session already owned.

`commands/tick.md` step 7's `work-started` handling must therefore say two
things: that "keep working" can mean the *same* sub-manager continuing rather
than always spawning a fresh one, and give the scheduler a concrete way to tell
the two apart -- a live-status check -- before spawning a second sub-manager on
a `work-started` handback.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_content_invariants import _collapse  # noqa: E402

TICK_MD = REPO_ROOT / "commands" / "tick.md"


def _step7_text(text):
    """The step 7 section, from its own heading to the '## If .oss.json is
    missing' heading that follows it in this file."""
    m = re.search(
        r"7\. \*\*Arm the next tick.*?(?=## If)",
        text,
        re.DOTALL,
    )
    return m.group(0) if m else None


def _names_same_sub_manager_can_continue(step7):
    """Does step 7 say a work-started handback can mean the same sub-manager
    keeps going, rather than always implying a fresh spawn?"""
    if step7 is None:
        return None
    return bool(
        re.search(r"same sub-manager", step7)
        and re.search(r"not\b.*always\b.*spawn|spawn.*not\b.*always", step7)
    )


def _names_a_live_status_check(step7):
    """Does step 7 name a concrete way to tell 'still working' apart from
    'genuinely finished' before spawning a second sub-manager -- a ListAgents
    check or a SendMessage status probe carrying the spawn token?"""
    if step7 is None:
        return None
    return bool(re.search(r"ListAgents", step7) and re.search(r"SendMessage", step7))


def test_step7_exists_in_this_file():
    text = _collapse(TICK_MD.read_text(encoding="utf-8"))
    assert _step7_text(text) is not None, "commands/tick.md's step 7 section not found"


def test_step7_says_the_same_sub_manager_can_keep_working():
    text = _collapse(TICK_MD.read_text(encoding="utf-8"))
    step7 = _step7_text(text)
    assert _names_same_sub_manager_can_continue(step7) is True, (
        "commands/tick.md step 7 must say a work-started handback can mean the "
        "same sub-manager continuing, not only a fresh spawn (#1349)"
    )


def test_step7_names_a_live_status_check_before_a_fresh_spawn():
    text = _collapse(TICK_MD.read_text(encoding="utf-8"))
    step7 = _step7_text(text)
    assert _names_a_live_status_check(step7) is True, (
        "commands/tick.md step 7 must give the scheduler a way (ListAgents / a "
        "SendMessage status probe carrying the spawn token) to tell a "
        "still-live sub-manager apart from a genuinely finished one before "
        "spawning a second one on a work-started handback (#1349)"
    )


# --- must-fire controls: prove the checks can actually fail ----------------


_OLD_BUGGY_STEP7 = (
    "7. **Arm the next tick, and keep working in this one.** This step is this "
    "session's own, not the sub-manager's -- it has no ScheduleWakeup tool and "
    "is gone by the time this runs. Use what the handback said above to "
    "decide: spawn another sub-manager right away if there is more to do this "
    "session, or arm the wakeup below and stop for now. On a completed "
    "handback the decision reads the TICK-ENDS field directly rather than "
    "parsing the paragraph for it: work-started keeps working, blocked and "
    "nothing-left both arm the wakeup below."
    "\n\n## If .oss.json is missing\n"
)


def test_the_same_sub_manager_check_fires_on_the_buggy_wording():
    step7 = _step7_text(_collapse(_OLD_BUGGY_STEP7))
    assert step7 is not None
    assert _names_same_sub_manager_can_continue(step7) is not True


def test_the_live_status_check_fires_on_the_buggy_wording():
    step7 = _step7_text(_collapse(_OLD_BUGGY_STEP7))
    assert step7 is not None
    assert _names_a_live_status_check(step7) is not True


def test_the_facts_are_findable_in_the_fixed_file_but_not_the_buggy_control():
    text = _collapse(TICK_MD.read_text(encoding="utf-8"))
    fixed = _step7_text(text)
    buggy = _step7_text(_collapse(_OLD_BUGGY_STEP7))
    assert _names_same_sub_manager_can_continue(
        fixed
    ) != _names_same_sub_manager_can_continue(buggy)
    assert _names_a_live_status_check(fixed) != _names_a_live_status_check(buggy)
