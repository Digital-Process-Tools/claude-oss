"""#539: the fleet-view label names what a lane covers, not what it starts with.

A lane carrying three issues and a lane carrying one rendered identically -- both showed
only the primary issue and a phrase. The count is the load-bearing half: a reader
scanning a fleet must see ``x3`` without reading the phrase. ``fleet_label`` refuses to
render a label when the caller has not stated the full issue set, because a convention
followed only by habit is the thing #539 was filed about in the first place.

Every "must not" is paired with a "must" in the same fixture -- a checker that refuses
everything is not the same as one that renders the right label.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fleet_label as fl  # noqa: E402


def test_single_issue_lane_carries_no_multiplier():
    # Positive control for the "must" half: a genuine one-issue lane renders plainly,
    # so the x1 case is never written and a bundled label's xN is not noise everyone
    # writes out of habit.
    assert fl.fleet_label(534, [534], "auto-update path") == "Lane 534  auto-update path"


def test_bundled_lane_carries_the_count():
    label = fl.fleet_label(534, [534, 537, 495], "auto-update path")
    assert label == "Lane 534 x3  auto-update path"
    assert "537" not in label and "495" not in label  # count, not enumeration
    assert "x3" in label


def test_refuses_when_issues_omitted():
    with pytest.raises(fl.FleetLabelError):
        fl.fleet_label(534, None, "auto-update path")


def test_refuses_empty_issue_list():
    with pytest.raises(fl.FleetLabelError):
        fl.fleet_label(534, [], "auto-update path")


def test_refuses_primary_not_in_bundle():
    with pytest.raises(fl.FleetLabelError):
        fl.fleet_label(534, [537, 495], "auto-update path")


def test_refuses_duplicate_issues():
    with pytest.raises(fl.FleetLabelError):
        fl.fleet_label(534, [534, 534, 537], "auto-update path")


def test_refuses_blank_phrase():
    with pytest.raises(fl.FleetLabelError):
        fl.fleet_label(534, [534], "   ")


def test_cli_prints_the_label(tmp_path):
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fleet_label.py"),
         "534", "534,537,495", "auto-update path"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Lane 534 x3  auto-update path"


def test_cli_refuses_without_full_bundle():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fleet_label.py"),
         "534", "537,495", "auto-update path"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode != 0
    assert "534" in result.stdout
