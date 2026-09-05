"""`labels.filed_by_loop`: the label that makes the intake numerator derivable
instead of recalled (#762).

An issue the loop filed and one the maintainer typed by hand carry the same account
and the same auth -- nothing on the tracker tells them apart. `oss_state.intake`'s
`filings` used to be whatever the ticking agent remembered filing during its own
tick. `labels.filed_by_loop` in `.oss.json` is the fix: a label name, declared per
repo the same way `labels.priority`/`labels.lanes` already are, attached to every
issue the loop files, and read back at counting time instead of trusted from memory.

Every "must be refused" case below is paired with an "must be accepted" case in the
same fixture -- a schema loose enough to accept a typo is worse than one that refuses
the correct spelling.
"""

import sys
from pathlib import Path

import pytest

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


def test_a_config_with_no_filed_by_loop_key_is_still_valid():
    """Nothing is invented: a repo that has not declared the label is not refused
    for it, and it is not filled in with a guess either."""
    config = _valid()
    assert oss_config.validate(config) == []
    assert "filed_by_loop" not in config["labels"]


def test_a_declared_label_name_validates():
    config = _valid()
    config["labels"]["filed_by_loop"] = "loop-filed"
    assert oss_config.validate(config) == []


def test_an_explicit_null_validates_as_not_declared():
    """Same shape as `test_command`/`changelog_dir`: null means the maintainer has
    not (yet) declared one, not a typo."""
    config = _valid()
    config["labels"]["filed_by_loop"] = None
    assert oss_config.validate(config) == []


@pytest.mark.parametrize("value", ["", "   ", 12, [], {}, True, False])
def test_a_non_label_value_is_refused(value):
    config = _valid()
    config["labels"]["filed_by_loop"] = value
    problems = oss_config.validate(config)
    assert problems, "labels.filed_by_loop={!r} validated with no problems".format(
        value
    )
    assert any("filed_by_loop" in problem for problem in problems), problems


def test_the_label_name_travels_beside_priority_and_lanes_not_replacing_either():
    config = _valid()
    config["labels"] = {
        "priority": ["priority-high"],
        "lanes": ["lane-docs"],
        "filed_by_loop": "loop-filed",
    }
    assert oss_config.validate(config) == []
