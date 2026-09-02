"""#880: a tick performs exactly one dispatch. The mechanism half: `lane_models`
refuses a `--decision` call that records the same issue as a fresh dispatch
(`dispatch_state` DISPATCHED, the default) more than once in one call -- resuming a
lane's own agent, or a genuine second spawn because it is `agent-unreachable`, are
not fresh dispatches and do not trip the refusal.

Every "must refuse" case is paired with a "must accept" case in the same fixture,
per this repo's own rule that a refusal-only suite cannot tell a real refusal from
a test that never triggers the code path.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

WINDOW = "lanes dispatched this tick"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------- library-level


def test_dispatch_state_defaults_to_dispatched_when_omitted():
    """History recorded before this field existed reads as an ordinary fresh
    dispatch -- the only honest default for a field that cannot retroactively
    ask a question of the past."""
    record = oss_state.lane_models(
        [{"issue": 1, "model": "sonnet", "choice": "default"}], window=WINDOW
    )
    assert record["lanes"][0]["dispatch_state"] == oss_state.DISPATCH_STATE_DISPATCHED
    assert record["lanes"][0]["dispatch_state_why"] is None


def test_dispatch_state_resumed_needs_no_why():
    record = oss_state.lane_models(
        [
            {
                "issue": 1,
                "model": "sonnet",
                "choice": "default",
                "dispatch_state": "resumed",
            }
        ],
        window=WINDOW,
    )
    assert record["lanes"][0]["dispatch_state"] == "resumed"


def test_dispatch_state_rejects_an_unknown_word():
    with pytest.raises(oss_state.StateError, match="dispatch_state"):
        oss_state.lane_models(
            [
                {
                    "issue": 1,
                    "model": "sonnet",
                    "choice": "default",
                    "dispatch_state": "reincarnated",
                }
            ],
            window=WINDOW,
        )


def test_agent_unreachable_without_why_is_refused():
    with pytest.raises(oss_state.StateError, match="dispatch_state_why"):
        oss_state.lane_models(
            [
                {
                    "issue": 1,
                    "model": "sonnet",
                    "choice": "default",
                    "dispatch_state": "agent-unreachable",
                }
            ],
            window=WINDOW,
        )


def test_agent_unreachable_with_why_is_accepted():
    """Positive control for the refusal above."""
    record = oss_state.lane_models(
        [
            {
                "issue": 1,
                "model": "sonnet",
                "choice": "default",
                "dispatch_state": "agent-unreachable",
                "dispatch_state_why": "context died",
            }
        ],
        window=WINDOW,
    )
    assert record["lanes"][0]["dispatch_state_why"] == "context died"


def test_two_fresh_dispatches_of_the_same_issue_are_refused():
    """The core of #880: this is what a re-dispatched lane, recorded honestly,
    looks like -- and it must not silently pass."""
    with pytest.raises(oss_state.StateError, match="#880"):
        oss_state.lane_models(
            [
                {"issue": 880, "model": "sonnet", "choice": "default"},
                {"issue": 880, "model": "sonnet", "choice": "default"},
            ],
            window=WINDOW,
        )


def test_a_dispatch_followed_by_a_legitimate_agent_unreachable_respawn_is_accepted():
    """Positive control for the refusal above: only one of the two entries is a
    fresh DISPATCHED claim, so this is not the #880 shape."""
    record = oss_state.lane_models(
        [
            {"issue": 880, "model": "sonnet", "choice": "default"},
            {
                "issue": 880,
                "model": "sonnet",
                "choice": "default",
                "dispatch_state": "agent-unreachable",
                "dispatch_state_why": "resumed and silent twice",
            },
        ],
        window=WINDOW,
    )
    assert len(record["lanes"]) == 2


def test_two_resumed_records_for_the_same_issue_are_not_a_redispatch():
    """A resume is never a fresh dispatch at all -- recording it twice (an
    unusual but not incoherent thing to do) must not trip the #880 refusal."""
    record = oss_state.lane_models(
        [
            {
                "issue": 880,
                "model": "sonnet",
                "choice": "default",
                "dispatch_state": "resumed",
            },
            {
                "issue": 880,
                "model": "sonnet",
                "choice": "default",
                "dispatch_state": "resumed",
            },
        ],
        window=WINDOW,
    )
    assert len(record["lanes"]) == 2


def test_two_fresh_dispatches_of_the_same_issue_are_refused_across_int_and_str():
    """Found by review: the CLI's own issue parser always converts identically
    for identical input text, so this shape never reaches the CLI -- but a
    caller building lane dicts directly (a test fixture, a future non-CLI
    caller) can hand issue=880 and issue='880' for the same issue, and the
    counting dict used to key on the raw, unconverted value, silently
    accepting the exact re-dispatch #880 exists to catch."""
    with pytest.raises(oss_state.StateError, match="#880"):
        oss_state.lane_models(
            [
                {"issue": 880, "model": "sonnet", "choice": "default"},
                {"issue": "880", "model": "opus", "choice": "default"},
            ],
            window=WINDOW,
        )


def test_two_different_issues_each_dispatched_once_is_fine():
    """Negative control: an ordinary two-lane tick must not be mistaken for a
    redispatch just because two entries exist."""
    record = oss_state.lane_models(
        [
            {"issue": 880, "model": "sonnet", "choice": "default"},
            {"issue": 855, "model": "sonnet", "choice": "default"},
        ],
        window=WINDOW,
    )
    assert len(record["lanes"]) == 2


def test_lane_models_line_surfaces_resumed_and_agent_unreachable_counts():
    record = oss_state.lane_models(
        [
            {
                "issue": 880,
                "model": "sonnet",
                "choice": "default",
                "dispatch_state": "resumed",
            },
        ],
        window=WINDOW,
    )
    line = oss_state.lane_models_line(record)
    assert "1 resumed, 0 agent-unreachable" in line


def test_lane_models_line_says_nothing_extra_for_an_ordinary_mix():
    """Negative control: a tick with no resume and no agent-unreachable lane
    must not carry the parenthetical at all."""
    record = oss_state.lane_models(
        [{"issue": 1, "model": "sonnet", "choice": "default"}], window=WINDOW
    )
    line = oss_state.lane_models_line(record)
    assert "resumed" not in line
    assert "agent-unreachable" not in line


def test_lane_model_trend_accumulates_resumed_and_unreachable():
    entries = [
        {
            "detail": {
                "lanes": {
                    "state": "recorded",
                    "lanes": [
                        {
                            "issue": 880,
                            "model": "sonnet",
                            "choice": "default",
                            "dispatch_state": "resumed",
                        }
                    ],
                }
            }
        },
        {
            "detail": {
                "lanes": {
                    "state": "recorded",
                    "lanes": [
                        {
                            "issue": 855,
                            "model": "sonnet",
                            "choice": "default",
                            "dispatch_state": "agent-unreachable",
                            "dispatch_state_why": "context died",
                        }
                    ],
                }
            }
        },
    ]
    trend = oss_state.lane_model_trend(entries)
    assert trend["resumed"] == 1
    assert trend["unreachable"] == 1


# --------------------------------------------------------- CLI-level


def test_cli_lane_dispatch_state_argument_parses():
    entry = oss_state._lane_dispatch_state_argument("880=resumed:CI fix")
    assert entry == {"issue": 880, "dispatch_state": "resumed", "dispatch_state_why": "CI fix"}


def test_cli_lane_dispatch_state_argument_requires_a_state():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        oss_state._lane_dispatch_state_argument("880=")


def test_cli_attaches_dispatch_state_to_the_matching_lane(tmp_path):
    state_path = tmp_path / "state.json"
    result = _piped(
        [
            str(state_path),
            "--decision",
            "test",
            "--at",
            "2026-09-02T22:00:00Z",
            "--lane",
            "880=sonnet:default",
            "--lane-window",
            "test",
            "--lane-dispatch-state",
            "880=resumed:CI fix",
        ]
    )
    assert result.returncode == 0, result.stdout
    assert "1 resumed, 0 agent-unreachable" in result.stdout
    assert '"dispatch_state": "resumed"' in result.stdout
    assert '"dispatch_state_why": "CI fix"' in result.stdout


def test_cli_refuses_a_genuine_redispatch(tmp_path):
    """The end-to-end shape of #880's own defect: the maintainer's actual tool
    call now catches it, not just the library function."""
    state_path = tmp_path / "state.json"
    result = _piped(
        [
            str(state_path),
            "--decision",
            "test",
            "--at",
            "2026-09-02T22:00:00Z",
            "--lane",
            "880=sonnet:default",
            "--lane",
            "880=sonnet:default",
            "--lane-window",
            "test",
        ]
    )
    assert result.returncode != 0
    assert "#880" in result.stdout


def test_cli_accepts_a_normal_single_dispatch(tmp_path):
    """Positive control for the refusal above: an ordinary single dispatch of
    one issue must not be caught by the same check."""
    state_path = tmp_path / "state.json"
    result = _piped(
        [
            str(state_path),
            "--decision",
            "test",
            "--at",
            "2026-09-02T22:00:00Z",
            "--lane",
            "880=sonnet:default",
            "--lane-window",
            "test",
        ]
    )
    assert result.returncode == 0, result.stdout


def test_cli_fifo_matches_two_lane_dispatch_state_entries_to_two_lane_entries_in_order(tmp_path):
    """The one shape the FIFO-per-issue design exists for (found by review): two
    --lane entries for the same issue -- an abandoned dispatch and its
    agent-unreachable respawn -- each getting its OWN --lane-dispatch-state,
    in the order both were given, not a dict collapsing to the last value or
    an off-by-one swap. This is the actual CLI path; the library-level test
    above only exercises the same shape with pre-built dicts."""
    state_path = tmp_path / "state.json"
    result = _piped(
        [
            str(state_path),
            "--decision",
            "test",
            "--at",
            "2026-09-02T22:00:00Z",
            "--lane",
            "880=sonnet:default",
            "--lane",
            "880=opus:override:second attempt",
            "--lane-window",
            "test",
            "--lane-dispatch-state",
            "880=dispatched",
            "--lane-dispatch-state",
            "880=agent-unreachable:context died",
        ]
    )
    assert result.returncode == 0, result.stdout
    import json
    import re

    match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
    entry = json.loads(match.group(0))
    lanes = entry["detail"]["lanes"]["lanes"]
    assert len(lanes) == 2
    assert lanes[0]["model"] == "sonnet"
    assert lanes[0]["dispatch_state"] == "dispatched"
    assert lanes[1]["model"] == "opus"
    assert lanes[1]["dispatch_state"] == "agent-unreachable"
    assert lanes[1]["dispatch_state_why"] == "context died"


def test_cli_fifo_order_reversed_would_be_caught():
    """Negative control for the test above: swap which entry gets which state
    and confirm the assertions would fail -- proving the test above actually
    pins the order rather than passing on either arrangement."""
    lanes = [
        {"model": "sonnet", "dispatch_state": "agent-unreachable"},
        {"model": "opus", "dispatch_state": "dispatched"},
    ]
    assert not (lanes[0]["model"] == "sonnet" and lanes[0]["dispatch_state"] == "dispatched")


def test_cli_refuses_lane_dispatch_state_with_no_matching_lane(tmp_path):
    state_path = tmp_path / "state.json"
    result = _piped(
        [
            str(state_path),
            "--decision",
            "test",
            "--at",
            "2026-09-02T22:00:00Z",
            "--lane-dispatch-state",
            "999=resumed",
        ]
    )
    assert result.returncode != 0
    assert "no matching --lane" in result.stdout


