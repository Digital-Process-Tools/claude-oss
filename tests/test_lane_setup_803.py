"""#803: `main`'s `--release` arm dropped `oss_config.load`'s `problems` list in
exactly the case #791 did not fix. #791 fixed `config is None` -- the project half
(`.oss.json`) could not be read at all. `worktree_root` only ever lives in
`.oss.local.json` (`LOCAL_KEYS`, `scripts/oss_config.py`), so when the *local* half
is present but unparseable, `oss_config.load` returns a non-None `config` -- with
no `worktree_root` key, since the unreadable local half was never merged in -- and
the real parse error sits in `problems` instead of in `config is None`. The old
`else` arm, reached whenever `config is not None`, dropped that list the same way
the pre-#791 code did and rendered the same benign "no registry" sentence written
for a config that genuinely has no `worktree_root` key configured.

Three arms, matching the issue body:

  A  .oss.local.json present and malformed -- must surface the parse error.
  B  .oss.json malformed -- already correct pre-#803 (this is the control that
     proves the fix does not touch the already-working path).
  C  no local file at all -- stays the benign "no registry" sentence, and must
     read differently from arm A's (arm C genuinely has nothing to report; arm A
     has a concrete parse error).

A naive "gate on any `problems`" over-corrects: `oss_config.load` always adds a
"missing required key: worktree_root" advisory to `problems` whenever `worktree_root`
is absent, read failure or not, which is exactly arm C's own ordinary case -- so a
fourth control below (a syntactically valid `.oss.local.json` that simply omits
`worktree_root`) pins that the benign sentence still renders even though `problems`
is non-empty for that config.
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

PROJECT_CONFIG = {
    "repo": "example/example",
    "default_branch": "main",
    "branch_pattern": "fix/{issue}",
    "test_command": "pytest",
    "version_sites": [],
    "changelog_dir": None,
    "docs_targets": [],
    "labels": {"priority": [], "lanes": []},
}


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


def _release(tmp_path, issue=999):
    done = _cli(tmp_path, issue, "--release")
    return json.loads(done.stdout)


def test_arm_a_malformed_local_config_surfaces_the_parse_error(tmp_path):
    (tmp_path / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))
    (tmp_path / ".oss.local.json").write_text("{not json")

    payload = _release(tmp_path)

    assert payload["state"] == "could-not-release"
    assert "could not parse as JSON" in payload["detail"]
    assert "no registry" not in payload["detail"]


def test_arm_b_malformed_project_config_control(tmp_path):
    """Control: #791's own case, already correct before this fix. Must still work
    after #803's change to the same code path."""
    (tmp_path / ".oss.json").write_text("{not json")

    payload = _release(tmp_path)

    assert payload["state"] == "could-not-release"
    assert "could not parse as JSON" in payload["detail"]
    assert "no registry" not in payload["detail"]


def test_arm_c_no_local_file_stays_benign_and_differs_from_arm_a(tmp_path):
    (tmp_path / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))

    payload = _release(tmp_path)

    assert payload["state"] == "could-not-release"
    assert "no registry" in payload["detail"]

    malformed_dir = tmp_path.parent / (tmp_path.name + "-arm-a")
    malformed_dir.mkdir()
    (malformed_dir / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))
    (malformed_dir / ".oss.local.json").write_text("{not json")
    arm_a_payload = _release(malformed_dir)

    assert arm_a_payload["detail"] != payload["detail"]


def test_valid_local_config_missing_worktree_root_is_still_benign(tmp_path):
    """Must-not-fire control for the naive "gate on any problems" fix: a
    syntactically valid .oss.local.json that simply has no worktree_root key
    still produces a "missing required key" advisory in `problems`, and that
    advisory alone must not be read as a read failure."""
    (tmp_path / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))
    (tmp_path / ".oss.local.json").write_text(json.dumps({"clone": "/tmp/does-not-matter"}))

    payload = _release(tmp_path)

    assert payload["state"] == "could-not-release"
    assert "no registry" in payload["detail"]
    assert "could not" not in payload["detail"]
