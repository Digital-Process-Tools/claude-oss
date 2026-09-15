"""#1567: a red lane whose own context has grown large may be re-spawned fresh
instead of resumed, and that is its own dispatch state.

`skills/manager/phases/dispatch.md` used to allow exactly two answers for a red
lane: resume it, or record `agent-unreachable`. Measured on 2026-09-15, a resumed
lane spent 15,558,821 tokens across 38 turns at an average call-time context of
409,443 -- within 3% of its own maximum, because it was already at its ceiling
when the message arrived. The rule priced the fresh spawn and never priced the
resume.

`respawned-for-cost` is the third answer. It must not be foldable into either of
the other two: a lane re-spawned because resuming it was too expensive and a lane
re-spawned because its agent was gone are different facts, and #880's whole
subject is that a second fresh spawn with no recorded reason is the defect.

Every "must refuse" case is paired with a "must accept" case in the same fixture,
per this repo's rule that a refusal-only suite cannot tell a real refusal from a
test that never reaches the code path.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

WINDOW = "lanes dispatched this tick"
WHY = "lane at 421,672 context; resume would pay that on every turn"


def _lane(issue, state=None, why=None):
    lane = {"issue": issue, "model": "sonnet", "choice": "default"}
    if state is not None:
        lane["dispatch_state"] = state
    if why is not None:
        lane["dispatch_state_why"] = why
    return lane


# --------------------------------------------------------- the state exists


def test_respawned_for_cost_is_a_declared_state():
    """It is one of the states, not a free string a caller can spell any way."""
    assert oss_state.DISPATCH_STATE_RESPAWNED_FOR_COST == "respawned-for-cost"
    assert oss_state.DISPATCH_STATE_RESPAWNED_FOR_COST in oss_state.DISPATCH_STATES


def test_respawned_for_cost_is_distinct_from_the_other_two():
    """Positive control for the negative assertions below: the three states are
    three, so a test asserting one is not another is asserting on something that
    exists rather than passing because nothing does."""
    assert (
        oss_state.DISPATCH_STATE_RESPAWNED_FOR_COST != oss_state.DISPATCH_STATE_RESUMED
    )
    assert (
        oss_state.DISPATCH_STATE_RESPAWNED_FOR_COST
        != oss_state.DISPATCH_STATE_AGENT_UNREACHABLE
    )
    assert (
        oss_state.DISPATCH_STATE_RESPAWNED_FOR_COST
        != oss_state.DISPATCH_STATE_DISPATCHED
    )


# --------------------------------------------------------- why is required


def test_respawned_for_cost_without_why_is_refused():
    """A cost claim with no measurement behind it is indistinguishable from an
    excuse -- the same argument agent-unreachable's own why requirement makes."""
    with pytest.raises(oss_state.StateError) as excinfo:
        oss_state.lane_models([_lane(1, "respawned-for-cost")], window=WINDOW)
    message = str(excinfo.value)
    assert "respawned-for-cost" in message
    assert "dispatch_state_why" in message


def test_respawned_for_cost_with_why_is_accepted():
    """The positive control for the refusal above."""
    record = oss_state.lane_models([_lane(1, "respawned-for-cost", WHY)], window=WINDOW)
    lane = record["lanes"][0]
    assert lane["dispatch_state"] == "respawned-for-cost"
    assert lane["dispatch_state_why"] == WHY


def test_respawned_for_cost_why_of_only_whitespace_is_refused():
    """A blank reason is an absent reason wearing a value."""
    with pytest.raises(oss_state.StateError):
        oss_state.lane_models([_lane(1, "respawned-for-cost", "   ")], window=WINDOW)


# ------------------------------------------- it is not a second fresh dispatch


def test_respawn_after_a_dispatch_of_the_same_issue_is_accepted():
    """The point of the state. #880 refuses the same issue recorded as a fresh
    dispatch twice; a respawn-for-cost is the second spawn done honestly, so it
    must pass where a second `dispatched` entry is refused."""
    record = oss_state.lane_models(
        [_lane(1), _lane(1, "respawned-for-cost", WHY)], window=WINDOW
    )
    assert len(record["lanes"]) == 2
    assert record["lanes"][1]["dispatch_state"] == "respawned-for-cost"


def test_two_dispatched_entries_for_one_issue_are_still_refused():
    """The positive control for the case above: the #880 refusal still fires, so
    the test above is passing because the new state is exempt and not because the
    guard stopped working."""
    with pytest.raises(oss_state.StateError) as excinfo:
        oss_state.lane_models([_lane(1), _lane(1)], window=WINDOW)
    assert "#880" in str(excinfo.value)


def test_the_880_refusal_names_the_new_state_as_a_route():
    """A refusal that lists only two of the three legal answers sends a caller to
    the wrong one -- the message is the only place most callers read the rule."""
    with pytest.raises(oss_state.StateError) as excinfo:
        oss_state.lane_models([_lane(1), _lane(1)], window=WINDOW)
    assert "respawned-for-cost" in str(excinfo.value)


# --------------------------------------------------------- it is visible


def test_respawned_for_cost_is_counted_in_the_sentence():
    """A mix carrying a cost respawn must not read as an ordinary tick. Same
    argument the resumed/agent-unreachable counts already make."""
    record = oss_state.lane_models(
        [_lane(1), _lane(2, "respawned-for-cost", WHY)], window=WINDOW
    )
    sentence = oss_state.lane_models_line(record)
    assert "respawn" in sentence.lower()


def test_a_tick_with_no_respawn_does_not_mention_one():
    """Positive control: the sentence gains the phrase because a respawn is in
    the mix, not because the phrase is always printed."""
    record = oss_state.lane_models([_lane(1)], window=WINDOW)
    assert "respawn" not in oss_state.lane_models_line(record).lower()


# --------------------------------------------------------- the CLI route


def _piped(argv):
    """argparse wraps help text through textwrap, which breaks on hyphens by
    default -- at a narrow width `agent-unreachable` renders as `agent-` then
    `unreachable` on the next line, and a substring assertion fails on text that
    is present. Found by the positive control below, which failed for exactly
    that reason while the assertion it controls passed. Pinning COLUMNS states
    the width the assertions are read at instead of measuring the terminal the
    suite happens to run in."""
    env = dict(os.environ, COLUMNS="200")
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        env=env,
    )


def test_cli_help_names_the_new_state():
    """`--lane-dispatch-state`'s help is where a sub-manager reads the vocabulary;
    a state the help does not name is a state nobody uses."""
    result = _piped(["--help"])
    assert result.returncode == 0
    assert "respawned-for-cost" in result.stdout


def test_cli_help_still_names_the_old_states():
    """Positive control for the assertion above."""
    result = _piped(["--help"])
    assert "agent-unreachable" in result.stdout
    assert "resumed" in result.stdout
