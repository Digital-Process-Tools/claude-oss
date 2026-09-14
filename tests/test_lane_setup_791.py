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
        [sys.executable, str(SCRIPT), str(issue), "--repo", str(tmp_path), "--json"]
        + list(extra_args),
        subject="lane_setup.py --release",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_release_with_absent_config_names_the_absence(tmp_path):
    """#1532: this used to compare a valid config carrying no `worktree_root`
    (benign -- nothing to release from) against an absent config (a read that
    failed), because the two rendered the same sentence. `--release` no longer
    reads `worktree_root` at all, so the benign half has no shape any more.

    The distinction that mattered survives on the project half, which still
    carries `repo`: absent and malformed are different facts and must not
    share a sentence. `tests/test_lane_setup_803.py` holds the malformed side;
    this holds the absent one."""
    done = _cli(tmp_path, 999, "--release")
    payload = json.loads(done.stdout)
    assert payload["state"] == "could-not-release"
    assert "not found" in payload["detail"]


def test_release_with_malformed_config_names_the_parse_error(tmp_path):
    (tmp_path / ".oss.json").write_text("{not json")
    done = _cli(tmp_path, 999, "--release")
    payload = json.loads(done.stdout)
    assert payload["state"] == "could-not-release"
    assert "not found" not in payload["detail"]
    assert "could not parse as JSON" in payload["detail"]
