"""`TICK: paused` -- #818.

A sub-manager reaching a CI wait has none of the loop's three waiting
mechanisms: no `ScheduleWakeup`, no channel-event delivery (measured on
#816: 6/6 events reached the scheduler, 0/6 reached a concurrently-running
subagent across ten turn boundaries), and `skills/manager/SKILL.md`'s "agents
must not poll CI" is ambiguous about whether it binds the sub-manager, which
is also the orchestrator for its own tick.

Resolution 2 (the one this issue's fix takes): split the wait across the
scheduler/sub-manager boundary that already exists. The scheduler holds the
channel connection and the scheduling tool; the sub-manager holds the tick's
own context. A sub-manager reaching a CI wait hands back a new state --
`paused` -- naming what it is waiting on, and the scheduler waits on the
channel event (or arms a short poll-timer wakeup) for the named observable,
then resumes the *same* sub-manager with `SendMessage`.

`paused` is deliberately not `blocked`: the issue says in as many words that
`blocked` is the wrong existing state, because it reads as ending the tick's
work, and a paused tick is mid-merge -- a lane pushed, a pull request open,
with something concrete expected to change it. The two required fields,
`WAIT-DISPATCH:` and `WAIT-OBSERVABLE:`, reuse the exact vocabulary
`scripts/oss_state.py`'s `--wait-dispatch`/`--wait-observable` already give a
tick closing blocked (#337) -- "what was set in motion" and "what clears
it" -- rather than inventing a second one for the same two facts.

Every negative assertion here carries a positive control in the same
fixture, per this repo's own working rule.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tick_handback.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import tick_handback  # noqa: E402


def test_paused_with_both_wait_fields_classifies():
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825 opened from fix/816, CI running\n"
        "WAIT-OBSERVABLE: PR #825 checks all green or one leg failing\n"
    )
    assert verdict["state"] == "paused"
    assert verdict["declared"] == "paused"
    assert "PR #825 opened" in verdict["wait_dispatch"]
    assert "checks all green" in verdict["wait_observable"]


def test_paused_is_not_blocked():
    """Negative: the issue is explicit that `blocked` is the wrong state for
    work mid-merge -- a paused tick must not collapse onto it."""
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825\n"
        "WAIT-OBSERVABLE: PR #825 goes green\n"
    )
    assert verdict["state"] != "blocked"


def test_positive_control_a_real_blocked_tick_still_classifies_as_blocked():
    """Positive control for the assertion above: an actual `TICK: blocked`
    handback must still classify as `blocked`, so the negative assertion is
    not passing because `blocked` stopped working entirely."""
    verdict = tick_handback.classify(
        "TICK: blocked\nBLOCKER: waiting on a human decision\n"
    )
    assert verdict["state"] == "blocked"


def test_paused_missing_wait_dispatch_is_could_not_classify():
    verdict = tick_handback.classify(
        "TICK: paused\nWAIT-OBSERVABLE: PR #825 goes green\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "paused"


def test_paused_missing_wait_observable_is_could_not_classify():
    verdict = tick_handback.classify(
        "TICK: paused\nWAIT-DISPATCH: PR #825 opened\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "paused"


def test_paused_missing_both_fields_is_could_not_classify():
    verdict = tick_handback.classify("TICK: paused\nwaiting on something\n")
    assert verdict["state"] == "could-not-classify"


def test_positive_control_paused_with_both_fields_is_not_could_not_classify():
    """Positive control for the three tests above: the well-formed paused
    message does not fall into could-not-classify."""
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825\n"
        "WAIT-OBSERVABLE: PR #825 goes green\n"
    )
    assert verdict["state"] != "could-not-classify"


def test_paused_and_returned_nothing_do_not_render_identically():
    paused = tick_handback.classify(
        "TICK: paused\nWAIT-DISPATCH: x\nWAIT-OBSERVABLE: y\n"
    )
    died = tick_handback.classify("")
    assert paused["state"] != died["state"]


def _run(stdin_text, extra_args=()):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *extra_args],
        subject="the verdict and exit code tick_handback.py's CLI produces for a paused tick",
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_exit_code_paused_is_distinct_from_every_other_state():
    paused = _run(
        "TICK: paused\nWAIT-DISPATCH: PR #825\nWAIT-OBSERVABLE: PR #825 goes green\n"
    )
    completed = _run("TICK: completed\nTICK-ENDS: nothing-left\nall clear")
    blocked = _run("TICK: blocked\nBLOCKER: waiting on a human\n")
    could_not_run = _run("TICK: could-not-run\nREASON: spawn refused\n")
    returned_nothing = _run("")
    could_not_classify = _run("no sentinel here at all")
    codes = {
        paused.returncode,
        completed.returncode,
        blocked.returncode,
        could_not_run.returncode,
        returned_nothing.returncode,
        could_not_classify.returncode,
    }
    assert "VERDICT: paused" in paused.stdout
    assert len(codes) == 6, "every state must have a distinct exit code: {}".format(
        (paused.returncode, completed.returncode, blocked.returncode,
         could_not_run.returncode, returned_nothing.returncode,
         could_not_classify.returncode)
    )


def test_cli_prints_wait_fields_for_paused():
    result = _run(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825 opened\n"
        "WAIT-OBSERVABLE: PR #825 checks green\n"
    )
    assert "wait_dispatch: PR #825 opened" in result.stdout
    assert "wait_observable: PR #825 checks green" in result.stdout
