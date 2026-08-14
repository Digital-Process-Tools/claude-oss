"""The doctor must print its findings, never fail to run.

Exit code 0 on every path, including the paths where everything is broken. A
diagnostic that exits non-zero gets swallowed by whatever ran it, and the one
output a stuck user needs is the one they do not see.

Three states, never two: OK, WARN, FAIL. A check that could not run says so and
must never render as a check that found nothing.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def run(cwd, args=(), project_dir=None):
    """CLAUDE_PROJECT_DIR is scrubbed unless a test asks for it.

    Inherited, it silently redirects every one of these runs at the developer's own
    repo, and each assertion below would then be about a tree the test never wrote.
    """
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(DOCTOR)] + [str(a) for a in args],
        cwd=str(cwd),
        env=env,
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


# --- #63: --root, end to end -----------------------------------------------------


def test_root_points_the_run_at_another_tree(tmp_path):
    """The test that could not be written before: point it at a fixture by argument."""
    target = tmp_path / "target"
    target.mkdir()
    _write_config(target)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    done = run(elsewhere, args=["--root", target])
    assert done.returncode == 0
    assert str(target) in done.stdout
    assert [ln for ln in done.stdout.splitlines() if ln.startswith("OK .oss.json")], done.stdout


def test_a_root_that_is_not_a_repo_is_a_finding_and_still_exits_zero(tmp_path):
    """The contract survives the flag: exit 0, one VERDICT, no traceback."""
    absent = tmp_path / "not-there"
    done = run(tmp_path, args=["--root", absent])
    assert done.returncode == 0
    assert "Traceback" not in done.stdout
    assert [ln for ln in done.stdout.splitlines() if ln.startswith("FAIL") and "directory" in ln]
    assert len([ln for ln in done.stdout.splitlines() if ln.startswith("VERDICT")]) == 1


def test_root_disagreeing_with_the_environment_is_reported(tmp_path):
    flagged = tmp_path / "flagged"
    flagged.mkdir()
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    _write_config(flagged)

    done = run(tmp_path, args=["--root", flagged], project_dir=env_dir)
    assert done.returncode == 0
    disagreements = [
        ln for ln in done.stdout.splitlines() if "CLAUDE_PROJECT_DIR" in ln and "WARN" in ln
    ]
    assert disagreements, done.stdout
    assert [ln for ln in done.stdout.splitlines() if ln.startswith("OK .oss.json")]


def test_the_environment_still_wins_over_cwd_when_no_root_is_given(tmp_path):
    """Positive control for the pair above: without --root, nothing disagrees."""
    target = tmp_path / "target"
    target.mkdir()
    _write_config(target)
    done = run(tmp_path, project_dir=target)
    assert done.returncode == 0
    assert not [ln for ln in done.stdout.splitlines() if "disagree" in ln]
    assert [ln for ln in done.stdout.splitlines() if ln.startswith("OK .oss.json")], done.stdout


# --- #62: unmeasured, end to end -------------------------------------------------


CONFIG_DEPENDENT = ("clone", "worktree_root", "state_file", "CI enforcement", "owned files")


def test_no_config_leaves_no_config_dependent_check_silent(tmp_path):
    """Silence is what this looked like before: the checks were skipped without a word."""
    empty = tmp_path / "empty"
    empty.mkdir()
    lines = run(tmp_path, args=["--root", empty]).stdout.splitlines()
    for label in CONFIG_DEPENDENT:
        matched = [ln for ln in lines if ln.startswith("WARN " + label + ":")]
        assert matched, "{} was silent: {}".format(label, lines)
        assert "not checked" in matched[0]


def test_a_found_config_measures_those_same_checks(tmp_path):
    """Positive control. Without it, the assertions above pass on a dead harness."""
    target = tmp_path / "target"
    target.mkdir()
    _write_config(target)
    out = run(tmp_path, args=["--root", target]).stdout
    assert "not checked" not in out, out


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
    project, local = oss_config.split(config)
    (root / oss_config.CONFIG_NAME).write_text(json.dumps(project, indent=2), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local, indent=2), encoding="utf-8"
    )
    return config
