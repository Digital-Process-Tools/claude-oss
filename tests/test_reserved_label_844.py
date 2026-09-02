"""#844: dispatch selection reads assignees in three states, but a maintainer
deliberately holding an issue open is a fourth fact the board cannot express.
Filed from jbkkz/requivo, against a real incident: a sub-manager tick read
`Assignees: none` correctly and dispatched a lane onto an issue the maintainer
had reserved by hand, off the tracker.

`labels.reserved` is a declared label name, the same optional shape
`labels.filed_by_loop` already is (#762) -- derivable from the tracker by
anyone, rather than recalled from a session handoff nothing later can see.

Every refusal below is paired with an acceptance in the same fixture.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import dispatch_rank  # noqa: E402
import oss_config  # noqa: E402


# --------------------------------------------------------------- oss_config


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


def test_a_config_with_no_reserved_key_is_still_valid():
    config = _valid()
    assert oss_config.validate(config) == []
    assert "reserved" not in config["labels"]


def test_a_declared_reserved_label_validates():
    config = _valid()
    config["labels"]["reserved"] = "reserved"
    assert oss_config.validate(config) == []


def test_an_explicit_null_reserved_validates_as_not_declared():
    config = _valid()
    config["labels"]["reserved"] = None
    assert oss_config.validate(config) == []


@pytest.mark.parametrize("value", ["", "   ", 12, [], {}, True, False])
def test_a_non_label_reserved_value_is_refused(value):
    config = _valid()
    config["labels"]["reserved"] = value
    problems = oss_config.validate(config)
    assert problems, "labels.reserved={!r} validated with no problems".format(value)
    assert any("reserved" in problem for problem in problems), problems


# ------------------------------------------------------------- dispatch_rank


DECLARED = {"priority": [], "filed_by_loop": "loop-filed", "reserved": "reserved"}


def test_an_issue_carrying_the_reserved_label_is_reserved():
    """Positive control's positive half: the label is present, so this must
    read as reserved even though assignees are empty."""
    assert dispatch_rank.reserved(["reserved"], DECLARED) is True


def test_an_issue_without_the_reserved_label_is_not_reserved():
    """Negative control: an ordinary, genuinely free issue must not be
    flagged -- a check that reserves everything is as useless as one that
    reserves nothing."""
    assert dispatch_rank.reserved(["priority-low"], DECLARED) is False


def test_no_declared_spelling_means_never_reserved():
    """An opt-in mechanism: a repo that has not declared a spelling reads
    every issue as unreserved rather than as could-not-tell -- there is
    nothing ambiguous about a label field with no candidate spelling to
    find."""
    assert dispatch_rank.reserved(["reserved"], {"priority": []}) is False


def test_reserved_label_survives_a_none_labels_list():
    assert dispatch_rank.reserved(None, DECLARED) is False
