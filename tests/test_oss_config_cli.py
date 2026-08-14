"""The `oss_config.py` CLI that /oss:setup and /oss:doctor invoke.

Exit codes carry meaning here, unlike in the doctor: a non-zero means the config or
the probe is unusable, so a caller can gate on it.
"""

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": ["priority-high", "lane-core"],
        "milestones": ["v1.0"],
        "workflow_jobs": ["pytest"],
        "files": ["pyproject.toml", "README.md"],
        "tags": [],
        "merge_method": None,
        "version_evidence": {"pyproject.toml": "version", "README.md": "none"},
    }
    probe.update(overrides)
    return probe


def test_build_reads_a_probe_and_writes_a_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_probe())))
    assert oss_config._main(["--build"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["repo"] == "owner/name"
    assert config["labels"]["priority"] == ["priority-high"]
    assert config["ci"]["required_checks"] == 1


def test_build_on_a_bare_repo_still_produces_a_valid_config(monkeypatch, capsys):
    """The repo with nothing configured is the fixture that matters: empty lists are
    the honest answer and must not be an error.
    """
    probe = _probe(
        labels=[], milestones=[], workflow_jobs=[], files=[], version_evidence={}
    )
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
    """A well-formed probe carrying a malformed repo name produces a config that does
    not validate. That is reported on stderr and exits non-zero -- but the config
    still goes to stdout, so the caller sees what was derived.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_probe(repo="name"))))
    assert oss_config._main(["--build"]) == 1
    captured = capsys.readouterr()
    assert "repo" in captured.err
    assert json.loads(captured.out)["default_branch"] == "main"


def test_build_refuses_an_underspecified_probe_and_names_the_key(monkeypatch, capsys):
    """An underspecified probe used to produce a confidently wrong config with no
    error at any layer (#1). It now produces no config at all.
    """
    probe = _probe()
    del probe["files"]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(probe)))
    assert oss_config._main(["--build"]) == 1
    captured = capsys.readouterr()
    assert "files" in captured.err
    assert captured.out == ""


def test_build_names_the_labels_it_could_not_classify(monkeypatch, capsys):
    """Empty priority on a labelled board and empty priority on a bare one are the
    same two characters in the config. The difference has to be said out loud (#10).
    """
    probe = _probe(labels=["priority/high", "bug", "documentation"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(probe)))
    assert oss_config._main(["--build"]) == 0
    err = capsys.readouterr().err
    assert "unclassified" in err
    assert "bug" in err
    assert "documentation" in err


def test_build_names_a_candidate_it_could_not_read(monkeypatch, capsys):
    probe = _probe(
        files=["package.json", "README.md"],
        version_evidence={"package.json": "unreadable", "README.md": "none"},
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(probe)))
    assert oss_config._main(["--build"]) == 0
    captured = capsys.readouterr()
    assert "package.json" in captured.err
    assert json.loads(captured.out)["version_sites"] == []


def test_help_states_the_probe_schema(capsys):
    """The schema was discoverable only by reading the source, so callers guessed and
    the guesses were wrong in a way nothing reported (#1).
    """
    with pytest.raises(SystemExit):
        oss_config._main(["--help"])
    out = capsys.readouterr().out
    assert "git ls-files" in out
    assert "version_evidence" in out


GIT = shutil.which("git")


@pytest.mark.skipif(GIT is None, reason="git is not on PATH, so there is no repo to probe")
def test_probe_mode_emits_a_probe_that_build_mode_accepts(tmp_path, monkeypatch, capsys):
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("# thing\n", encoding="utf-8")
    subprocess.run([GIT, "-C", str(tmp_path), "add", "-A"], check=True)

    def fake_gh(root, args):
        if args[0] == "repo":
            return (
                True,
                {
                    "nameWithOwner": "owner/name",
                    "defaultBranchRef": {"name": "main"},
                    "squashMergeAllowed": True,
                    "mergeCommitAllowed": False,
                    "rebaseMergeAllowed": False,
                },
                "",
            )
        return True, [], ""

    monkeypatch.setattr(oss_config, "_gh_json", fake_gh)
    assert oss_config._main(["--probe", str(tmp_path)]) == 0
    probe = json.loads(capsys.readouterr().out)
    assert probe["files"] == ["README.md"]

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(probe)))
    assert oss_config._main(["--build"]) == 0
    assert json.loads(capsys.readouterr().out)["repo"] == "owner/name"


def test_probe_mode_says_why_it_could_not_measure(tmp_path, capsys):
    assert oss_config._main(["--probe", str(tmp_path / "nowhere")]) == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.out + captured.err
    assert captured.out.strip() == "" or not captured.out.strip().startswith("{")
