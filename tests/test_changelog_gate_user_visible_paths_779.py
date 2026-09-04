"""#779: `user_visible_paths` -- an optional `.oss.json` key naming regexes for
paths this repository considers user-visible, so a pull request touching only
docs/tests-shaped paths can be exempted from the "add a changelog fragment"
gate without a human applying the `no-changelog` label by hand.

Absent/null is the default and must leave today's behaviour byte-identical:
every non-empty diff with no fragment fails, same as before this key existed.

Three things the acceptance bar names, each with its own test below:

1. The exemption sits BELOW the deleted-fragment branch: `git rm` on a pending
   fragment is refused even when `user_visible_paths` is configured and none
   of the changed paths match it.
2. The value is contributor-writable and validated: an unparseable/empty shape
   is a stated refusal (`oss_config.user_visible_paths_problem`), never a
   silent "nothing is user-visible" that would turn the gate off for the
   whole repo.
3. The receipt names which branch fired: `skipped (no user-visible paths
   changed)` is distinguishable from the pre-existing `skipped (...label...)`
   and `skipped (...dependabot...)` branches and from an ordinary pass.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [".claude-plugin/plugin.json", "README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": ["priority-high"], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


# --------------------------------------------------------- oss_config validation


def test_null_is_fine_the_default_reading():
    assert oss_config.user_visible_paths_problem(None) is None


def test_a_legitimate_list_of_regexes_is_fine():
    assert oss_config.user_visible_paths_problem([r"^docs/", r"^README\.md$"]) is None


def test_not_a_list_is_refused():
    problem = oss_config.user_visible_paths_problem("^docs/")
    assert problem is not None
    assert "user_visible_paths" in problem


def test_an_empty_list_is_refused_not_read_as_nothing_is_user_visible():
    """The acceptance bar's own words: an empty pattern set must not silently
    turn the gate off for the whole repo."""
    problem = oss_config.user_visible_paths_problem([])
    assert problem is not None


def test_an_unparseable_regex_is_refused():
    problem = oss_config.user_visible_paths_problem(["("])
    assert problem is not None


def test_a_single_quote_is_refused_shell_injection_surface():
    """This value is embedded, single-quoted, into a `run:` line of the
    generated workflow (like `changelog_dir` already is) -- a quote character
    would close that literal early."""
    problem = oss_config.user_visible_paths_problem(["docs/'; rm -rf /; echo '"])
    assert problem is not None


# --------------------------------------------------------- rendered workflow


def test_absent_key_renders_no_exemption_block_pattern():
    """Default: nothing declared, so the generated workflow's exemption guard
    never fires -- the substituted pattern is empty."""
    body = scaffold.render_owned(".github/workflows/oss-changelog.yml", _config())
    assert "no user-visible paths changed" in body
    # the guard around it must be shaped so an empty pattern never matches
    assert "if [ -n '' ]" in body or "if [ -n \"\" ]" not in body


def test_a_declared_list_is_rendered_into_the_workflow():
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml",
        _config(user_visible_paths=[r"^docs/", r"^README\.md$"]),
    )
    assert r"^docs/" in body
    assert "no user-visible paths changed" in body


def test_the_exemption_check_sits_below_the_deleted_fragment_branch():
    """Acceptance bar #1: the fragment-deletion refusal must appear earlier in
    the generated script than the new exemption branch."""
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml",
        _config(user_visible_paths=[r"^docs/"]),
    )
    deleted_branch = body.index("deleted without being assembled")
    exemption_branch = body.index("no user-visible paths changed")
    assert deleted_branch < exemption_branch


def test_the_three_skip_receipts_are_distinguishable():
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml",
        _config(user_visible_paths=[r"^docs/"]),
    )
    assert "skipped (no user-visible paths changed)" in body
    # the pre-existing label escape hatch and dependabot exemption still read
    # differently
    assert "'no-changelog' label present" in body
    assert "dependabot" in body


def test_an_unparseable_config_refuses_at_render_time_rather_than_shipping_silently():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render_owned(
            ".github/workflows/oss-changelog.yml",
            _config(user_visible_paths=[]),
        )
