"""#816: nothing in `commands/tick.md` says what the scheduler does with a
lane-level watch-channel event (e.g. `pr_opened`, `checks_failed`) that
arrives while a tick is live. Decided in the issue thread (2026-09-02): the
scheduler treats a lane-level event as situational awareness only -- it
does not diagnose, push, comment on the pull request, or relay it to the
sub-manager, because the running tick already owns and polls its own lanes
-- while board-level events (default branch red, a release published) stay
the scheduler to act on. One narrow exception: the scheduler may probe a
running sub-manager for plain status when its own independent board read
contradicts the assumption that the tick is still progressing.

This pins that the rule is actually stated in commands/tick.md own
scheduler-half prose (beside step 7, not inside the sub-manager numbered
steps), not merely that the file changed.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_content_invariants import _collapse  # noqa: E402

TICK_MD = REPO_ROOT / "commands" / "tick.md"


def _tick_md_text():
    return _collapse(TICK_MD.read_text(encoding="utf-8"))


def test_scheduler_does_not_act_on_lane_level_channel_events():
    text = _tick_md_text()
    # The no-diagnose / no-push / no-comment / no-relay default, stated for
    # lane-level events specifically.
    assert "situational awareness" in text
    assert "does not diagnose" in text or "do not diagnose" in text.lower()
    assert "does not relay" in text or "no relay" in text.lower()


def test_board_level_events_stay_the_schedulers_to_act_on():
    text = _tick_md_text()
    assert "board-level" in text.lower()
    assert "lane-level" in text.lower()


def test_probe_exception_is_named_with_its_condition():
    text = _tick_md_text()
    # The narrow escape hatch: the scheduler may ask (not act), and only
    # when its own independent read contradicts the assumption of progress.
    assert "probe" in text.lower()
    assert "contradicts" in text.lower() or "contradict" in text.lower()


def test_rule_lives_beside_step_7_not_inside_the_sub_managers_numbered_steps():
    """#1037 moved the sub-manager's own numbered steps 1-6 (and "What ends
    a tick") out of commands/tick.md entirely, into
    skills/manager/phases/tick-order.md -- so the physical separation this
    test checks for is now a fact about which FILE the rule is in, not only
    where it sits within one file. The positional half (beside step 7)
    still applies within commands/tick.md, which is what remains here."""
    raw = TICK_MD.read_text(encoding="utf-8")
    step7_idx = raw.find("7. **Arm the next tick")
    assert step7_idx != -1
    situational_idx = raw.find("situational awareness")
    assert situational_idx != -1, (
        "commands/tick.md does not state the channel-event rule at all"
    )
    assert step7_idx < situational_idx, (
        "the channel-event rule must sit in the scheduler's own half of the "
        "file, at or after step 7"
    )
    assert "## What ends a tick" not in raw, (
        "commands/tick.md still carries 'What ends a tick' -- #1037 moved "
        "it to skills/manager/phases/tick-order.md, so a copy left behind "
        "here is a duplicate, not a fix"
    )
