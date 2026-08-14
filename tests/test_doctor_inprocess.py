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
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import oss_config  # noqa: E402
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
    project, local = oss_config.split(config)
    (root / oss_config.CONFIG_NAME).write_text(json.dumps(project, indent=2), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local, indent=2), encoding="utf-8"
    )
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


# --- #62: the four checks that depend on the config need a third state ------------
#
# Each pair below is one test on purpose. An assertion that a check said "not checked"
# also passes on a harness that produced no output at all, so the measured half sits in
# the same function and must report normally.


def test_check_directory_says_unmeasured_when_the_config_was_not_found(tmp_path):
    doctor.check_directory("clone", None, config_found=False)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not checked" in message
    assert ".oss.json" in message

    doctor.check_directory("clone", str(tmp_path))
    assert doctor.FINDINGS[-1] == ("OK", "clone: {}".format(tmp_path))


def test_check_state_file_says_unmeasured_when_the_config_was_not_found(tmp_path):
    doctor.check_state_file(tmp_path, None)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "state_file" in message and "not checked" in message

    (tmp_path / ".max").mkdir()
    (tmp_path / ".max" / "oss-watch.json").write_text("{}", encoding="utf-8")
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_ci_enforcement_says_unmeasured_when_the_config_was_not_found(tmp_path):
    doctor.check_ci_enforcement(tmp_path, None)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not checked" in message

    doctor.FINDINGS.clear()
    doctor.check_ci_enforcement(tmp_path, _config(tmp_path))
    assert doctor.FINDINGS, "the measured half of this pair reported nothing at all"
    assert not any("not checked" in m for _, m in doctor.FINDINGS)


def test_check_ci_enforcement_distinguishes_an_unimportable_scaffold(tmp_path, monkeypatch):
    """Two different reasons a check could not run, and they are not the same sentence."""
    config = _config(tmp_path)
    monkeypatch.setattr(doctor, "scaffold", None)
    doctor.check_ci_enforcement(tmp_path, config)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "scaffold" in message and "not checked" in message
    assert ".oss.json was not found" not in message


def test_check_freshness_says_the_owned_half_was_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])

    doctor.check_freshness(tmp_path, None)
    owned = [m for state, m in doctor.FINDINGS if "owned files" in m]
    assert owned, "the owned-drift half printed nothing at all"
    assert "not checked" in owned[-1]

    doctor.FINDINGS.clear()
    doctor.check_freshness(tmp_path, _config(tmp_path))
    assert not any("not checked" in m for _, m in doctor.FINDINGS)


UNMEASURED_LABELS = ("clone", "worktree_root", "state_file", "CI enforcement", "owned files")


def _quiet_main(monkeypatch):
    """Stub the boundaries that reach the network or the user's home directory.

    main() is the only place the four checks are wired together, so the pairing has to
    run it -- but not its probes.
    """
    monkeypatch.setattr(doctor, "check_tool", lambda *a, **k: None)
    monkeypatch.setattr(doctor, "check_memory", lambda *a, **k: None)
    monkeypatch.setattr(doctor, "check_jit_rules", lambda *a, **k: None)
    monkeypatch.setattr(doctor, "check_merge_permission", lambda *a, **k: None)
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])


def test_main_labels_every_config_dependent_check_unmeasured_and_still_measures_them(
    tmp_path, monkeypatch, capsys
):
    """The pairing #62 asks for, in one fixture.

    Without the second half, "said not checked" is satisfied by a run that said nothing.
    """
    _quiet_main(monkeypatch)
    missing = tmp_path / "missing"
    missing.mkdir()

    assert doctor.main(["--root", str(missing)]) == 0
    absent = capsys.readouterr().out
    for label in UNMEASURED_LABELS:
        matched = [
            ln for ln in absent.splitlines() if ln.startswith("WARN " + label + ":")
        ]
        assert matched, "no line at all for {}".format(label)
        assert "not checked" in matched[0], matched[0]

    doctor.FINDINGS.clear()
    present = tmp_path / "present"
    present.mkdir()
    _config(present)
    assert doctor.main(["--root", str(present)]) == 0
    found = capsys.readouterr().out
    assert "not checked" not in found, found
    for label in ("clone", "worktree_root", "state_file"):
        assert [ln for ln in found.splitlines() if label + ":" in ln], label


def test_a_root_that_does_not_exist_never_widens_to_the_cwds_clone(tmp_path, monkeypatch):
    """Found by running it, not by reading it.

    `resolve_config_path` widens a relative path to the enclosing clone, and it starts
    that search from `.` when the directory the path points into does not exist. So a
    --root at a path that is not there reported the config of whatever repo the caller
    happened to be standing in -- the exact defect this file is about, one layer up.
    """
    clone = tmp_path / "clone"
    inside = clone / "sub"
    inside.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", str(clone)])
    _config(clone)
    monkeypatch.chdir(inside)

    absent = tmp_path / "nowhere"
    doctor.check_config(absent)
    messages = [m for _, m in doctor.FINDINGS]
    assert messages, "check_config said nothing"
    assert not any(str(clone) in m for m in messages), messages
    assert any(str(absent) in m and "not found" in m for m in messages), messages

    # Positive control, same fixture and the same cwd: a project dir that IS inside the
    # clone must still widen to it. Without this, the assertion above is satisfied by a
    # widening that was disabled outright.
    doctor.FINDINGS.clear()
    doctor.check_config(inside)
    assert any("enclosing clone" in m for _, m in doctor.FINDINGS), doctor.FINDINGS


def test_the_clone_is_only_searched_with_a_path_the_clone_can_answer(tmp_path, monkeypatch):
    """`resolve_config_path` appends the relative path AS GIVEN to the clone.

    So only a bare `.oss.json` asks the clone for `<clone>/.oss.json`. Any relative path
    carrying directory components asks it for `<clone>/a/b/.oss.json`, which is not
    where a config lives -- and that path is what `os.path.relpath` returns whenever the
    project dir is not the current directory, or whenever it reaches this process
    unresolved while `os.getcwd()` is resolved. On macOS the second happens by default:
    `/tmp` is a symlink to `/private/tmp`, so a caller holding the `/tmp` spelling gets a
    five-level `../../../../..` relpath and the clone is asked a question about a
    directory that does not exist. Reported as `not found` with the file sitting in the
    clone all along -- the #53 defect, reintroduced by the fix for it.
    """
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", str(real)])
    _config(real)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    monkeypatch.chdir(link / "sub")
    doctor.check_config(link / "sub")
    assert any("enclosing clone" in m for _, m in doctor.FINDINGS), doctor.FINDINGS
    assert not any(state == "FAIL" for state, _ in doctor.FINDINGS), doctor.FINDINGS

    # Positive control for the negative above: pointed somewhere with no config at all,
    # this must still FAIL, or "no FAIL" is a statement about a dead code path.
    doctor.FINDINGS.clear()
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    doctor.check_config(bare)
    assert any(state == "FAIL" for state, _ in doctor.FINDINGS), doctor.FINDINGS


def test_a_project_dir_that_is_not_cwd_says_the_clone_was_not_searched(tmp_path):
    """The third state for the widening itself.

    It cannot run when the project dir is not the directory this process stands in, and
    "not found, run /oss:setup" is the wrong advice inside a worktree -- #53's whole
    point. So the run says the clone was not searched rather than implying it was.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    doctor.check_config(elsewhere)
    assert any("not searched" in m for _, m in doctor.FINDINGS), doctor.FINDINGS


def test_help_exits_zero_and_is_not_a_diagnostic_run(tmp_path):
    """--help prints usage and no VERDICT. That is the one non-diagnostic mode, and the
    exit code -- the thing callers branch on -- is still 0.
    """
    done = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "doctor.py"), "--help"],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert done.returncode == 0, done.stdout
    assert "--root" in done.stdout


# --- #63: --root -----------------------------------------------------------------


def test_root_flag_wins_over_the_environment(tmp_path):
    other = tmp_path / "env"
    other.mkdir()
    chosen, findings = doctor.resolve_project_dir(str(tmp_path), str(other), str(tmp_path))
    assert chosen == tmp_path
    assert any(state == "WARN" and "CLAUDE_PROJECT_DIR" in m for state, m in findings)


def test_root_flag_agreeing_with_the_environment_is_not_a_disagreement(tmp_path):
    _, findings = doctor.resolve_project_dir(str(tmp_path), str(tmp_path), str(tmp_path))
    assert not any("disagree" in m for _, m in findings)


def test_two_spellings_of_the_same_directory_do_not_disagree(tmp_path, monkeypatch):
    """`--root .` beside a CLAUDE_PROJECT_DIR naming the same place is not a conflict.

    Comparing Path objects makes it one: `Path(".") != Path("/abs/path")` however the
    same directory both are. A warning that fires on agreement is the noise that gets a
    real disagreement scrolled past.
    """
    monkeypatch.chdir(tmp_path)
    _, findings = doctor.resolve_project_dir(".", str(tmp_path), str(tmp_path))
    assert not any("disagree" in m for _, m in findings), findings

    # Positive control, same fixture: a genuinely different directory must still warn.
    other = tmp_path / "other"
    other.mkdir()
    _, findings = doctor.resolve_project_dir(".", str(other), str(tmp_path))
    assert any("disagree" in m for _, m in findings), findings


def test_the_environment_is_used_when_no_root_is_given(tmp_path):
    chosen, findings = doctor.resolve_project_dir(None, str(tmp_path), str(tmp_path / "cwd"))
    assert chosen == tmp_path
    assert findings and findings[0][0] == "OK"


def test_cwd_is_used_when_neither_is_given_and_says_it_is_a_guess(tmp_path):
    chosen, findings = doctor.resolve_project_dir(None, None, str(tmp_path))
    assert chosen == tmp_path
    assert findings[0][0] == "WARN"
    assert "guessed" in findings[0][1]


def test_a_root_that_is_not_a_directory_is_a_finding_not_a_crash(tmp_path):
    absent = tmp_path / "nope"
    chosen, findings = doctor.resolve_project_dir(str(absent), None, str(tmp_path))
    assert chosen == absent
    assert any(state == "FAIL" and "not a directory" in m for state, m in findings)


def test_a_root_that_is_a_directory_but_not_a_repo_warns(tmp_path):
    _, findings = doctor.resolve_project_dir(str(tmp_path), None, str(tmp_path))
    assert any(state == "WARN" and "git repository" in m for state, m in findings)

    (tmp_path / ".git").mkdir()
    _, findings = doctor.resolve_project_dir(str(tmp_path), None, str(tmp_path))
    assert not any("git repository" in m for _, m in findings)


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
    # A project-scope allow rule naming the merge op. Written in the project rather
    # than left to the real home directory: a check whose OK depends on whose laptop
    # the suite runs on is not a check.
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(./supertool 'gh-pr-merge:*')"]}}),
        encoding="utf-8",
    )
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
    # required_checks is set and a workflow actually runs the test command. A
    # scaffolded repo without both is the state the doctor now warns about -- the
    # tests are configured and nothing in CI runs them -- so a clean verdict has to
    # be built on a repo where that is untrue.
    config = _config(tmp_path, ci={"required_checks": 2})
    _fully_configured(tmp_path)
    scaffold.apply(tmp_path, config, plugin_root=REPO_ROOT)
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text(
        "jobs:\n  tests:\n    steps:\n      - run: pytest\n", encoding="utf-8"
    )
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


# --------------------------------------------------------------------------- #
# The merge permission.
#
# doctor reads settings files for an allow rule. That is a file read, not a
# probe of the harness, so the three states are about the RULE and never about
# the decision: present, absent, and could-not-look. The third one is why these
# are three tests and not two -- an unreadable settings file that rendered as
# "no rule" would send someone to add a rule they already have.
# --------------------------------------------------------------------------- #


def _settings(path, allow=None, deny=None):
    permissions = {}
    if allow is not None:
        permissions["allow"] = allow
    if deny is not None:
        permissions["deny"] = deny
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"permissions": permissions}), encoding="utf-8")
    return path


def _isolated_home(tmp_path):
    """No settings anywhere in it. Without this every test below would be asking
    about the machine it happens to run on."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def test_settings_candidates_survive_an_unresolvable_home(tmp_path, monkeypatch):
    """doctor exits 0 always. A machine with no HOME/USERPROFILE must lose user
    scope, not the whole run."""
    def _boom():
        raise RuntimeError("no home directory")

    monkeypatch.setattr(doctor.Path, "home", staticmethod(_boom))
    candidates = doctor.settings_candidates(tmp_path)
    assert len(candidates) == 2
    assert all(str(tmp_path) in str(path) for path in candidates)
    # And the check above it still answers rather than raising.
    assert doctor.merge_permission_state(tmp_path)[0] == "absent"


def test_merge_permission_state_present(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    state, _detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_merge_permission_state_absent_when_no_settings_exist(tmp_path):
    """Absent is not unknown. Nothing to read and unable to read are opposite
    findings with opposite remedies."""
    state, _detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "absent"


def test_merge_permission_state_absent_when_rules_name_other_ops(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr:*')", "Bash(git status)"],
    )
    state, _detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "absent"


def test_merge_permission_state_unknown_when_settings_are_malformed(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    state, detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "unknown"
    # str(path), not a POSIX literal: the separator is a backslash on Windows.
    assert str(path) in detail


def test_merge_permission_state_unknown_when_a_settings_file_cannot_be_opened(tmp_path):
    """The OSError arm, distinct from the JSON one. A directory where a file is
    expected raises IsADirectoryError on POSIX and PermissionError on Windows;
    both are OSError, which is what the check has to catch."""
    (tmp_path / ".claude" / "settings.local.json").mkdir(parents=True)
    state, _detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "unknown"


def test_a_readable_rule_beats_an_unreadable_neighbour(tmp_path):
    """Unknown means the question could not be answered. A rule that WAS read
    answers it, whatever the file beside it did."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    state, _detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_a_deny_rule_is_not_read_as_permission(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    state, detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "denied"
    assert "deny" in detail


def test_a_deny_beside_an_allow_is_still_denied(tmp_path):
    """Deny wins, and the scan reads every candidate before deciding. Returning on
    the first allow reported `present` while holding an already-parsed deny for the
    same op -- an OK built on evidence the check dropped."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr-merge:*')"],
        deny=["Bash(./supertool 'gh-pr-merge:42:squash|force')"],
    )
    state, _detail = doctor.merge_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "denied"


def test_check_merge_permission_reports_a_deny_rule(tmp_path, capsys):
    """The fourth arm reaching the report. Only the state function was covered, so
    a mistake in this branch's severity or wording would have shipped."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "deny rule" in out
    # Not escalated to FAIL: this is still a file read, and it cannot prove the
    # harness will refuse any more than an allow rule proves it will permit.
    assert "FAIL" not in out


def test_a_rule_in_the_home_settings_counts(tmp_path):
    """The rule can live in user scope. Ignoring that would WARN at a maintainer
    who already arranged it -- and the fix they would then apply is a duplicate."""
    home = _isolated_home(tmp_path)
    _settings(home / ".claude" / "settings.json", allow=["Bash(./supertool 'gh-pr-merge:*')"])
    state, _detail = doctor.merge_permission_state(tmp_path, home=home)
    assert state == "present"


def test_check_merge_permission_ok_does_not_promise_the_merge_will_run(tmp_path, capsys):
    """The whole judgment of this check. An OK saying "the merge is permitted"
    is a file read presented as a probe of the harness -- the absence-read-as-fact
    this plugin is named after, one layer out."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert "not a probe" in out
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_merge_permission_warns_and_names_the_file_to_add_it_to(tmp_path, capsys):
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert ".claude/settings.local.json" in out
    # The WARN must not overclaim either: a rule is not the only thing that can
    # allow the call, so "no rule found" is not "the merge will be denied".
    assert "not the only thing" in out


def test_check_merge_permission_says_it_could_not_look(tmp_path, capsys):
    """The unknown arm reaching the report. Untested, it renders as a pass the
    first time it fires."""
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not" in out
    assert "no rule" not in out


# --- #71: the audited tree must not be able to write doctor's own lines -----------

FORGED = ("OK all gates passed", "WARN everything is fine", "VERDICT: ok")

HOSTILE_ENTRY = (
    "Bash(gh-pr-merge)\nOK all gates passed\r"
    "WARN everything is fine\x1b[31m\nVERDICT: ok"
)


def test_report_reduces_anything_it_is_handed_to_one_printable_line(capsys):
    """The choke point, not one call site. Every finding doctor prints is built
    from a string somebody else may have chosen -- a settings entry, a path, a
    subprocess's stderr -- and a sanitiser applied at one of several call sites
    leaves the next one to rediscover this."""
    doctor.report("OK", HOSTILE_ENTRY)
    out = capsys.readouterr().out
    assert out.count("\n") == 1, repr(out)
    assert "\x1b" not in out
    assert "\r" not in out
    for forged in FORGED:
        assert not out.startswith(forged)


def test_a_settings_entry_cannot_write_doctors_own_lines(tmp_path, capsys):
    """`.claude/settings.json` is tracked in a managed repo, so a pull-request
    contributor writes it. Before this, an entry carrying newlines put attacker-
    chosen OK/WARN lines -- and a forged VERDICT -- at column 0 of the maintainer's
    next /oss:doctor.

    The benign entry beside it is the positive control: an assertion that nothing
    was forged also passes when the check produced no output at all.
    """
    hostile = _settings(tmp_path / ".claude" / "settings.json", allow=[HOSTILE_ENTRY])
    benign = _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out

    # Positive control: the check ran, found the rule, and still says where.
    assert out.startswith("OK ")
    assert doctor.FINDINGS[-1][0] == "OK"
    assert str(hostile) in out
    assert str(benign) in out

    # One line per finding, and none of them supplied by the fixture.
    lines = out.rstrip("\n").split("\n")
    assert len(lines) == 1, lines
    for forged in FORGED:
        assert not any(line.startswith(forged) for line in lines), lines
    assert "\x1b" not in out


def test_a_hostile_deny_entry_is_flattened_too(tmp_path, capsys):
    """The deny arm reaches report() by its own path. Fixing only the allow arm
    leaves the same forgery one key away."""
    _settings(tmp_path / ".claude" / "settings.json", deny=[HOSTILE_ENTRY])
    benign = _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(./supertool 'gh-pr-merge:42')"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert str(benign) in out
    assert len(out.rstrip("\n").split("\n")) == 1, out
    for forged in FORGED:
        assert not out.startswith(forged)


def test_the_report_does_not_quote_the_entry_text_back(tmp_path, capsys):
    """Counts and paths answer the question doctor is asking; the entry text never
    did. Not printing it is what makes this safe rather than merely escaped."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool 'gh-pr-merge:*')"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert "supertool" not in out
    assert "1 allow" in out


def test_a_truncated_finding_says_it_was_truncated(capsys):
    """A finding cut off at the limit without saying so is a partial answer
    rendered as a whole one -- the same class as a check that could not run
    rendering as a check that found nothing."""
    doctor.report("WARN", "x" * (doctor.REPORT_LIMIT * 2))
    out = capsys.readouterr().out.rstrip("\n")
    assert out.endswith(" ...")
    assert len(out) == len("WARN ") + doctor.REPORT_LIMIT
    # Positive control: a message under the limit is passed through whole.
    doctor.report("WARN", "y" * 40)
    assert capsys.readouterr().out.rstrip("\n") == "WARN " + "y" * 40


def test_a_message_exactly_at_the_limit_is_not_marked_truncated(capsys):
    """The boundary, because the cheap test of "was it cut" -- length equals the
    limit -- is also true of a message that fit exactly. Read that way, report()
    drops four real characters and then appends an ellipsis saying it dropped
    more: a complete finding rendered as a partial one, which is the inverse of
    the bug the marker exists to prevent."""
    doctor.report("WARN", "z" * doctor.REPORT_LIMIT)
    out = capsys.readouterr().out.rstrip("\n")
    assert out == "WARN " + "z" * doctor.REPORT_LIMIT
    assert not out.endswith(" ...")


def test_the_verdict_line_counts_only_findings_doctor_itself_recorded(tmp_path, capsys):
    """FINDINGS drives the verdict, so a state forged into a message must not be
    countable. It never was -- the state is the first tuple element, not parsed
    out of the text -- and this pins that, because the fix above changed what
    lands in FINDINGS."""
    _settings(tmp_path / ".claude" / "settings.json", allow=[HOSTILE_ENTRY])
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    capsys.readouterr()
    assert [state for state, _ in doctor.FINDINGS] == ["OK"]
