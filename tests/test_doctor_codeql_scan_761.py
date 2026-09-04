"""#761: the CodeQL owned-path language finding -- a default CodeQL setup on a
repo whose only CodeQL-supported language is the vendored `.oss/` directory
this plugin itself installs is worse than shipping no scanner at all, since
the findings would be unfixable in that tree without being reverted at the
next `/oss:scaffold` run.

Four states, and every "must not fire" case here is paired with a "must fire"
case in the same fixture, per CLAUDE.md's rule that a negative assertion
needs a positive control: a supported language sitting ONLY inside the owned
path must never render as `uncovered-outside-owned`, and a language present
both inside and outside the owned path must never render as `owned-only`.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_codeql_scan  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _config(repo="owner/name", **overrides):
    config = {"repo": repo}
    config.update(overrides)
    return config


def _run_once(rc, out, err):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def _languages_run(languages_dict):
    return _run_once(0, json.dumps(languages_dict), "")


# --------------------------------------------------------------- gating


def test_could_not_tell_when_gh_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config())
    assert state == "could-not-tell"
    assert "gh is not on PATH" in detail


def test_could_not_tell_on_403(tmp_path):
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "403" in detail


def test_could_not_tell_when_languages_response_is_not_json(tmp_path):
    run = _run_once(0, "not json at all", "")
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"


# --------------------------------------------------------- no-supported-language


def test_no_supported_language_is_ok_when_only_shell_is_present(tmp_path):
    """Shell has no CodeQL analyser at all -- this is the issue's own worked
    example (claude-jit-context: 1.5MB Shell, no analyser exists)."""
    run = _languages_run({"Shell": 1511382})
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "no-supported-language"
    assert "Shell" in detail


def test_no_supported_language_names_existing_shellcheck_workflow(tmp_path):
    """Must-fire pair: when a shellcheck workflow already exists, the check
    says so rather than recommending one that is already there."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("jobs:\n  lint:\n    steps:\n      - run: shellcheck script.sh\n", encoding="utf-8")
    run = _languages_run({"Shell": 1000})
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "no-supported-language"
    assert "shellcheck" in detail
    assert "already appears to cover" in detail


def test_no_supported_language_with_no_existing_shellcheck_recommends_one(tmp_path):
    """Negative control for the case above: no workflow at all must not be
    read as "already covered"."""
    run = _languages_run({"Shell": 1000})
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert "no shellcheck workflow was found" in detail
    assert "already appears to cover" not in detail


# ---------------------------------------------------------------- owned-only


def test_owned_only_when_the_only_supported_language_is_inside_dot_oss(tmp_path):
    """The issue's own worked example: 100% of the Python present is the
    vendored .oss/ trio."""
    oss_dir = tmp_path / ".oss"
    oss_dir.mkdir()
    (oss_dir / "assemble_changelog.py").write_text("# vendored\n", encoding="utf-8")
    run = _languages_run({"Python": 154452, "Shell": 1511382})
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "owned-only"
    assert "python" in detail


def test_uncovered_outside_owned_when_the_same_language_also_appears_outside(tmp_path):
    """Must-fire pair for the test above: identical GitHub language totals,
    but this time a real .py file sits outside .oss/ too -- must land on the
    OTHER side of the split."""
    oss_dir = tmp_path / ".oss"
    oss_dir.mkdir()
    (oss_dir / "assemble_changelog.py").write_text("# vendored\n", encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "doctor.py").write_text("# real product code\n", encoding="utf-8")
    run = _languages_run({"Python": 154452, "Shell": 1511382})
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "uncovered-outside-owned"
    assert "python" in detail


def test_owned_workflow_file_itself_does_not_count_as_outside_owned(tmp_path):
    """The other CLAUDE.md 'ours' path -- .github/workflows/oss-changelog.yml
    -- must be excluded too, even though it sits outside .oss/ by name."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "oss-changelog.yml").write_text("name: changelog\n", encoding="utf-8")
    run = _languages_run({"YAML": 500})  # YAML has no CodeQL analyser either way
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "no-supported-language"


def test_jit_context_01_oss_directory_is_treated_as_owned(tmp_path):
    """The third CLAUDE.md 'ours' path: .claude/jit-context/<dim>/01-oss/ --
    a .py file living there must not count as 'outside owned', even though
    it is nested three levels deep rather than at the top."""
    owned_nested = tmp_path / ".claude" / "jit-context" / "tools" / "01-oss"
    owned_nested.mkdir(parents=True)
    (owned_nested / "helper.py").write_text("# vendored rule tooling\n", encoding="utf-8")
    run = _languages_run({"Python": 500})
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "owned-only"


# ---------------------------------------------------------- workflow-mention tri-state


def test_workflow_files_mention_true_when_needle_present(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("run: shellcheck script.sh\n", encoding="utf-8")
    assert doctor_check_codeql_scan._workflow_files_mention(tmp_path, "shellcheck") is True


def test_workflow_files_mention_false_when_directory_absent(tmp_path):
    """Must-not-fire pair for the could-not-read case below: a directory that
    genuinely does not exist is False, not None -- there is nothing to search,
    which is a real, confident answer."""
    assert doctor_check_codeql_scan._workflow_files_mention(tmp_path, "shellcheck") is False


def test_workflow_files_mention_none_when_directory_could_not_be_listed(tmp_path, monkeypatch):
    """Self-review finding: a workflows directory that exists but could not
    be listed (a permission error, not absence) must render as `None` --
    unknown -- never silently as `False`, the same "an absence produced by
    the tool must not read as an absence in the world" rule CLAUDE.md states
    for every checker in this plugin."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)

    def broken_listdir(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(doctor_check_codeql_scan.os, "listdir", broken_listdir)
    assert doctor_check_codeql_scan._workflow_files_mention(tmp_path, "shellcheck") is None


def test_no_supported_language_detail_carries_the_stale_table_caveat(tmp_path):
    """Self-review finding: `CODEQL_LANGUAGE_FAMILIES` is a hardcoded,
    admittedly stale snapshot documented in the module's own docstring --
    that limitation must reach the printed detail, not stay a fact only the
    source reader sees."""
    run = _languages_run({"Shell": 1000})
    _state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert "hardcoded snapshot" in detail


def test_no_supported_language_names_could_not_tell_when_workflows_unreadable(tmp_path, monkeypatch):
    """Must-fire pair for the existing-shellcheck-workflow test above: when
    the workflows directory cannot be read at all, the detail must say so
    rather than silently reading as "no shellcheck workflow was found"."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)

    def broken_listdir(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(doctor_check_codeql_scan.os, "listdir", broken_listdir)
    run = _languages_run({"Shell": 1000})
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "no-supported-language"
    assert "could not be told" in detail
    assert "no shellcheck workflow was found" not in detail


# ---------------------------------------------------------------- report lines


def test_check_codeql_scan_reports_ok_for_no_supported_language(tmp_path, capsys):
    run = _languages_run({"Shell": 1000})
    doctor.check_codeql_scan(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_codeql_scan_reports_warn_for_owned_only(tmp_path, capsys):
    oss_dir = tmp_path / ".oss"
    oss_dir.mkdir()
    (oss_dir / "assemble_changelog.py").write_text("# vendored\n", encoding="utf-8")
    run = _languages_run({"Python": 1000})
    doctor.check_codeql_scan(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "actions" in out


def test_check_codeql_scan_reports_could_not_tell_distinctly(tmp_path, capsys):
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    doctor.check_codeql_scan(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not tell" in out
    assert not out.startswith("OK ")
