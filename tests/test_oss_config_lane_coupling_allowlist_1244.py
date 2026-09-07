"""#1244 review finding: `labels.lane_coupling_allowlist` -- the per-repo list
of test-file paths a maintainer has reviewed and confirmed intentionally span
more than one declared lane (`scripts/lane_coupling.py`'s own noise-reduction
mechanism) -- was validated in `scripts/oss_config.py` with zero test
coverage, breaking this repo's own convention of one dedicated test file per
`labels.*` validation branch (`tests/test_oss_config_lane_patterns_1129.py`,
`tests/test_oss_config_lane_other_1130.py`, `tests/test_oss_config_filed_by_
loop_990.py`). Found independently by both self-review spawns on the same PR.

Additive: `labels.lane_patterns` and every other `labels.*` key stay exactly
what they are today, and an existing `.oss.json` with no
`lane_coupling_allowlist` key at all keeps validating unchanged.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402

from test_oss_config import _valid  # noqa: E402


def test_an_existing_config_with_no_lane_coupling_allowlist_key_still_validates():
    config = _valid()
    assert oss_config.validate(config) == []


def test_a_well_formed_lane_coupling_allowlist_validates():
    config = _valid()
    config["labels"]["lane_coupling_allowlist"] = [
        "tests/test_content_invariants.py",
        "tests/test_unwired_scripts_253.py",
    ]
    assert oss_config.validate(config) == []


def test_null_lane_coupling_allowlist_means_not_declared_not_a_typo():
    config = _valid()
    config["labels"]["lane_coupling_allowlist"] = None
    assert oss_config.validate(config) == []


def test_lane_coupling_allowlist_must_be_a_list():
    config = _valid()
    config["labels"]["lane_coupling_allowlist"] = "tests/test_content_invariants.py"
    problems = oss_config.validate(config)
    assert any("labels.lane_coupling_allowlist" in p for p in problems)


def test_lane_coupling_allowlist_elements_must_be_non_empty_strings():
    config = _valid()
    config["labels"]["lane_coupling_allowlist"] = ["tests/test_ok.py", ""]
    problems = oss_config.validate(config)
    assert any("labels.lane_coupling_allowlist" in p for p in problems)


def test_lane_coupling_allowlist_rejects_a_non_string_element():
    config = _valid()
    config["labels"]["lane_coupling_allowlist"] = ["tests/test_ok.py", 5]
    problems = oss_config.validate(config)
    assert any("labels.lane_coupling_allowlist" in p for p in problems)


def test_lane_coupling_allowlist_empty_list_is_fine():
    """Unlike `lane_patterns.<lane>`, an empty allowlist is a real, meaningful
    value (this repo declared zero test files as intentionally cross-lane) --
    not refused the way an empty `lane_patterns` value is."""
    config = _valid()
    config["labels"]["lane_coupling_allowlist"] = []
    assert oss_config.validate(config) == []
