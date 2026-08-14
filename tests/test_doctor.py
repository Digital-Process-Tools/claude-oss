"""The doctor must print its findings, never fail to run.

Exit code 0 on every path, including the paths where everything is broken. A
diagnostic that exits non-zero gets swallowed by whatever ran it, and the one
output a stuck user needs is the one they do not see.

Three states, never two: OK, WARN, FAIL. A check that could not run says so and
must never render as a check that found nothing.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def run(cwd):
    return subprocess.run(
        [sys.executable, str(DOCTOR)],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def test_exits_zero_with_nothing_configured(tmp_path):
    """The worst case is also the case most likely to be run."""
    assert run(tmp_path).returncode == 0


def test_exits_zero_on_a_healthy_repo(tmp_path):
    _write_config(tmp_path)
    assert run(tmp_path).returncode == 0


def test_prints_the_plugin_version_even_when_everything_else_fails(tmp_path):
    """The version is read straight off the manifest, independent of any path
    resolution, so it survives the failure that made the user run this.
    """
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["version"] in run(tmp_path).stdout


def test_every_line_is_one_of_three_states(tmp_path):
    out = run(tmp_path).stdout
    body = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("VERDICT")]
    assert body, "doctor printed no findings"
    for line in body:
        assert line.split()[0] in ("OK", "WARN", "FAIL"), line


def test_ends_on_exactly_one_verdict_line(tmp_path):
    verdicts = [ln for ln in run(tmp_path).stdout.splitlines() if ln.startswith("VERDICT")]
    assert len(verdicts) == 1
    assert run(tmp_path).stdout.rstrip().splitlines()[-1].startswith("VERDICT")


def test_a_missing_config_is_a_named_failure_not_a_crash(tmp_path):
    out = run(tmp_path).stdout
    assert "FAIL" in out
    assert ".oss.json" in out
    assert "/oss:setup" in out


def test_a_malformed_config_says_so(tmp_path):
    (tmp_path / ".oss.json").write_text("{ broken", encoding="utf-8")
    out = run(tmp_path).stdout
    assert "FAIL" in out and "parse" in out.lower()


def test_a_config_with_a_secret_key_is_flagged(tmp_path):
    _write_config(tmp_path, extra={"gh_token": "ghp_example"})
    out = run(tmp_path).stdout
    assert "gh_token" in out
    assert "FAIL" in out


def test_never_prints_a_config_value_that_looks_like_a_credential(tmp_path):
    """Flagging the key must not echo the value into a terminal or a transcript."""
    _write_config(tmp_path, extra={"gh_token": "ghp_SUPERSECRET"})
    assert "ghp_SUPERSECRET" not in run(tmp_path).stdout


def test_output_carries_no_ansi_escapes(tmp_path):
    """Git Bash renders colour codes as noise, and this output gets pasted."""
    assert "\x1b[" not in run(tmp_path).stdout


def test_a_check_that_cannot_run_reports_skipped_state_not_success(tmp_path):
    """An absent clone directory is unknown, not fine. WARN is the third state here:
    the check ran and could not answer.
    """
    _write_config(tmp_path, overrides={"clone": str(tmp_path / "nope")})
    out = run(tmp_path).stdout
    assert "WARN" in out or "FAIL" in out
    assert "clone" in out.lower()


def test_a_verified_test_command_no_workflow_runs_is_a_warning(tmp_path):
    """Green from a changelog check and an org scan says nothing about the tests."""
    _write_config(tmp_path)
    # Matched on a phrase, not on "test_command": pytest builds tmp_path from the
    # test function name, so a substring of the name is present in every path the
    # doctor prints and would satisfy the search on its own.
    lines = [ln for ln in run(tmp_path).stdout.splitlines() if "runs it" in ln]
    assert lines, "the doctor never mentioned the configured test command"
    assert lines[0].startswith("WARN"), lines[0]
    assert "pytest" in lines[0]


def test_a_test_command_a_workflow_runs_is_not_warned_about(tmp_path):
    """Positive control: the warning above has an off state."""
    _write_config(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "test.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - run: pytest\n", encoding="utf-8"
    )
    offenders = [
        ln
        for ln in run(tmp_path).stdout.splitlines()
        if ln.startswith("WARN") and "runs it" in ln
    ]
    assert not offenders, offenders


def _write_config(root, overrides=None, extra=None):
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
    config.update(overrides or {})
    config.update(extra or {})
    (root / ".oss.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config
