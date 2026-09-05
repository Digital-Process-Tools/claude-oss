"""#564: the scaffolded `.gitignore` ignored `.oss.json` -- the file this loop
calls tracked and authoritative -- while leaving `.oss.local.json`, the actual
machine-specific half, unmentioned by name in the comment beside it.

`#34` split one combined config into two files: `.oss.json` became the project's
answer, tracked and reviewed like any other repo fact, and `.oss.local.json` became
the machine-specific half, git-excluded. `oss_config.py`'s own module docstring says
so. The scaffolded `GITIGNORE` template never followed -- a fossil of the
pre-#34 world, when there was one file and ignoring it was correct.

Assert the POST-CONDITION, not the template string: what a real `git check-ignore`
says about a rendered `.gitignore` in an actual repo. A string match on the template
is a proxy; git's own answer is the fact that matters, and it is the fact the
install-audit check in PR #563 reads.

Every "is not ignored" assertion is paired with an "is ignored" one in the same
fixture -- a fixture with no `.gitignore` at all would pass the first half for the
wrong reason.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

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


def _real_git_repo(tmp_path):
    """A repo `git check-ignore` will actually answer about, or the test skips.

    Same shape as `oss_config`'s own `_real_git_repo` fixture (test_config_scope.py):
    a real `git init` is required because `git check-ignore` is what is under test,
    not a hand-rolled parse of the file.
    """
    done = subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if done.returncode != 0:
        pytest.skip(
            "git init failed here: {}".format(done.stderr.strip() or done.returncode)
        )


def _check_ignore(repo, name):
    """(ignored: bool, could_not_ask: bool) for `name` under `repo`."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "--", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return None, str(exc)
    if done.returncode == 0:
        return True, ""
    if done.returncode == 1:
        return False, ""
    return None, done.stderr.decode("utf-8", "replace").strip()


def test_a_freshly_scaffolded_gitignore_tracks_oss_json_and_ignores_the_local_half(
    tmp_path,
):
    _real_git_repo(tmp_path)
    scaffold.apply(tmp_path, _config())

    gitignore = tmp_path / ".gitignore"
    assert gitignore.is_file()

    ignored, detail = _check_ignore(tmp_path, ".oss.json")
    assert ignored is False, (
        ".oss.json -- the tracked, authoritative project config -- is ignored by the "
        "scaffolded .gitignore: {}".format(detail)
    )

    # The positive control, in the SAME fixture: something must still be ignored, or
    # the assertion above would also pass against a .gitignore with no rules in it.
    ignored, detail = _check_ignore(tmp_path, ".oss.local.json")
    assert ignored is True, (
        ".oss.local.json -- the machine-specific half -- is NOT ignored by the "
        "scaffolded .gitignore, so it would be committed: {}".format(detail)
    )


def test_the_supertool_symlink_is_still_ignored(tmp_path):
    # A second positive control, independent of the .oss.local.json rule: the fix
    # must narrow or remove the .oss.json line, not delete unrelated ignore rules.
    _real_git_repo(tmp_path)
    scaffold.apply(tmp_path, _config())

    ignored, detail = _check_ignore(tmp_path, "supertool")
    assert ignored is True, (
        "the machine-specific /supertool symlink must stay ignored: {}".format(detail)
    )


def test_gitignore_template_body_names_oss_json_nowhere(tmp_path):
    """The template string itself, as a secondary/cheaper check -- not a substitute
    for the git-check-ignore assertions above, which test the actual post-condition.
    """
    body = scaffold.render(".gitignore", _config())
    lines = [line.strip() for line in body.splitlines()]
    assert ".oss.json" not in lines, (
        "the .gitignore template still names .oss.json as a line of its own -- the "
        "file this loop calls tracked and authoritative"
    )
    assert ".oss.local.json" in lines, (
        "the .gitignore template should name .oss.local.json explicitly -- the "
        "machine-specific half the old comment was actually describing"
    )


def test_gitignore_stays_a_default_not_an_owned_file(tmp_path):
    """The fix must not turn `.gitignore` into an OWNED file (replaced every run).

    `.gitignore` is a defaults file in CLAUDE.md's ownership table: created once when
    absent, then the managed repo's forever. `apply()` must keep reporting it under
    `created` on first write and under neither `created` nor `replaced` -- i.e.
    untouched -- on a second run, the same as every other defaults file.
    """
    first = scaffold.apply(tmp_path, _config())
    assert ".gitignore" in first["created"]
    assert ".gitignore" not in first["replaced"]

    # A maintainer edits it by hand after scaffolding -- exactly the case a defaults
    # file exists to protect.
    (tmp_path / ".gitignore").write_text("# hand-edited\n", encoding="utf-8")
    second = scaffold.apply(tmp_path, _config())
    assert ".gitignore" not in second["created"]
    assert ".gitignore" not in second["replaced"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "# hand-edited\n"
