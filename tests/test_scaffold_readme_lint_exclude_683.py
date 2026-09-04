"""#683: `.oss/*.py` is vendored and replaced wholesale, so a repo's own linter
(ruff, flake8, ...) reports style findings inside it that no fix can survive --
any edit is reverted at the next `/oss:scaffold` run. The cheap fix from the
issue: one line in `.oss/README.md` (already written and owned by scaffold)
saying so, so a maintainer reading the directory before configuring their
linter's excludes has the fact in front of them.

Scope: the README line only, not auto-editing `pyproject.toml`/`.eslintrc` --
see the report for why (`pyproject.toml` is a "yours" file under this
project's own ownership contract, never written by scaffold).
"""

import sys
from pathlib import Path

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


def test_owned_readme_tells_a_linter_to_exclude_the_directory():
    body = scaffold.render_owned(".oss/README.md", _config())
    assert "lint" in body.lower() or "linter" in body.lower()
    assert scaffold.OWNED_DIR in body
    assert "vendored" in body.lower() or "replaced wholesale" in body.lower()
