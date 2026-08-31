"""#287: is this install complete -- over the plugin and its declared dependencies,
not over this repository. Every question is satisfied / missing-with-a-named-remedy
/ could-not-tell, and the third one is what this file spends most of its length on:
a check that cannot look must print something different from a check that looked
and found nothing.

The comment on #287 folds #286 in as its own checklist line: the finding survives
as evidence independent of the remedy, and the fixture below covers both -- a fresh
repo with no committed .oss.json, no priority labels, and dependency/labels/owned
questions each answered honestly rather than skipped.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import doctor  # noqa: E402
import spawn_guard  # noqa: E402
import oss_config  # noqa: E402
import scaffold  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _git(root, *args):
    subprocess.run(["git", "-C", str(root)] + list(args), check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _init_repo(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


def _fake_run(stdout="", returncode=0):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return run


# ------------------------------------------------------- .oss.json committed


def test_a_tracked_oss_json_reports_committed(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".oss.json").write_text("{}", encoding="utf-8")
    _git(tmp_path, "add", ".oss.json")
    _git(tmp_path, "commit", "-q", "-m", "x")
    doctor.check_oss_json_committed(tmp_path)
    assert any(
        state == "OK" and "committed: tracked by git" in msg for state, msg in doctor.FINDINGS
    )


def test_an_untracked_oss_json_is_a_named_gap_not_a_silent_pass(tmp_path):
    """The positive control above and this negative one share one fixture family:
    presence on disk without a git commit must not read as satisfied.
    """
    _init_repo(tmp_path)
    (tmp_path / ".oss.json").write_text("{}", encoding="utf-8")
    doctor.check_oss_json_committed(tmp_path)
    assert any(
        state == "WARN" and "NOT tracked by git" in msg for state, msg in doctor.FINDINGS
    )


def test_no_git_repository_at_all_is_could_not_tell(tmp_path):
    """No `.git` here: whether the file is committed is unknown, not "no"."""
    (tmp_path / ".oss.json").write_text("{}", encoding="utf-8")
    doctor.check_oss_json_committed(tmp_path)
    assert any(
        state == "WARN" and "could not tell" in msg for state, msg in doctor.FINDINGS
    )


def test_git_absent_from_path_is_could_not_tell(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    doctor.check_oss_json_committed(tmp_path)
    assert any(
        state == "WARN" and "could not tell" in msg and "git is not on PATH" in msg
        for state, msg in doctor.FINDINGS
    )


# ------------------------------------------------------- .oss.json presence


def test_a_valid_config_reports_ok_and_returns_it(tmp_path):
    project, local = oss_config.split(_config())
    (tmp_path / ".oss.json").write_text(json.dumps(project), encoding="utf-8")
    (tmp_path / ".oss.local.json").write_text(json.dumps(local), encoding="utf-8")
    config = doctor.check_oss_json_presence(tmp_path)
    assert config is not None
    assert any(state == "OK" and "present and valid" in msg for state, msg in doctor.FINDINGS)


def test_a_missing_config_is_warn_not_fail(tmp_path):
    """Missing is the state this whole audit is for. FAIL would make an install
    with nothing else wrong at all read as broken.
    """
    config = doctor.check_oss_json_presence(tmp_path)
    assert config is None
    assert not any(state == "FAIL" for state, _ in doctor.FINDINGS)
    assert any(state == "WARN" and "missing or unreadable" in msg for state, msg in doctor.FINDINGS)


# ------------------------------------------------------- dependency resolution


def test_dependency_resolution_state_shape_is_stable_across_machines(tmp_path):
    """`record=None` reads the real install record, which this machine's own
    state decides -- so this asserts the SHAPE (name present, state one of the
    three) rather than a specific value, which would be a statement about this
    developer's machine rather than about the function. The fixed-record
    variants below (`test_an_active_dependency_...`, `test_a_missing_dependency
    _...`, `test_a_resolving_dependency_with_a_readable_manifest_is_resolves`)
    pin the actual values.
    """
    findings = doctor.dependency_resolution_state(
        ["supertool"], record=None, repos={"supertool": "owner/supertool"}
    )
    assert findings[0]["name"] == "supertool"
    assert findings[0]["state"] in ("resolves", "missing", "contract-unknown")


def test_an_active_dependency_with_no_readable_manifest_is_contract_unknown(tmp_path):
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@dpt-plugins": [{"version": "0.40.0"}]}}),
        encoding="utf-8",
    )
    findings = doctor.dependency_resolution_state(["supertool"], record=record, repos={})
    assert findings == [{"name": "supertool", "state": "contract-unknown", "version": "0.40.0"}]


def test_a_missing_dependency_is_reported_separately_from_contract_unknown(tmp_path):
    record = tmp_path / "installed_plugins.json"
    record.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    findings = doctor.dependency_resolution_state(["supertool"], record=record, repos={})
    assert findings == [{"name": "supertool", "state": "missing", "version": None}]


def test_a_resolving_dependency_with_a_readable_manifest_is_resolves(tmp_path):
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@dpt-plugins": [{"version": "0.40.0"}]}}),
        encoding="utf-8",
    )
    findings = doctor.dependency_resolution_state(
        ["supertool"], record=record, repos={"supertool": "dpt-plugins/claude-supertool"}
    )
    assert findings == [{"name": "supertool", "state": "resolves", "version": "0.40.0"}]


def test_check_dependency_resolution_reports_each_state(tmp_path, monkeypatch):
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@dpt-plugins": [{"version": "0.40.0"}]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: ["supertool", "remember"])
    doctor.check_dependency_resolution(record=record, repos={})
    messages = [msg for _, msg in doctor.FINDINGS]
    assert any("dependency supertool" in m and "contract-unknown" not in m for m in messages)
    assert any("dependency remember" in m and "not active" in m for m in messages)


def test_no_declared_dependencies_reports_ok(monkeypatch):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    doctor.check_dependency_resolution()
    assert any(
        state == "OK" and "none named" in msg for state, msg in doctor.FINDINGS
    )


def test_an_unreadable_manifest_is_could_not_tell_not_zero(tmp_path, monkeypatch):
    """The negative control for the test above: `declared_dependencies()` folds
    "genuinely none" and "manifest could not be read" into the same empty list
    (`except (OSError, ValueError): return []`), and this check must not repeat
    that collapse -- a corrupt manifest must not read as a clean board.
    """
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    monkeypatch.setattr(doctor, "PLUGIN_ROOT", tmp_path)  # no .claude-plugin/plugin.json here
    doctor.check_dependency_resolution()
    assert any(
        state == "WARN" and "could not tell" in msg and "manifest" in msg
        for state, msg in doctor.FINDINGS
    )
    assert not any("none named" in msg for _, msg in doctor.FINDINGS)


# ------------------------------------------------------------ label vocabulary


def test_a_repo_with_priority_labels_is_satisfied(tmp_path):
    rows = json.dumps([{"name": "priority-high"}, {"name": "priority-low"}, {"name": "bug"}])
    state, payload = doctor.label_vocabulary_state(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=rows)
    )
    assert state == "satisfied"
    slug, priority, lanes = payload
    assert slug == "owner/name"
    assert set(priority) == {"priority-high", "priority-low"}


def test_a_repo_with_no_priority_labels_is_a_named_gap(tmp_path):
    """Positive control's sibling: labels exist on the forge, none classify as
    priority, and that must not read the same as `satisfied`.
    """
    rows = json.dumps([{"name": "bug"}, {"name": "enhancement"}])
    state, payload = doctor.label_vocabulary_state(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=rows)
    )
    assert state == "missing"
    assert payload == "owner/name"


def test_gh_unavailable_is_could_not_tell_not_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, payload = doctor.label_vocabulary_state(tmp_path, config={"repo": "owner/name"})
    assert state == "could-not-tell"
    assert "gh is not on PATH" in payload


def test_no_repo_and_no_origin_is_could_not_tell(tmp_path):
    state, payload = doctor.label_vocabulary_state(tmp_path, config=None, run=_fake_run())
    assert state == "could-not-tell"


def test_a_non_string_repo_value_is_could_not_tell_not_a_crash(tmp_path):
    """`.oss.json`'s `repo` key is only VALIDATED as a string by oss_config --
    `check_oss_json_presence` still returns the config, problems and all, and
    label_vocabulary_state is hand-fed exactly that dict. `subprocess.run` raises
    `TypeError` on a non-str/bytes/PathLike argv entry, which is not one of the
    exceptions this function catches -- a malformed committed .oss.json must not
    take out doctor's own exit-0-always contract.
    """
    state, payload = doctor.label_vocabulary_state(
        tmp_path, config={"repo": 123}, run=_fake_run()
    )
    assert state == "could-not-tell"
    assert "repo" in payload


def test_check_label_vocabulary_reports_all_three_states(tmp_path):
    doctor.check_label_vocabulary(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=json.dumps([]))
    )
    assert any(
        state == "WARN" and "correctly refuses to invent one" in msg
        for state, msg in doctor.FINDINGS
    )


# --------------------------------------------------------------- origin slug


def test_origin_slug_reads_a_https_remote(tmp_path):
    slug, reason = doctor._origin_slug(
        tmp_path, run=_fake_run(stdout="https://github.com/owner/name.git\n")
    )
    assert slug == "owner/name"
    assert reason is None


def test_origin_slug_reads_an_ssh_remote(tmp_path):
    slug, reason = doctor._origin_slug(
        tmp_path, run=_fake_run(stdout="git@github.com:owner/name.git\n")
    )
    assert slug == "owner/name"


def test_origin_slug_names_a_non_github_remote_as_unrecognised(tmp_path):
    slug, reason = doctor._origin_slug(
        tmp_path, run=_fake_run(stdout="https://example.com/owner/name.git\n")
    )
    assert slug is None
    assert "not a recognised github.com remote" in reason


# --------------------------------------------------------------------- owned


def test_owned_files_are_not_checked_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    monkeypatch.setattr(
        doctor, "label_vocabulary_state", lambda *a, **k: ("could-not-tell", "no gh")
    )
    doctor.run_install_audit(tmp_path, plugin_root=REPO_ROOT)
    assert any(
        state == "WARN" and "owned files: not checked" in msg for state, msg in doctor.FINDINGS
    )


def test_owned_files_report_when_a_config_is_present(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    monkeypatch.setattr(
        doctor, "label_vocabulary_state", lambda *a, **k: ("could-not-tell", "no gh")
    )
    (tmp_path / ".oss.json").write_text(json.dumps(_config()), encoding="utf-8")
    doctor.run_install_audit(tmp_path, plugin_root=REPO_ROOT)
    detail = [msg for state, msg in doctor.FINDINGS if "owned file" in msg or msg.startswith((
        ".oss/", ".github/"))]
    assert detail, "owned_drift never ran with a config in hand"


# --------------------------------------------------------- run_install_audit


def test_run_install_audit_exits_zero_always(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    monkeypatch.setattr(
        doctor, "label_vocabulary_state", lambda *a, **k: ("could-not-tell", "no gh")
    )
    assert doctor.run_install_audit(tmp_path, plugin_root=REPO_ROOT) == 0


def test_run_install_audit_prints_one_verdict_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    monkeypatch.setattr(
        doctor, "label_vocabulary_state", lambda *a, **k: ("could-not-tell", "no gh")
    )
    doctor.run_install_audit(tmp_path, plugin_root=REPO_ROOT)
    out = capsys.readouterr().out
    verdicts = [ln for ln in out.splitlines() if ln.startswith("VERDICT")]
    assert len(verdicts) == 1


def test_a_fresh_install_with_nothing_configured_is_gaps_not_broken(tmp_path, monkeypatch, capsys):
    """The state #287 is FOR: no .oss.json, no history, nothing the loop normally
    reads. That must never render as `install incomplete` -- nothing here is FAIL.
    """
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    monkeypatch.setattr(
        doctor, "label_vocabulary_state", lambda *a, **k: ("could-not-tell", "no gh")
    )
    doctor.run_install_audit(tmp_path, plugin_root=REPO_ROOT)
    out = capsys.readouterr().out
    assert "VERDICT: install incomplete" not in out
    assert "VERDICT: install usable with gaps" in out


# ------------------------------------------------------------------ subprocess


def _run_cli(cwd, args=()):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return spawn_guard.run(
        [sys.executable, str(DOCTOR), "--install-audit"] + list(args),
        subject="what --install-audit says when run as a real CLI",
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        timeout=60,
    )


def test_cli_flag_exits_zero_with_one_verdict_line(tmp_path):
    done = _run_cli(tmp_path, ["--root", str(tmp_path)])
    assert done.returncode == 0
    verdicts = [ln for ln in done.stdout.splitlines() if ln.startswith("VERDICT")]
    assert len(verdicts) == 1


def test_cli_flag_does_not_run_the_normal_25_check_sequence(tmp_path):
    """The normal run's config-dependent checks say `not checked -- .oss.json was
    not found, so there was nothing to check it against` -- `NO_CONFIG`'s own text,
    five times, on a fresh install. That phrase is exactly what this command exists
    to replace with an answer, and it must not appear here.
    """
    done = _run_cli(tmp_path, ["--root", str(tmp_path)])
    assert doctor.NO_CONFIG not in done.stdout


def test_parse_args_carries_the_new_flag():
    root, plugin_root, install_audit, problems = doctor.parse_args(["--install-audit"])
    assert install_audit is True
    assert problems == []
    root, plugin_root, install_audit, problems = doctor.parse_args([])
    assert install_audit is False
