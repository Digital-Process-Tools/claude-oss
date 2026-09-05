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
    (workflows / "ci.yml").write_text(
        "jobs:\n  lint:\n    steps:\n      - run: shellcheck script.sh\n",
        encoding="utf-8",
    )
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
    # #1062: the `covered` path now asks the forge whether default setup
    # already scans these families, so this fixture has to answer that call
    # too -- `_languages_run` would hand the languages body back for it and
    # the state would (correctly) become `could-not-tell`, which is a
    # different subject from the inside/outside split this test pins.
    run = _routed_run(
        {"Python": 154452, "Shell": 1511382},
        default_setup=(0, json.dumps({"state": "not-configured"}), ""),
    )
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
    (owned_nested / "helper.py").write_text(
        "# vendored rule tooling\n", encoding="utf-8"
    )
    run = _languages_run({"Python": 500})
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "owned-only"


# ---------------------------------------------------------- workflow-mention tri-state


def test_workflow_files_mention_true_when_needle_present(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("run: shellcheck script.sh\n", encoding="utf-8")
    assert (
        doctor_check_codeql_scan._workflow_files_mention(tmp_path, "shellcheck") is True
    )


def test_workflow_files_mention_false_when_directory_absent(tmp_path):
    """Must-not-fire pair for the could-not-read case below: a directory that
    genuinely does not exist is False, not None -- there is nothing to search,
    which is a real, confident answer."""
    assert (
        doctor_check_codeql_scan._workflow_files_mention(tmp_path, "shellcheck")
        is False
    )


def test_workflow_files_mention_none_when_directory_could_not_be_listed(
    tmp_path, monkeypatch
):
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
    assert (
        doctor_check_codeql_scan._workflow_files_mention(tmp_path, "shellcheck") is None
    )


def test_no_supported_language_detail_carries_the_stale_table_caveat(tmp_path):
    """Self-review finding: `CODEQL_LANGUAGE_FAMILIES` is a hardcoded,
    admittedly stale snapshot documented in the module's own docstring --
    that limitation must reach the printed detail, not stay a fact only the
    source reader sees."""
    run = _languages_run({"Shell": 1000})
    _state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert "hardcoded snapshot" in detail


def test_no_supported_language_names_could_not_tell_when_workflows_unreadable(
    tmp_path, monkeypatch
):
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


# ------------------------------------------------- #1062: GitHub's default setup


def _routed_run(languages_dict, default_setup=None):
    """A `run` stub that answers the two `gh api` paths separately.

    #1062: the check makes a second forge call on the `covered` path, and the
    single-answer `_run_once` above would hand the languages body back for it
    too -- a stub that cannot tell the two calls apart cannot pin which one
    produced an answer. `default_setup` is `(rc, stdout, stderr)`, or `None`
    when the test wants no default-setup call to be answered at all.
    """
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        path = cmd[-1]
        if path.endswith("/default-setup"):
            if default_setup is None:
                raise AssertionError(
                    "default-setup was called and the test declared none"
                )
            rc, out, err = default_setup
            return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(languages_dict), stderr=""
        )

    run.calls = calls
    return run


def _repo_with_python_outside_owned(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "doctor.py").write_text("# real product code\n", encoding="utf-8")
    return tmp_path


def test_default_setup_covering_the_local_families_is_not_a_warning(tmp_path):
    """#1062's own measured case: CodeQL default setup ships no workflow file,
    so the local walk sees nothing -- and the repo is fully scanned."""
    _repo_with_python_outside_owned(tmp_path)
    run = _routed_run(
        {"Python": 154452},
        default_setup=(
            0,
            json.dumps({"state": "configured", "languages": ["actions", "python"]}),
            "",
        ),
    )
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "default-setup-covers"
    assert "default setup" in detail
    assert "python" in detail


def test_default_setup_not_covering_every_local_family_still_warns(tmp_path):
    """Must-fire pair for the test above: a default setup that is configured
    and does NOT list a family found locally is a real gap, not a pass."""
    _repo_with_python_outside_owned(tmp_path)
    (tmp_path / "app.go").write_text("package main\n", encoding="utf-8")
    run = _routed_run(
        {"Python": 154452, "Go": 4000},
        default_setup=(
            0,
            json.dumps({"state": "configured", "languages": ["python"]}),
            "",
        ),
    )
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "uncovered-outside-owned"
    assert "go" in detail


def test_default_setup_not_configured_keeps_the_original_warning(tmp_path):
    _repo_with_python_outside_owned(tmp_path)
    run = _routed_run(
        {"Python": 154452},
        default_setup=(0, json.dumps({"state": "not-configured"}), ""),
    )
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "uncovered-outside-owned"
    assert "python" in detail


def test_default_setup_404_keeps_the_original_warning(tmp_path):
    """A clean 404 is the issue's own second outcome: nothing is configured."""
    _repo_with_python_outside_owned(tmp_path)
    run = _routed_run(
        {"Python": 154452},
        default_setup=(1, "", "gh: Not Found (HTTP 404)"),
    )
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "uncovered-outside-owned"


def test_default_setup_403_is_never_folded_into_either_answer(tmp_path):
    """A permission-limited read that cannot see the setting must not render
    as a setting confirmed absent -- the rule `branch protection` in the same
    diagnostic already follows."""
    _repo_with_python_outside_owned(tmp_path)
    run = _routed_run(
        {"Python": 154452},
        default_setup=(1, "", "gh: Resource not accessible by integration (HTTP 403)"),
    )
    state, detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "403" in detail


def test_default_setup_unparseable_body_is_could_not_tell(tmp_path):
    _repo_with_python_outside_owned(tmp_path)
    run = _routed_run({"Python": 154452}, default_setup=(0, "not json", ""))
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"


def test_default_setup_is_not_called_when_nothing_sits_outside_owned(tmp_path):
    """Must-not-fire control: the owned-only and no-supported-language paths
    answer without the second forge call at all."""
    oss_dir = tmp_path / ".oss"
    oss_dir.mkdir()
    (oss_dir / "assemble_changelog.py").write_text("# vendored\n", encoding="utf-8")
    run = _routed_run({"Python": 1000}, default_setup=None)
    state, _detail = doctor.codeql_scan_state(tmp_path, config=_config(), run=run)
    assert state == "owned-only"
    assert not any(cmd[-1].endswith("/default-setup") for cmd in run.calls)


def test_check_codeql_scan_reports_ok_for_default_setup_coverage(tmp_path, capsys):
    _repo_with_python_outside_owned(tmp_path)
    run = _routed_run(
        {"Python": 154452},
        default_setup=(
            0,
            json.dumps({"state": "configured", "languages": ["python"]}),
            "",
        ),
    )
    doctor.check_codeql_scan(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "OK"
    assert out.startswith("OK ")
    assert "consider adding a CodeQL workflow" not in out
