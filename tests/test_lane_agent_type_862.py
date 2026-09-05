"""#862: a lane dispatched as `general-purpose` instead of `oss:developer` renders
identically to a correctly dispatched one -- nothing anywhere records what a lane was
actually spawned as. This module pins the observable half of the fix: `--lane-agent-type
ISSUE=TYPE` beside `--lane`, closed against `oss:developer`/`oss:triager`, surfaced as a
finding in the mix sentence rather than folded into a silent pass.

Every "must not" is paired with a "must", in the same fixture, per this repo's own rule.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

WINDOW = "lanes dispatched this tick"


def test_known_agent_types_are_the_two_dispatch_definitions():
    assert oss_state.KNOWN_AGENT_TYPES == ("oss:developer", "oss:triager")


def test_lane_models_accepts_an_optional_agent_type():
    record = oss_state.lane_models(
        [
            {
                "issue": 1,
                "model": "sonnet",
                "choice": "default",
                "agent_type": "oss:developer",
            }
        ],
        window=WINDOW,
    )
    assert record["lanes"][0]["agent_type"] == "oss:developer"


def test_lane_models_agent_type_defaults_to_none_when_not_given():
    """Positive control for the negative below: an ordinary lane record, carrying no
    opinion about agent_type at all, must not be treated as an anomaly.
    """
    record = oss_state.lane_models(
        [{"issue": 1, "model": "sonnet", "choice": "default"}], window=WINDOW
    )
    assert record["lanes"][0]["agent_type"] is None
    line = oss_state.lane_models_line(record)
    assert "not oss:developer/oss:triager" not in line


def test_lane_models_line_flags_a_lane_dispatched_outside_the_known_set():
    """The #862 shape itself: a lane whose recorded agent_type is `general-purpose`
    must render as a finding in the mix sentence, not disappear into the count.
    """
    record = oss_state.lane_models(
        [
            {
                "issue": 851,
                "model": "sonnet",
                "choice": "default",
                "agent_type": "general-purpose",
            }
        ],
        window=WINDOW,
    )
    line = oss_state.lane_models_line(record)
    assert "#851" in line
    assert "general-purpose" in line
    assert "not oss:developer/oss:triager" in line


def test_lane_models_line_does_not_flag_the_known_types():
    for agent_type in oss_state.KNOWN_AGENT_TYPES:
        record = oss_state.lane_models(
            [
                {
                    "issue": 1,
                    "model": "sonnet",
                    "choice": "default",
                    "agent_type": agent_type,
                }
            ],
            window=WINDOW,
        )
        line = oss_state.lane_models_line(record)
        assert "not oss:developer/oss:triager" not in line, (agent_type, line)


def _lane_agent_type_argument_direct(text):
    return oss_state._lane_agent_type_argument(text)


def test_lane_agent_type_cli_argument_parses_issue_and_type():
    parsed = _lane_agent_type_argument_direct("851=general-purpose")
    assert parsed == {"issue": 851, "agent_type": "general-purpose"}


def test_lane_agent_type_cli_argument_refuses_missing_equals():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _lane_agent_type_argument_direct("851")


def _run_cli(tmp_path, argv):
    state_path = tmp_path / "state.json"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py"), str(state_path)]
        + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ), state_path


def test_cli_lane_agent_type_attaches_to_the_matching_lane(tmp_path):
    result, state_path = _run_cli(
        tmp_path,
        [
            "--decision",
            "delegate",
            "--at",
            "2026-09-02T00:00:00Z",
            "--lane",
            "851=sonnet:default",
            "--lane-agent-type",
            "851=general-purpose",
            "--lane-window",
            WINDOW,
        ],
    )
    assert result.returncode == 0, result.stdout
    import json

    history = json.loads(state_path.read_text(encoding="utf-8"))
    lane = history[-1]["detail"]["lanes"]["lanes"][0]
    assert lane["agent_type"] == "general-purpose"


def test_cli_lane_agent_type_refuses_without_a_matching_lane(tmp_path):
    result, _ = _run_cli(
        tmp_path,
        [
            "--decision",
            "delegate",
            "--at",
            "2026-09-02T00:00:00Z",
            "--lane-agent-type",
            "999=general-purpose",
            "--lane-window",
            WINDOW,
        ],
    )
    assert result.returncode != 0
    assert "999" in result.stdout


def test_lane_model_trend_carries_the_anomaly_across_a_history():
    """Review finding on #862's own fix: `lane_model_trend`'s `lanes` is a count, not
    a list, so the single-tick anomaly scan in `_lane_models_sentence` never sees it
    for `--model-trend` -- the aggregate view most likely to be read for a pattern
    across ticks. `lane_model_trend` must carry the anomaly forward on its own, and
    `lane_models_line` must render it for a trend record the same way it does for a
    single tick's.
    """
    entries = [
        {
            "at": "2026-09-02T00:00:00Z",
            "decision": "delegate",
            "detail": {
                "lanes": oss_state.lane_models(
                    [
                        {
                            "issue": 851,
                            "model": "sonnet",
                            "choice": "default",
                            "agent_type": "general-purpose",
                        }
                    ],
                    window=WINDOW,
                )
            },
        }
    ]
    trend = oss_state.lane_model_trend(entries)
    line = oss_state.lane_models_line(trend)
    assert "#851" in line
    assert "general-purpose" in line
    assert "not oss:developer/oss:triager" in line


def test_lane_model_trend_does_not_flag_an_ordinary_history():
    """Positive control: a trend built entirely from lanes with no agent_type opinion
    at all must not read as anomalous.
    """
    entries = [
        {
            "at": "2026-09-02T00:00:00Z",
            "decision": "delegate",
            "detail": {
                "lanes": oss_state.lane_models(
                    [{"issue": 1, "model": "sonnet", "choice": "default"}],
                    window=WINDOW,
                )
            },
        }
    ]
    trend = oss_state.lane_model_trend(entries)
    line = oss_state.lane_models_line(trend)
    assert "not oss:developer/oss:triager" not in line
