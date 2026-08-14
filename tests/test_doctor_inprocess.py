"""doctor.py driven in-process.

test_doctor.py runs it as a subprocess, which is the honest end-to-end check: it is
how a user invokes it, and it is the only way to assert the real exit code. But
coverage cannot see inside a subprocess, so that suite reports 0% for a file it
exercises thoroughly -- a measurement saying "untested" about tested code, which is
the same defect class this plugin is about.

So both: subprocess for the contract, in-process for the branches.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import scaffold  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _config(root, **overrides):
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
    (root / ".oss.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def test_plugin_version_matches_the_manifest():
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert doctor.plugin_version() == manifest["version"]


def test_check_config_returns_none_and_reports_when_absent(tmp_path):
    assert doctor.check_config(tmp_path) is None
    assert any(state == "FAIL" for state, _ in doctor.FINDINGS)


def test_check_config_returns_the_config_when_valid(tmp_path):
    written = _config(tmp_path)
    loaded = doctor.check_config(tmp_path)
    assert loaded == written
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_directory_warns_rather_than_failing_on_a_missing_path(tmp_path):
    doctor.check_directory("clone", str(tmp_path / "absent"))
    assert doctor.FINDINGS[-1][0] == "WARN"


def test_check_directory_warns_when_the_value_is_not_set():
    doctor.check_directory("worktree_root", None)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "cannot check" in message


def test_check_directory_expands_a_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "somewhere").mkdir()
    doctor.check_directory("clone", "~/somewhere")
    assert doctor.FINDINGS[-1][0] == "OK"


def test_state_file_absence_is_a_warning_naming_the_first_tick(tmp_path):
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "first tick" in message


def test_state_file_present_is_ok(tmp_path):
    (tmp_path / ".max").mkdir()
    (tmp_path / ".max" / "oss-watch.json").write_text("{}", encoding="utf-8")
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_tool_warns_when_absent(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    doctor.check_tool("nonexistent-tool", ["nonexistent-tool", "--version"])
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not on PATH" in message


def test_check_tool_warns_when_present_but_failing(monkeypatch):
    """Present-and-broken is its own state. Reporting it as absent would send someone
    to install a tool they already have.
    """
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/false")
    doctor.check_tool("git", [sys.executable, "-c", "import sys; sys.exit(3)"])
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "returned 3" in message


def test_check_tool_warns_when_the_probe_cannot_spawn(monkeypatch):
    """An unspawnable binary must reach the tool-failed arm, not raise. This is the
    cross-platform shape: Windows raises where POSIX would have run something.
    """
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/definitely/not/here")
    doctor.check_tool("git", ["/definitely/not/here", "--version"])
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "would not run" in message


def test_check_tool_reports_ok_on_a_zero_exit(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: sys.executable)
    doctor.check_tool("python", [sys.executable, "-c", "pass"])
    assert doctor.FINDINGS[-1][0] == "OK"


def test_main_returns_zero_and_ends_on_a_verdict(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor.main() == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1].startswith("VERDICT:")


def _fully_configured(root):
    """Everything the doctor checks, present and current.

    Written out rather than stubbed: the point of this test is that `VERDICT: ok`
    requires every check to pass, so the fixture has to satisfy every check.
    """
    (root / "wt").mkdir(exist_ok=True)
    (root / ".max").mkdir(exist_ok=True)
    (root / ".max" / "oss-watch.json").write_text("{}", encoding="utf-8")
    # config.json lives in .claude/remember/; sessions AND identity go to the data_dir
    # it names. Identity in the config dir is only read when the plugin is installed
    # there, which this fixture does not do -- so putting it there would describe a repo
    # whose identity never loads.
    memory_config = root / ".claude" / "remember"
    memory_config.mkdir(parents=True, exist_ok=True)
    (memory_config / "config.json").write_text('{"data_dir": ".remember"}', encoding="utf-8")
    (root / ".remember").mkdir(exist_ok=True)
    (root / ".remember" / "identity.md").write_text("who the agent is\n", encoding="utf-8")
    rules = root / ".claude" / "jit-context"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    index = rules / "00-index.tsv"
    index.write_text("conventions\tx\n", encoding="utf-8")
    newer = index.stat().st_mtime + 60
    os.utime(index, (newer, newer))


def _dependencies_current(monkeypatch):
    """Every declared dependency installed and matching what is published.

    Stubbed at the fetch boundary rather than by replacing check_freshness: the
    judging stays real, so this test still covers how a freshness finding reaches
    the verdict.
    """
    names = doctor.declared_dependencies()
    monkeypatch.setattr(doctor, "active_versions", lambda n: {name: "1.0.0" for name in names})
    monkeypatch.setattr(doctor, "dependency_repositories", lambda n: {})
    monkeypatch.setattr(doctor, "published_versions", lambda repos: {n: "1.0.0" for n in names})


def test_verdict_says_ok_only_when_nothing_warned(tmp_path, monkeypatch, capsys):
    config = _config(tmp_path)
    _fully_configured(tmp_path)
    scaffold.apply(tmp_path, config, plugin_root=REPO_ROOT)
    _dependencies_current(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(doctor, "check_tool", lambda name, probe: doctor.report("OK", name))
    doctor.main()
    assert "VERDICT: ok" in capsys.readouterr().out


def test_verdict_distinguishes_gaps_from_failures(tmp_path, monkeypatch, capsys):
    """usable-with-gaps and not-usable are different answers, and collapsing them is
    how a missing config reads the same as a missing worktree directory.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(doctor, "check_tool", lambda name, probe: doctor.report("OK", name))
    doctor.main()
    out = capsys.readouterr().out
    assert "VERDICT: not usable" in out

    doctor.FINDINGS.clear()
    _config(tmp_path)
    (tmp_path / "wt").mkdir()
    doctor.main()
    assert "VERDICT: usable with gaps" in capsys.readouterr().out
