"""#1129: `labels.lane_patterns` -- the per-repo mapping from a `lane-*`
GitHub label to the glob patterns that lane covers, declared in `.oss.json`
so `select_issues.py` can derive a candidate's `lane_patterns` from its
label when the issue carries none of its own. Additive: `labels.lanes`
stays exactly the list it is today, and an existing `.oss.json` with no
`lane_patterns` key at all keeps validating unchanged.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402

from test_oss_config import _valid  # noqa: E402


def test_an_existing_config_with_no_lane_patterns_key_still_validates():
    config = _valid()
    assert oss_config.validate(config) == []


def test_a_well_formed_lane_patterns_mapping_validates():
    config = _valid()
    config["labels"]["lane_patterns"] = {
        "lane-dispatch": ["scripts/select_issues*.py", "scripts/lane_setup*.py"],
        "lane-doctor": ["scripts/doctor.py"],
    }
    assert oss_config.validate(config) == []


def test_null_lane_patterns_means_not_declared_not_a_typo():
    config = _valid()
    config["labels"]["lane_patterns"] = None
    assert oss_config.validate(config) == []


def test_lane_patterns_must_be_an_object():
    config = _valid()
    config["labels"]["lane_patterns"] = ["lane-dispatch"]
    problems = oss_config.validate(config)
    assert any("labels.lane_patterns" in p for p in problems)


def test_lane_patterns_value_must_be_a_non_empty_list_of_strings():
    config = _valid()
    config["labels"]["lane_patterns"] = {"lane-dispatch": "scripts/*.py"}
    problems = oss_config.validate(config)
    assert any("labels.lane_patterns.lane-dispatch" in p for p in problems)


def test_lane_patterns_value_cannot_be_an_empty_list():
    config = _valid()
    config["labels"]["lane_patterns"] = {"lane-dispatch": []}
    problems = oss_config.validate(config)
    assert any("labels.lane_patterns.lane-dispatch" in p for p in problems)
