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
  C  no local file at all -- must read differently from arm A's (arm C genuinely
     has nothing to report; arm A has a concrete parse error). #608: `worktree_root`
     used to be simply absent for arm C, rendering the benign "no registry"
     sentence; `oss_config.load` now DERIVES it from the repository root instead,
     so arm C reaches the ordinary `not-found` outcome -- still benign, still
     distinct from arm A, reached a different way.

A naive "gate on any `problems`" over-corrects: pre-#608, `oss_config.load` always
added a "missing required key: worktree_root" advisory to `problems` whenever
`worktree_root` was absent, read failure or not, which was exactly arm C's own
ordinary case -- so a fourth control below (a syntactically valid `.oss.local.json`
that simply omits `worktree_root`) pins that the benign outcome still holds even
where that advisory would have fired.
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
    """#608: this arm's `worktree_root` used to be simply absent, and the "benign"
    outcome pinned here was the "no registry" sentence. `oss_config.load` now
    DERIVES it from the repository root instead, so the release proceeds against a
    real (if empty) path and reports `not-found` -- still benign, and still clearly
    distinct from arm A's genuine parse error.
    """
    (tmp_path / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))

    payload = _release(tmp_path)

    assert payload["state"] == "not-found", payload

    malformed_dir = tmp_path.parent / (tmp_path.name + "-arm-a")
    malformed_dir.mkdir()
    (malformed_dir / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))
    (malformed_dir / ".oss.local.json").write_text("{not json")
    arm_a_payload = _release(malformed_dir)

    assert arm_a_payload["state"] == "could-not-release"
    assert arm_a_payload["detail"] != payload["detail"]


def test_valid_local_config_missing_worktree_root_is_still_benign(tmp_path):
    """Must-not-fire control for the naive "gate on any problems" fix: a
    syntactically valid .oss.local.json that simply has no worktree_root key must
    not be read as a read failure. #608: that key is now DERIVED from the
    repository root rather than left missing, so `problems` carries no advisory
    about it at all any more, and the release proceeds to the ordinary not-found
    outcome instead of the old "no registry" sentence.
    """
    (tmp_path / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))
    (tmp_path / ".oss.local.json").write_text(json.dumps({"clone": "/tmp/does-not-matter"}))

    payload = _release(tmp_path)

    assert payload["state"] == "not-found", payload
    assert "could not" not in payload["detail"]


def test_unrelated_project_problem_naming_could_not_does_not_block_a_real_release(tmp_path):
    """Must-not-fire control found in review: a fully-parseable, fully-known
    .oss.local.json (worktree_root genuinely present and known) must let a real
    release proceed even when the tracked .oss.json independently carries an
    unrelated validation problem whose own prose contains the substring "could
    not" -- `oss_config.test_command_problem`'s non-string-value message ("...or
    null when the probe could not tell; got ...") is exactly such a case. A
    naive substring scan over the whole merged `problems` list for "could not"
    cannot tell that advisory apart from a genuine local-file read failure, and
    would have blocked a release that has everything it needs."""
    registry_dir = tmp_path / "registry"
    project = dict(PROJECT_CONFIG)
    project["test_command"] = 123  # triggers test_command_problem's "could not tell" text
    (tmp_path / ".oss.json").write_text(json.dumps(project))
    (tmp_path / ".oss.local.json").write_text(
        json.dumps(
            {
                "clone": "/tmp/does-not-matter",
                "worktree_root": str(registry_dir),
                "state_file": "/tmp/does-not-matter-state.json",
            }
        )
    )

    payload = _release(tmp_path)

    assert payload["state"] == "not-found", payload
    assert "worktree_root is not known" not in payload["detail"]
