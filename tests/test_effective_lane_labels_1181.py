"""#1181: `lane-other` had four independent readers and no two of them agreed
on whether a declared `labels.lane_other` spelling counts as "this issue is
triaged into a lane". `oss_config.effective_lane_labels` is the one place a
caller holding a loaded config now derives that answer -- `labels.lanes` plus
`labels.lane_other` when it is declared as a non-blank string, deduplicated,
`null`/absent contributing nothing.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def test_lane_other_is_folded_in_when_declared():
    config = {"labels": {"lanes": ["lane-a", "lane-b"], "lane_other": "lane-other"}}
    assert oss_config.effective_lane_labels(config) == [
        "lane-a",
        "lane-b",
        "lane-other",
    ]


def test_null_lane_other_contributes_nothing_the_positive_control():
    """Must-not-fire half: an undeclared lane_other must leave the declared
    lanes list untouched, not silently drop or duplicate an entry."""
    config = {"labels": {"lanes": ["lane-a", "lane-b"], "lane_other": None}}
    assert oss_config.effective_lane_labels(config) == ["lane-a", "lane-b"]


def test_absent_lane_other_contributes_nothing():
    config = {"labels": {"lanes": ["lane-a"]}}
    assert oss_config.effective_lane_labels(config) == ["lane-a"]


def test_lane_other_already_present_in_lanes_is_not_duplicated():
    config = {"labels": {"lanes": ["lane-a", "lane-other"], "lane_other": "lane-other"}}
    assert oss_config.effective_lane_labels(config) == ["lane-a", "lane-other"]


def test_blank_lane_other_string_contributes_nothing():
    config = {"labels": {"lanes": ["lane-a"], "lane_other": "   "}}
    assert oss_config.effective_lane_labels(config) == ["lane-a"]


def test_missing_labels_key_returns_empty_list():
    assert oss_config.effective_lane_labels({}) == []


def test_non_dict_config_returns_empty_list():
    assert oss_config.effective_lane_labels(None) == []
