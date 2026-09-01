"""#791: `main`'s `--release` arm threw away `oss_config.load`'s problems list, so a
malformed config, an absent config and a valid config genuinely lacking `worktree_root`
all rendered the one benign sentence written for the third case.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402


def _cli(tmp_path, issue, *extra_args):
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), str(issue), "--repo", str(tmp_path), "--json"] + list(extra_args),
        subject="lane_setup.py --release",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_release_with_absent_config_names_the_absence(tmp_path):
    """Control: a valid config genuinely lacking worktree_root -- the benign case
    `derive_worktree`'s own docstring calls expected inside a worktree."""
    (tmp_path / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "example/example",
                "default_branch": "main",
                "clone": "/tmp/does-not-matter",
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": None,
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": "/tmp/does-not-matter-state.json",
            }
        )
    )
    done = _cli(tmp_path, 999, "--release")
    payload = json.loads(done.stdout)
    assert payload["state"] == "could-not-release"
    valid_missing_detail = payload["detail"]
    assert "no registry" in valid_missing_detail

    no_config_dir = tmp_path / "no-config"
    no_config_dir.mkdir()
    done2 = _cli(no_config_dir, 999, "--release")
    payload2 = json.loads(done2.stdout)
    assert payload2["state"] == "could-not-release"
    assert "not found" in payload2["detail"]
    assert payload2["detail"] != valid_missing_detail


def test_release_with_malformed_config_names_the_parse_error(tmp_path):
    (tmp_path / ".oss.json").write_text("{not json")
    done = _cli(tmp_path, 999, "--release")
    payload = json.loads(done.stdout)
    assert payload["state"] == "could-not-release"
    assert "not found" not in payload["detail"]
    assert "no registry" not in payload["detail"]
