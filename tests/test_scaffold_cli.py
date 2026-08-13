"""The scaffold CLI that /oss:scaffold invokes.

The default must be the safe one. A command that writes into someone's repo by default
is a command somebody runs to "see what it does".
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

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
        "ci": {"required_checks": 0},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    path = root / ".oss.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_the_default_run_writes_nothing(tmp_path, capsys):
    """Printing the plan is the default because the other option edits someone's repo."""
    config = _write_config(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "PLAN:" in out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_the_plan_names_each_file_and_its_action(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    out = capsys.readouterr().out
    assert "CLAUDE.md" in out
    assert "create" in out


def test_the_plan_distinguishes_present_from_create(tmp_path, capsys):
    config = _write_config(tmp_path)
    (tmp_path / "SECURITY.md").write_text("ours\n", encoding="utf-8")
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    lines = {
        line.split()[1]: line.split()[0]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(("create", "present"))
    }
    assert lines["SECURITY.md"] == "present"
    assert lines["CLAUDE.md"] == "create"


def test_apply_writes_and_reports_what_it_wrote(tmp_path, capsys):
    config = _write_config(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "WROTE:" in out
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").is_file()


def test_apply_leaves_an_existing_file_alone(tmp_path):
    config = _write_config(tmp_path)
    (tmp_path / "CODE_OF_CONDUCT.md").write_text("ours\n", encoding="utf-8")
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    assert (tmp_path / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8") == "ours\n"


def test_a_missing_config_is_a_named_failure(tmp_path, capsys):
    result = scaffold._main(["--root", str(tmp_path), "--config", str(tmp_path / "absent.json")])
    assert result == 1
    assert "not found" in capsys.readouterr().out


def test_an_invalid_config_refuses_before_writing_anything(tmp_path, capsys):
    path = tmp_path / ".oss.json"
    path.write_text(json.dumps({"repo": "owner/name"}), encoding="utf-8")
    assert scaffold._main(["--root", str(tmp_path), "--config", str(path), "--apply"]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_apply_works_with_a_relative_root(tmp_path, monkeypatch, capsys):
    """`--root .` is how the command invokes this, and it was broken while every test
    passed: they all handed in an absolute tmp_path, so the one form that ships was the
    one form never exercised. Found by running the tool on this repo, not by the suite.
    """
    config = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert scaffold._main(["--root", ".", "--config", str(config), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "01-oss" in out
    assert (tmp_path / ".claude" / "jit-context" / "paths" / "01-oss" / "00-index.tsv").is_file()


def test_apply_replaces_the_rule_layer_and_says_so(tmp_path, capsys):
    """Templates and rules have opposite contracts, so the output must not blur them:
    one is never overwritten, the other always is.
    """
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert "replaced" in out
    assert "rule layer" in out


def test_the_generated_claude_md_names_the_configured_repo(tmp_path):
    config = _write_config(tmp_path, repo="acme/widget", default_branch="trunk")
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    body = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "acme/widget" in body
    assert "trunk" in body
