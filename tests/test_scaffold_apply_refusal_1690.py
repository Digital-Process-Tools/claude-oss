"""#1690: `scaffold.py --apply` refuses when the declared agent role is
`doctor` and `--i-was-asked` was not passed -- the observed incident was a
doctor spawn running `--apply`, committing to the default branch and
pushing, in a run whose own prompt explicitly said not to.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_role  # noqa: E402
import oss_config  # noqa: E402
import scaffold  # noqa: E402


def _write_config(root, **overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": str(root),
        "worktree_root": str(root / "wt"),
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": None,
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    project, local = oss_config.split(config)
    path = root / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local), encoding="utf-8"
    )
    return path


def test_apply_without_doctor_role_still_writes_no_flag_needed(tmp_path, monkeypatch):
    """Positive control: the ordinary case (no role declared, a maintainer
    or the release path running scaffold by hand) must not be disturbed."""
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    config = _write_config(tmp_path)
    rc = scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    assert rc == 0
    assert (tmp_path / "CLAUDE.md").exists()


def test_apply_with_doctor_role_and_no_flag_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "doctor")
    config = _write_config(tmp_path)
    rc = scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert "--i-was-asked" in out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_apply_with_doctor_role_and_i_was_asked_writes(tmp_path, monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "doctor")
    config = _write_config(tmp_path)
    rc = scaffold._main(
        [
            "--root",
            str(tmp_path),
            "--config",
            str(config),
            "--apply",
            "--i-was-asked",
        ]
    )
    assert rc == 0
    assert (tmp_path / "CLAUDE.md").exists()


def test_plan_only_run_is_never_refused_even_with_doctor_role(tmp_path, monkeypatch):
    """The refusal is scoped to --apply -- the read-only plan a doctor spawn
    might print while investigating a gap must still work."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "doctor")
    config = _write_config(tmp_path)
    rc = scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    assert rc == 0
