"""#1130: `labels.lane_other` -- the per-repo GitHub label name a triager
applies to an issue that was examined and matches no real lane -- gets the
same opt-in, null-is-fine validation `labels.filed_by_loop` and
`labels.reserved` already have. A repo that has not declared one yet is
not a typo; it is `_derive_lane_patterns_from_labels`'s own "not
configured, never checked" posture at derivation time.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def _valid():
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "~/src/name",
        "worktree_root": "~/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [".claude-plugin/plugin.json"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }


def test_a_declared_lane_other_label_validates():
    config = _valid()
    config["labels"]["lane_other"] = "lane-other"
    assert oss_config.validate(config) == []


def test_a_null_lane_other_label_validates_the_positive_control():
    config = _valid()
    config["labels"]["lane_other"] = None
    assert oss_config.validate(config) == []


def test_an_absent_lane_other_label_validates_too():
    config = _valid()
    assert "lane_other" not in config["labels"]
    assert oss_config.validate(config) == []


def test_a_non_string_lane_other_label_is_refused():
    config = _valid()
    config["labels"]["lane_other"] = 123
    problems = oss_config.validate(config)
    assert any("lane_other" in p for p in problems)


def test_a_blank_lane_other_label_is_refused():
    config = _valid()
    config["labels"]["lane_other"] = "   "
    problems = oss_config.validate(config)
    assert any("lane_other" in p for p in problems)
