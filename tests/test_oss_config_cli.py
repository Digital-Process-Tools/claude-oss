"""The `oss_config.py` CLI that /oss:setup and /oss:doctor invoke.

Exit codes carry meaning here, unlike in the doctor: a non-zero means the config or
the probe is unusable, so a caller can gate on it.
"""

import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def _valid(root):
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
        "ci": {"required_checks": 0},
        "state_file": ".max/oss-watch.json",
    }
    path = root / ".oss.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_validate_exits_zero_on_a_good_config(tmp_path, capsys):
    assert oss_config._main(["--validate", str(_valid(tmp_path))]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_exits_non_zero_and_names_each_problem(tmp_path, capsys):
    path = tmp_path / ".oss.json"
    path.write_text(json.dumps({"repo": "name"}), encoding="utf-8")
    assert oss_config._main(["--validate", str(path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "repo" in out
    assert "missing required key" in out


def test_validate_of_a_missing_file_is_a_named_failure(tmp_path, capsys):
    assert oss_config._main(["--validate", str(tmp_path / "absent.json")]) == 1
    assert "not found" in capsys.readouterr().out


def test_build_reads_a_probe_and_writes_a_config(tmp_path, monkeypatch, capsys):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": ["priority-high", "lane-core"],
        "milestones": ["v1.0"],
        "workflow_jobs": ["pytest"],
        "files": ["pyproject.toml", "README.md"],
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(probe)))
    assert oss_config._main(["--build"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["repo"] == "owner/name"
    assert config["labels"]["priority"] == ["priority-high"]
    assert config["ci"]["required_checks"] == 1


def test_build_on_a_bare_repo_still_produces_a_valid_config(monkeypatch, capsys):
    """The repo with nothing configured is the fixture that matters: empty lists are
    the honest answer and must not be an error.
    """
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": [],
        "milestones": [],
        "workflow_jobs": [],
        "files": [],
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(probe)))
    assert oss_config._main(["--build"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["labels"] == {"priority": [], "lanes": []}
    assert config["test_command"] is None


def test_build_rejects_a_probe_that_is_not_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert oss_config._main(["--build"]) == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_build_reports_a_derived_config_that_would_not_validate(monkeypatch, capsys):
    """A probe missing the repo produces a config missing the repo. That is reported
    on stderr and exits non-zero -- but the config still goes to stdout, so the caller
    can see what was derived rather than being told only that it failed.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"default_branch": "main"})))
    assert oss_config._main(["--build"]) == 1
    captured = capsys.readouterr()
    assert "repo" in captured.err
    assert json.loads(captured.out)["default_branch"] == "main"
