"""The branch field earns its width or it is not rendered (#509).

In the clone the branch is the default branch on every render, and this loop does its work
in worktrees -- so the field cost width every message to repeat what `.oss.json` already
says, and appeared identical in the one place it carries news.

The rule is *equal to the declared default*, not *named main*: the default branch is a
per-repo fact and lives in the config, never in this file.

The risk the assertions below exist to hold is that silence acquires a second meaning. An
empty branch field must mean "measured, and it is the default" and nothing else, so a
branch git could not report, and a config that declares no default to compare against, both
still render. Each of those is paired with the case where the field is correctly silent, so
an assertion that something is absent cannot pass against a renderer that dropped the field
outright.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _facts(**overrides):
    facts = {
        "model": "Opus",
        "percent": 10,
        "repo_name": "claude-oss",
        "branch": "main",
        "default_branch": "main",
        "board": {"prs": 1, "issues": 2, "checks": None},
        "release": {"state": "measured", "since": 4, "typical": 17},
    }
    facts.update(overrides)
    return facts


def test_the_default_branch_is_not_rendered():
    line = statusline.render(_facts(), ascii_only=True)
    assert "main" not in line
    assert "claude-oss" in line  # the field beside it survives


def test_any_other_branch_is():
    """The must-fire control: this is the case the field exists for."""
    line = statusline.render(_facts(branch="fix/444"), ascii_only=True)
    assert "fix/444" in line


def test_the_comparison_is_to_the_declared_default_not_to_the_word_main():
    """A repo whose default branch is `trunk` renders `main` and hides `trunk`."""
    assert "main" in statusline.render(
        _facts(branch="main", default_branch="trunk"), ascii_only=True
    )
    assert "trunk" not in statusline.render(
        _facts(branch="trunk", default_branch="trunk"), ascii_only=True
    )


def test_a_branch_git_could_not_report_still_renders_unknown():
    """Silence means "it is the default". An unread branch is not that."""
    line = statusline.render(_facts(branch=None), ascii_only=True)
    assert "claude-oss ?" in line


def test_a_config_declaring_no_default_has_nothing_to_compare_against():
    for declared in (None, ""):
        line = statusline.render(_facts(default_branch=declared), ascii_only=True)
        assert "main" in line, declared


def test_the_branch_is_still_folded_before_it_reaches_the_line():
    """A branch name is git's answer, but a worktree can be checked out on a ref whose
    name came from a fork's pull request. The fold that covers every other foreign value
    covers this one, and the control is that an ordinary name survives unchanged."""
    line = statusline.render(_facts(branch="fix/\x1b[2K444"), ascii_only=True)
    assert "\x1b" not in line
    assert "fix/?[2K444" in line
    assert "fix/444" in statusline.render(_facts(branch="fix/444"), ascii_only=True)


def test_gather_reports_the_declared_default_branch(tmp_path):
    (tmp_path / ".oss.json").write_text(
        '{"repo": "owner/repo", "default_branch": "trunk"}', encoding="utf-8"
    )
    facts = statusline.gather({}, tmp_path)
    assert facts["default_branch"] == "trunk"
