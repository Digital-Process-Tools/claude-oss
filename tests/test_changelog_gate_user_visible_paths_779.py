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


def test_a_perl_only_lookahead_is_refused_grep_e_cannot_parse_it():
    """Found by review (#779): `oss_config.user_visible_paths_problem` used to
    validate with Python's `re.compile`, but the value is spliced into a
    `grep -E` (POSIX ERE) invocation at runtime -- a different grammar.
    `(?=...)` is ordinary Python `re` and a `grep -E` SYNTAX ERROR (exit 2),
    which the generated workflow's `if ! grep -Eq ...; then skip; fi` cannot
    tell apart from a genuine no-match -- so an accepted-but-unparseable
    pattern silently and permanently turns the gate off for the whole repo,
    the exact failure the acceptance bar names by name for an empty list."""
    problem = oss_config.user_visible_paths_problem(["(?=README)"])
    assert problem is not None


def test_a_non_capturing_group_is_refused_same_reason():
    problem = oss_config.user_visible_paths_problem(["(?:docs|README)"])
    assert problem is not None


def test_a_perl_only_backslash_class_is_refused():
    """`\\d`, `\\w`, `\\s`, `\\A`, `\\Z`, `\\b`... are not POSIX ERE. Every
    backslash-letter escape is refused rather than allow-listed one at a
    time, because whether a given one happens to work is a GNU-grep-version
    question this validator cannot answer on the maintainer's own machine."""
    problem = oss_config.user_visible_paths_problem([r"^docs/\d+"])
    assert problem is not None


def test_an_ordinary_ere_pattern_still_validates():
    """Positive control for the three refusals above: a pattern using only
    POSIX ERE syntax -- anchors, character classes, alternation, quantifiers,
    a backslash-escaped metacharacter -- is still accepted."""
    assert oss_config.user_visible_paths_problem(
        [r"^docs/", r"^README\.md$", r"^(docs|tests)/"]
    ) is None


# --------------------------------------------------------- rendered workflow


def test_absent_key_renders_no_exemption_block_pattern():
    """Default: nothing declared, so the generated workflow's exemption guard
    never fires -- the substituted pattern is empty, which makes the `[ -n ]`
    test around it false on every run.

    Caught by review (#779): the earlier version of this assertion,
    `"if [ -n '' ]" in body or "if [ -n \"\" ]" not in body`, was a tautology
    -- the second disjunct is true regardless of what the first substitution
    produced, because the template never uses the double-quoted spelling at
    all. Asserting the exact rendered guard line directly is what actually
    exercises `user_visible_pattern()` returning `""` for an absent key.
    """
    body = scaffold.render_owned(".github/workflows/oss-changelog.yml", _config())
    assert "no user-visible paths changed" in body
    assert "if [ -n '' ]; then" in body


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


# ----------------------------------------------------- real shell execution (#996)
#
# Everything above reads the RENDERED TEXT of the workflow. Its sibling files
# (`tests/test_changelog_gate.py`, `tests/test_bot_pull_request_293.py`,
# `tests/test_changelog_label_live_read_777.py`) all put the extracted `run:` body in
# front of a real git repository and read the exit status instead -- because a defect
# in what the shell actually DOES is invisible to a text assertion (#87 is the reason
# `test_changelog_gate.py` exists at all). This file had none of that until #996: two
# diagnostic passes had to reason about the generated script from outside because
# nothing here ever actually ran it.
#
# Reuses the shared harness (`_gate_script`, `_child_env`, `_pull_request`, `_require`,
# `BASH`) from `tests/test_changelog_gate.py` rather than reinventing shell-extraction
# machinery, exactly as the sibling files already do.

from test_changelog_gate import (  # noqa: E402
    BASH,
    _child_env,
    _config as _shared_config,
    _gate_script,
    _pull_request,
    _require,
    _run_script,
)


def _user_visible_config(**overrides):
    """The shared harness's own `_config()`, with `user_visible_paths` overrides
    layered on top -- this file's local `_config()` above is for the render-only
    tests and is not what `_gate_script()` needs, since the extracted `run:` body
    has to come from the same rendering `_step_script` uses.
    """
    return _shared_config(**overrides)


def _run_gate(repo, config):
    for tool in ("git", "grep", "sed"):
        _require(tool)
    return _run_script(_gate_script(config), repo, _child_env(BASH, BASE_REF="main"))


# A pull request that changes only a path the config below declares user-visible
# (`^docs/`), adds no fragment: the exemption must NOT reach this -- declaring
# `user_visible_paths` narrows what counts, it does not blanket-exempt a repo.
VISIBLE_ONLY = {"docs/guide.md": "a new sentence\n"}

# A pull request that changes only a path OUTSIDE the declared pattern, adds no
# fragment: the shape the exemption exists for.
NOT_VISIBLE_ONLY = {"tests/harness.py": "value = 2\n"}


def test_a_path_not_matching_user_visible_paths_is_skipped_and_says_so(tmp_path):
    """The 'must fire' half of the pair below: a diff that touches only a path the
    config did NOT declare user-visible is exempted, and the receipt says which
    branch fired rather than reading like an ordinary pass or the label escape hatch.
    """
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(tmp_path, NOT_VISIBLE_ONLY)
    done = _run_gate(repo, config)
    assert done.returncode == 0, done.stdout
    assert "skipped (no user-visible paths changed)" in done.stdout, done.stdout


def test_a_path_matching_user_visible_paths_is_still_refused(tmp_path):
    """The 'must not fire' half: a diff that DOES touch a path the config declared
    user-visible is refused exactly as it would be with no config at all --
    declaring `user_visible_paths` narrows the exemption, it does not turn the gate
    off for the paths it names.
    """
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(tmp_path, VISIBLE_ONLY)
    done = _run_gate(repo, config)
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout, done.stdout


def test_with_no_user_visible_paths_configured_the_same_diff_is_still_refused(tmp_path):
    """Positive control for the first test above: without the key declared at all,
    the identical NOT_VISIBLE_ONLY diff is NOT exempted -- proving the skip in the
    first test came from the configured pattern genuinely not matching, not from
    some other branch (`nothing changed`, the label, dependabot) firing instead.
    """
    config = _user_visible_config()
    repo = _pull_request(tmp_path, NOT_VISIBLE_ONLY)
    done = _run_gate(repo, config)
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout, done.stdout


def test_a_fragment_present_still_passes_even_with_user_visible_paths_configured(tmp_path):
    """A fragment satisfies the gate regardless of `user_visible_paths` -- the
    exemption is an additional way to pass, never a narrower way to fail."""
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(
        tmp_path,
        {"src.py": "value = 2\n", "changelog.d/925.fixed.md": "- a fix (#925).\n"},
    )
    done = _run_gate(repo, config)
    assert done.returncode == 0, done.stdout
    assert "925.fixed.md" in done.stdout, done.stdout


def test_deleting_a_fragment_is_refused_even_when_the_rest_of_the_diff_is_user_visible_only(tmp_path):
    """Acceptance bar #1, executed rather than read: the deleted-fragment branch
    sits ABOVE the user-visible-paths exemption, so losing a pending fragment is
    refused even when every OTHER changed path matches the configured pattern.
    """
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(
        tmp_path,
        {"docs/guide.md": "a new sentence\n", "changelog.d/906.added.md": None},
    )
    done = _run_gate(repo, config)
    assert done.returncode == 1, done.stdout
    assert "deleted without being assembled" in done.stdout, done.stdout

