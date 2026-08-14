"""The scaffold CLI that /oss:scaffold invokes.

The default must be the safe one. A command that writes into someone's repo by default
is a command somebody runs to "see what it does".
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


def _write_halves(root, config):
    """Write the two-file shape /oss:setup produces, and return the project half's path."""
    project, local = oss_config.split(config)
    path = root / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")
    return path


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
    return _write_halves(root, config)


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


def test_the_plan_names_the_test_gate_that_does_not_exist(tmp_path, capsys):
    """A verified test command nothing runs is a measurement, so it is stated."""
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    out = capsys.readouterr().out
    assert "pytest" in out
    assert "runs it" in out


def test_apply_reports_the_stale_required_checks_count(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert "required_checks" in out
    assert "check-runs" in out


def test_apply_names_the_escape_hatch_label_it_will_not_create(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert "no-changelog" in out
    assert "gh label create" in out


def test_the_generated_claude_md_names_the_configured_repo(tmp_path):
    config = _write_config(tmp_path, repo="acme/widget", default_branch="trunk")
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    body = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "acme/widget" in body
    assert "trunk" in body


# ------------------------------------------------------------------------------ show


def test_show_prints_content_and_writes_nothing(tmp_path, capsys):
    config = _write_config(tmp_path, repo="acme/widget")
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"]) == 0
    out = capsys.readouterr().out
    assert "CLAUDE.md" in out
    assert "acme/widget" in out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_show_one_path_prints_only_that_file(tmp_path, capsys):
    config = _write_config(tmp_path)
    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--show", "SECURITY.md"]
    ) == 0
    out = capsys.readouterr().out
    assert "Security Policy" in out
    assert "CLAUDE.md" not in out


def test_show_and_apply_together_is_refused_before_writing(tmp_path, capsys):
    config = _write_config(tmp_path)
    result = scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--show", "--apply"]
    )
    assert result == 1
    assert "FAIL" in capsys.readouterr().out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_show_of_an_unknown_path_is_a_named_failure(tmp_path, capsys):
    config = _write_config(tmp_path)
    result = scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--show", "NOT_A_TEMPLATE.md"]
    )
    assert result == 1
    assert "FAIL" in capsys.readouterr().out


def test_show_includes_owned_files_even_when_every_template_already_exists(tmp_path, capsys):
    """The sharp case from the coordinator review: with every template already on disk,
    the bare `--show` this command tells the caller to run must still name the three
    files `apply` overwrites unconditionally -- printing nothing here reads as "apply
    would write nothing", which is false.
    """
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    result = scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"])
    assert result == 0
    out = capsys.readouterr().out
    assert ".oss/README.md" in out
    assert ".oss/assemble_changelog.py" in out
    assert ".github/workflows/oss-changelog.yml" in out
    assert "nothing to show" not in out


def test_show_labels_create_and_replace_differently(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"])
    out = capsys.readouterr().out
    create_line = next(line for line in out.splitlines() if "CLAUDE.md" in line)
    replace_line = next(line for line in out.splitlines() if ".oss/README.md" in line)
    assert create_line != replace_line
    assert "create" in create_line
    assert "replace" in replace_line


# ------------------------------------------- collision with an existing changelog gate


def _with_other_gate(root):
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "changelog.yml").write_text(
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        ".github/scripts/assemble_changelog.py --check\n",
        encoding="utf-8",
    )


def test_the_plan_reports_a_decline_when_a_gate_already_exists(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    out = capsys.readouterr().out
    assert "decline" in out
    assert "changelog" in out


def test_apply_reports_what_it_declined_and_does_not_write_it(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "declined" in out
    assert "--force-owned" in out
    assert not (tmp_path / ".github" / "workflows" / "oss-changelog.yml").exists()


def test_force_owned_flag_writes_the_trio_despite_a_detected_gate(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--apply", "--force-owned"]
    ) == 0
    assert (tmp_path / ".github" / "workflows" / "oss-changelog.yml").is_file()
