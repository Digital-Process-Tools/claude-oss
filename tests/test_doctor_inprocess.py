"""doctor.py driven in-process.

test_doctor.py runs it as a subprocess, which is the honest end-to-end check: it is
how a user invokes it, and it is the only way to assert the real exit code. But
coverage cannot see inside a subprocess, so that suite reports 0% for a file it
exercises thoroughly -- a measurement saying "untested" about tested code, which is
the same defect class this plugin is about.

So both: subprocess for the contract, in-process for the branches.
"""

import json
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import doctor  # noqa: E402
import spawn_guard  # noqa: E402
import oss_config  # noqa: E402
import scaffold  # noqa: E402

# Captured before any test's autouse fixture can monkeypatch the module
# attribute -- `_watch_name_accepted_by_default` below replaces
# `doctor._consumer_watch_name_verdict` for every test in this file, and the
# two tests that exercise the real mechanism need the real function under
# that stub, not the stub itself.
_REAL_CONSUMER_WATCH_NAME_VERDICT = doctor._consumer_watch_name_verdict
_REAL_WATCH_DECLARATION_SPLIT = doctor._watch_declaration_split


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


@pytest.fixture(autouse=True)
def _unpin_the_watch_channel(monkeypatch):
    """`SUPERTOOL_WATCH_NAME` is popped for the same reason PATH and HOME are.

    `doctor.main()` reads the real environment, and `bin/oss-workspace` EXPORTS this
    variable into every session it opens -- so running this suite from inside a
    maintainer session made `test_verdict_says_ok_only_when_nothing_warned` red with
    `watch channel: SUPERTOOL_WATCH_NAME is exported ... not what .oss.json's repo
    derives to`, correctly, about the developer's machine rather than about the code.
    CI has nothing exported, so the leg that would have caught it is the one that
    cannot: green in the matrix, red on the machine of anybody who uses the launcher
    this plugin ships.

    Autouse and popped BEFORE the test body, so the tests that set it deliberately
    (`monkeypatch.setenv`, or an explicit `env=` argument) still decide their own
    answer. Found while fixing #207; the mechanism is unrelated to it.
    """
    monkeypatch.delenv("SUPERTOOL_WATCH_NAME", raising=False)


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


def _state_file(tmp_path, body):
    directory = tmp_path / ".max"
    directory.mkdir(exist_ok=True)
    path = directory / "oss-watch.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_state_file_present_is_ok(tmp_path):
    _state_file(tmp_path, "[]")
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    assert doctor.FINDINGS[-1][0] == "OK"


# --- #149: present is not the question ---------------------------------------------


def test_state_file_present_but_unreadable_by_the_writer_is_not_ok(tmp_path):
    """A pre-plugin state file is a dict keyed `tick_<ISO>`; `oss_state` wants a list.

    Doctor used to report it OK on `path.is_file()` alone, so the one step that would
    have caught it before a tick's work was spent reported the file as fine. The
    readable half sits in the same function: an assertion that the dict is not OK also
    passes when nothing at all is OK.
    """
    _state_file(tmp_path, json.dumps({"tick_2026-08-01T09:00:00Z": {"decision": "x"}}))
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "--migrate" in message

    _state_file(tmp_path, json.dumps([{"at": "2026-08-01T09:00:00Z", "decision": "x"}]))
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    assert doctor.FINDINGS[-1][0] == "OK"


def test_state_file_says_unmeasured_when_oss_state_could_not_be_imported(
    tmp_path, monkeypatch
):
    """The shape lives in oss_state, so a broken install cannot judge the file.

    Without this arm the check would either crash or quietly grade the file on nothing
    -- and a doctor run on exactly the broken install it exists to diagnose is the run
    that would hit it.
    """
    _state_file(tmp_path, "[]")
    monkeypatch.setattr(doctor, "oss_state", None)
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not checked" in message

    # Must-fire control, same fixture and same file: with the module there, it grades.
    monkeypatch.undo()
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    assert doctor.FINDINGS[-1][0] == "OK"


def test_state_file_that_cannot_be_read_at_all_warns_rather_than_raising(tmp_path):
    """Exit 0 always, one VERDICT line -- a check that raises takes the contract out.

    A directory standing where the state file should be fails the read on every
    platform without a permission fixture: POSIX raises `IsADirectoryError`, Windows
    raises `PermissionError`, both are `OSError`, and neither is `FileNotFoundError`.
    """
    (tmp_path / ".max").mkdir()
    (tmp_path / ".max" / "oss-watch.json").mkdir()
    doctor.check_state_file(tmp_path, {"state_file": ".max/oss-watch.json"})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not written yet" not in message


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

    _state_file(tmp_path, "[]")
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
    # #621 self-review: a real `claude mcp get oss-channel` call, which answers
    # about THIS machine's registrations -- not about the fixture -- and would
    # make the suite non-hermetic on any dev machine that happens to have
    # `claude` on PATH.
    monkeypatch.setattr(doctor, "check_mcp_channel_registration", lambda **k: None)


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
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: None)
    doctor.check_tool("nonexistent-tool", ["nonexistent-tool", "--version"])
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not on PATH" in message


def test_check_tool_warns_when_present_but_failing(monkeypatch):
    """Present-and-broken is its own state. Reporting it as absent would send someone
    to install a tool they already have.
    """
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: "/bin/false")
    doctor.check_tool("git", [sys.executable, "-c", "import sys; sys.exit(3)"])
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "returned 3" in message


def test_check_tool_warns_when_the_probe_cannot_spawn(monkeypatch):
    """An unspawnable binary must reach the tool-failed arm, not raise. This is the
    cross-platform shape: Windows raises where POSIX would have run something.
    """
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: "/definitely/not/here")
    doctor.check_tool("git", ["/definitely/not/here", "--version"])
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "would not run" in message


def test_check_tool_reports_ok_on_a_zero_exit(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: sys.executable)
    doctor.check_tool("python", [sys.executable, "-c", "pass"])
    assert doctor.FINDINGS[-1][0] == "OK"


def _undecodable_byte():
    """A byte this runner's locale codec rejects, and the codec's name.

    Measured, not tabulated. Text-mode ``subprocess`` decodes with
    ``locale.getpreferredencoding(False)``, and which bytes that codec rejects is a
    property of the runner rather than of a platform anyone can name: UTF-8 rejects a
    lone ``0x80``, cp1252 maps ``0x80`` to a euro sign and rejects ``0x81``, and
    latin-1 rejects nothing at all. A hardcoded byte would therefore be green on some
    legs by never constructing the condition the test is about.

    Returns ``(None, encoding)`` when the codec decodes every byte. That is the third
    state -- the case cannot be built here -- and it is not a pass.
    """
    encoding = locale.getpreferredencoding(False)
    for value in range(0x80, 0x100):
        try:
            bytes([value]).decode(encoding)
        except UnicodeDecodeError:
            return value, encoding
    return None, encoding


def test_check_tool_survives_a_banner_this_locale_cannot_decode(monkeypatch, tmp_path):
    """A dependency whose ``--version`` banner carries one undecodable byte must reach
    a finding, not a traceback.

    ``doctor.py``'s contract is exit 0 and one VERDICT line. Text mode made the probe
    decode output that no arm of ``check_tool`` reads -- both branch on ``returncode``
    alone -- so a copyright sign in a banner, met by the wrong locale, killed the
    diagnostic from a decode with no consumer.
    """
    bad, encoding = _undecodable_byte()
    if bad is None:
        pytest.skip(
            "locale codec {!r} decodes every byte, so an undecodable banner cannot be "
            "built here; check_tool's behaviour on one went untested".format(encoding)
        )

    # PATH is pinned at an empty directory. Every argv[0] below is an absolute
    # interpreter path, so nothing should resolve a name against it -- pinning makes
    # that structural rather than argued. A suite that finds a real tool where its
    # fixture should have been has run something nobody asked for.
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: sys.executable)

    emit_bad = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(bytes([{}])); sys.stdout.flush()".format(bad),
    ]

    # Control: the fixture really does put that byte on the pipe. Read in bytes mode,
    # the one way to look without triggering the defect under test.
    emitted = spawn_guard.run(
        emit_bad,
        subject="whether the fixture really does put an undecodable byte on the pipe",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    assert emitted.returncode == 0
    assert bytes([bad]) in emitted.stdout, (
        "fixture emitted {!r}, not the undecodable byte this test is about".format(
            emitted.stdout
        )
    )

    doctor.check_tool("undecodable", emit_bad)
    assert doctor.FINDINGS[-1] == ("OK", "undecodable: available")

    # Positive control, same fixture: a probe with a clean banner reaches the same arm.
    # Without it, "OK was reported" cannot tell a working probe from one never invoked.
    doctor.check_tool(
        "ascii",
        [sys.executable, "-c", "import sys; sys.stdout.write('tool 1.2.3')"],
    )
    assert doctor.FINDINGS[-1] == ("OK", "ascii: available")


def test_main_returns_zero_and_ends_on_a_verdict(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: None)
    assert doctor.main() == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1].startswith("VERDICT:")


def _fully_configured(root):
    """Everything the doctor checks, present and current.

    Written out rather than stubbed: the point of this test is that `VERDICT: ok`
    requires every check to pass, so the fixture has to satisfy every check.
    """
    (root / "wt").mkdir(exist_ok=True)
    (root / ".max").mkdir(exist_ok=True)
    # A registered radar tier AND a route to the op that reads it (#191). Both are
    # needed and each is silent about the other, so a fixture carrying one of them
    # is a repo whose board publishes nothing -- which is exactly the state this
    # suite would then be calling `VERDICT: ok`.
    (root / doctor.WATCH_CONFIG).write_text(
        json.dumps(
            {
                "presets": [doctor.WATCH_PRESET],
                "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
            }
        ),
        encoding="utf-8",
    )
    # A list, because that is what /oss:tick writes and reads. It said `{}` until #149 --
    # this suite's own idea of a fully configured repo carried the one shape the tick
    # cannot use, and the doctor called it OK.
    (root / ".max" / "oss-watch.json").write_text("[]", encoding="utf-8")
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


def _entry_point_linked(monkeypatch):
    """`./supertool` present and pointing at the plugin's own supertool.py (#285).

    Stubbed at the state boundary, not by replacing `check_supertool_entry_point`, for
    the same reason `_dependencies_current` stubs the fetch: the message selection stays
    real, so this test still covers how that check's OK line reaches the verdict.

    It is stubbed at all for the reason `check_tool` three lines below it is. The link
    is created by supertool's session-start hook against the directory a *session* opens
    in, so no repository fixture can establish it -- a tmp_path a test just made has
    never had a session opened in it, by construction. Asserting it here would be
    asserting that the harness ran another plugin's hook.
    """
    monkeypatch.setattr(
        doctor,
        "supertool_entry_point",
        lambda project_dir, cache_root=None, record=None: ("ok", "<the plugin's copy>"),
    )


def _oss_workspace_launcher_matched(monkeypatch):
    """PATH's `oss-workspace` matching the running install (#289).

    Stubbed at the state boundary like `_entry_point_linked`, for the same reason:
    no repository fixture can put a real `~/.local/bin` symlink on this machine's
    actual PATH, so asserting it here would be asserting that this developer's
    machine happens to have the launcher linked and current.
    """
    monkeypatch.setattr(
        doctor,
        "oss_workspace_launcher_state",
        lambda plugin_root=None, path=None: ("matched", "<the plugin's copy>"),
    )


def test_verdict_says_ok_only_when_nothing_warned(tmp_path, monkeypatch, capsys):
    # A workflow actually runs the test command, and the config carries no leftover
    # `ci` block. Both are states the doctor warns about -- tests configured with
    # nothing in CI running them, and the key #113 deleted still on disk -- so a clean
    # verdict has to be built on a repo where neither is true.
    #
    # #564: `check_gitignore_hides_config` needs a real `git check-ignore` to answer
    # "clear" rather than "could not ask" -- and "could not ask" is a WARN, correctly,
    # so a fixture claiming to be genuinely clean has to be a real git repo for that
    # check to have anything to say OK about.
    done = subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {}".format(done.stderr.strip() or done.returncode))
    config = _config(tmp_path)
    _fully_configured(tmp_path)
    scaffold.apply(tmp_path, config, plugin_root=REPO_ROOT)
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text(
        "jobs:\n  tests:\n    steps:\n      - run: pytest\n", encoding="utf-8"
    )
    _dependencies_current(monkeypatch)
    _entry_point_linked(monkeypatch)
    _oss_workspace_launcher_matched(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    # `plugin copy scope` is a WARN whenever nothing named the root this invocation
    # resolved from, and that is not a gap in the repo -- it is the check saying it
    # could not establish which copy answered. A clean verdict therefore needs the
    # invocation to name one, which is exactly what `/oss:doctor` now passes (#262).
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(doctor.PLUGIN_ROOT))
    # `name != "sh"` self-review finding (CI failure on windows-latest, 3.10-3.12,
    # after #495): this blanket stub used to fake EVERY tool name as found, which was
    # harmless before #495 -- nothing this fixture exercises consulted `shutil.which`
    # for a name this test cared about measuring. #495 gave `check_auto_update` and
    # `_statusline_windows_gap` a real `shutil.which("sh")` call each, and this same
    # stub (patching the shared `shutil` module object, not a `doctor`-local copy)
    # silently answered "sh is on PATH" for both regardless of the real machine --
    # so on Windows CI the POSIX-syntax WARN this test hardcoded as "1 warning(s)"
    # was suppressed by the fixture's own stub, and the count went stale. Excluding
    # "sh" leaves it answering for real, which is exactly what #495 asks a caller to
    # measure rather than infer.
    real_which = shutil.which
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name, **kwargs: real_which(name, **kwargs) if name == "sh" else sys.executable,
    )
    monkeypatch.setattr(doctor, "check_tool", lambda name, probe: doctor.report("OK", name))
    # #386: `check_gh_binary` probes THIS machine's real `gh`, independent of the
    # `check_tool` stub above -- and this repo's own dev machine is exactly the
    # Rosetta-gh case #386 was filed from, which would turn a "fully configured,
    # everything clean" fixture into a real WARN about a fact this test is not
    # about. Stubbed the same way `check_tool` is.
    monkeypatch.setattr(doctor, "check_gh_binary", lambda: doctor.report("OK", "gh binary"))
    # #551: reads the status line's real cache directory and makes a real `gh` call
    # to compare against it -- neither of which this fixture's "fully configured"
    # tree can fake, and both are already covered on their own terms by
    # tests/test_doctor_latest_skew_551.py. Stubbed the same way check_tool/
    # check_gh_binary are: the message selection for THIS check is not what this
    # test is about, only whether its OK reaches the aggregated verdict.
    monkeypatch.setattr(
        doctor, "check_latest_skew", lambda project_dir, config: doctor.report("OK", "latest skew")
    )
    # #621: a real subprocess call to `claude mcp get oss-channel`, which answers
    # about THIS machine's MCP registrations -- not about this fixture's tree --
    # exactly the same reason check_gh_binary and check_latest_skew are stubbed
    # above rather than measured here.
    monkeypatch.setattr(
        doctor,
        "check_mcp_channel_registration",
        lambda **kw: doctor.report("OK", "channel MCP registration"),
    )
    # #646: reads THIS machine's real MCP registration too (its own `claude mcp
    # get` call, independent of the stub above), for the same reason.
    monkeypatch.setattr(doctor, "check_channel_consumer_pin", lambda **kw: None)
    # #638: real subprocess calls to each declared dependency's own diagnostic
    # (a supertool op, two versioned bash scripts) -- answers about what is
    # actually installed on THIS machine, not about this fixture's tree,
    # exactly the same reason check_mcp_channel_registration is stubbed above
    # rather than measured here.
    monkeypatch.setattr(
        doctor,
        "check_dependency_diagnostics",
        lambda *a, **kw: doctor.report("OK", "dependency diagnostics"),
    )
    doctor.main()
    out = capsys.readouterr().out
    # #495 self-review: whether either of the two Windows gaps below is real is a
    # question about THIS machine, never a table keyed on `os.name` alone -- a
    # `windows-latest` runner ships Git Bash, and whether that puts `sh` on PATH for
    # the process this test runs in is exactly what went unmeasured in the CI
    # failure this replaces. Both checks (`_statusline_windows_gap`,
    # `check_auto_update`'s no-receipt arm) key on the identical `shutil.which("sh")`
    # signal in production, so the expected warning count is built from measuring it
    # once here too, rather than asserting either count as a given.
    sh_here = shutil.which("sh") is not None
    expected = []
    if not sh_here:
        expected.append("WARN auto-update:")
    if os.name == "nt" and not sh_here:
        expected.append("WARN statusline:")
    if expected:
        assert "VERDICT: usable with gaps -- {} warning(s)".format(len(expected)) in out, out
        for prefix in expected:
            assert prefix in out, out
        if "WARN statusline:" in expected:
            assert "%CLAUDE_PROJECT_DIR%" in out, out
        if "WARN auto-update:" in expected:
            assert "not resolvable" in out, out
    else:
        # The must-not-fire control: `sh` resolvable (every machine observed so far,
        # including `windows-latest`'s Git Bash) means neither gap applies, and the
        # fully-scaffolded fixture is genuinely clean.
        assert "VERDICT: ok" in out, out


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


# ------------------------------------------------- agent dispatch (#81)
#
# What this check can and cannot see is the point of it. It cross-references the
# `oss:NAME` spawns written into this plugin's own documents against the agent files
# it ships -- a fact on disk. It cannot see whether the harness registers any of
# them, because that lives in a registry no python process can read, and #81 is what
# leaving that unsaid costs: two of four shipped agents unreachable, the release
# gate's blocking audit dispatching to nothing, for two versions, with no signal.
#
# So the boundary rides on the line rather than being omitted from it, and the
# vacuous state -- nothing scanned -- is a warning rather than a clean report.


def _fake_plugin(root, documents, agents):
    for relative, text in documents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    agent_dir = root / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    for name in agents:
        (agent_dir / (name + ".md")).write_text("name: " + name, encoding="utf-8")
    return root


def test_agent_dispatch_is_clean_on_this_plugin_and_still_states_what_it_cannot_know():
    lines = doctor.agent_dispatch()
    assert lines, "agent_dispatch reported nothing at all"
    joined = " ".join(message for _, message in lines)

    # Every shipped agent named individually (#140), and read off disk rather than out
    # of a list in the checker or in this test.
    shipped = sorted(path.stem for path in (REPO_ROOT / "agents").glob("*.md"))
    assert shipped, "no agent files -- the assertions below would be vacuous"
    for name in shipped:
        assert "oss:" + name in joined, name

    # The clause that keeps this from reading as "the agents work", and the remedy for
    # the only failure anyone has observed.
    assert "cannot be determined from here" in joined, joined
    assert "registry" in joined, joined
    assert "/reload-plugins" in joined, joined

    # And it must NOT borrow "not checked", which two suites pin to "the config was
    # absent". A phrase reused is an invariant retired.
    assert "not checked" not in joined, joined

    # OK, not WARN. A sentence equally true on every machine forever is not a finding,
    # and counting it would pin every repo's verdict at "usable with gaps".
    assert not [level for level, _ in lines if level != "OK"], lines


def test_agent_dispatch_fails_on_a_name_no_file_ships(tmp_path):
    """Positive control for the finding state."""
    root = _fake_plugin(
        tmp_path,
        {"commands/release.md": 'Agent(subagent_type: "oss:ghost")'},
        ["developer"],
    )
    lines = doctor.agent_dispatch(root)
    assert [level for level, _ in lines] == ["FAIL"], lines
    assert "ghost" in lines[0][1]


def test_agent_dispatch_warns_rather_than_passing_when_it_scanned_nothing(tmp_path):
    """The vacuous state. A plugin root with no documents yields no dispatched names,
    and "no name is missing a file" is trivially true of the empty set -- which would
    print an OK line about a tree the check never found. It must say so instead.
    """
    lines = doctor.agent_dispatch(tmp_path / "nowhere")
    assert [level for level, _ in lines] == ["WARN"], lines
    assert "could not be checked" in lines[0][1]
    # And not the reserved phrase: commands/doctor.md tells its reader every `not
    # checked` line means .oss.json was absent. This one means the plugin's own tree
    # was, which is a finding rather than expected fallout from unset config.
    assert "not checked" not in lines[0][1], lines[0][1]


def test_agent_dispatch_reports_a_document_it_could_not_read(tmp_path):
    """A file that cannot be read is a hole in the cross-reference, not an absence of
    findings. Skipping it silently would let a rename hide behind a permissions error.
    """
    root = _fake_plugin(
        tmp_path,
        {"commands/release.md": 'Agent(subagent_type: "oss:developer")'},
        ["developer"],
    )
    unreadable = root / "commands" / "broken.md"
    unreadable.write_text("x", encoding="utf-8")
    try:
        unreadable.chmod(0o000)
        if os.access(str(unreadable), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 file (root, or a filesystem without "
                "POSIX modes), so the unreadable-document arm cannot be reached here"
            )
        lines = doctor.agent_dispatch(root)
    finally:
        unreadable.chmod(0o644)
    warnings = [message for level, message in lines if level == "WARN"]
    assert warnings, lines
    assert "broken.md" in " ".join(warnings)


def test_check_agent_dispatch_prints_every_line_it_produced(capsys):
    doctor.check_agent_dispatch()
    out = capsys.readouterr().out
    assert out.strip(), "check_agent_dispatch printed nothing"
    assert len(doctor.FINDINGS) == len(out.strip().splitlines())


# --- the watch channel (#150) -------------------------------------------------
#
# The reported symptom is four repos resolving to one poller slot because one
# `SUPERTOOL_WATCH_NAME` was hand-copied between machines' settings files. The
# thing that makes it invisible is that a shared fleet and a private one render
# identically, so every arm below asserts a DISTINCT state -- an assertion that
# two arms merely both produce a WARN would reproduce the defect in the test.


def _supertool_config(root, doc):
    (root / doctor.WATCH_CONFIG).write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture(autouse=True)
def _watch_name_accepted_by_default(monkeypatch):
    """#533 taught `check_watch_channel` to ask the installed supertool whether
    it will accept the name a state agreed on, and every test above this line
    was written before that existed -- it built a name and asserted OK with
    no opinion on whether some consumer would take it. Patching the ask keeps
    those assertions about the DECLARATION comparison, isolated from whatever
    supertool happens to be installed on the machine running the suite (there
    may be none at all, which is the CI case and would otherwise turn every
    OK above into a WARN). The tests that exercise the asking mechanism
    itself override this explicitly, per fixture-shadowing rules."""
    monkeypatch.setattr(
        doctor, "_consumer_watch_name_verdict", lambda name: ("accepted", "")
    )


@pytest.fixture(autouse=True)
def _watch_declaration_split_reads_fully_declared_by_default(monkeypatch):
    """#623 sibling of the fixture above, same reasoning: every test above this
    line was written before `_watch_declaration_split` existed, declaring a
    name on ONE op block (`radar`) and asserting on the OLD states
    (`agree`/`declared-only`/`derived-export`/`derived`). Against the real
    installed supertool that fixture shape genuinely IS half-declared, which
    would turn every one of those into `partial` and break an assertion about
    something else entirely. Patched to `found` with nothing silent -- "as far
    as this repo declares, every watch op has it" -- so the existing
    single-op fixtures keep exercising what they were written to exercise.
    The tests that exercise the split itself override this explicitly, per
    fixture-shadowing rules, the same way `_watch_name_accepted_by_default`'s
    own overrides work.
    """
    monkeypatch.setattr(
        doctor, "_watch_declaration_split", lambda project_dir: ("found", (), (), "")
    )


def test_watch_channel_agrees_when_the_export_matches_the_declaration(tmp_path):
    """The must-not-fire arm. Its control is the test directly below, which uses
    the same fixture and changes only the exported value."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    state, _detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss"}
    )
    assert state == "agree"


def test_watch_channel_reports_a_mismatch_against_the_same_fixture(tmp_path):
    """The must-fire control for the test above."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    state, detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss-supertool"}
    )
    assert state == "mismatch"
    assert doctor.WATCH_CONFIG in detail


def test_watch_channel_reports_an_export_this_repo_never_declared(tmp_path):
    """The filed case (#150): nothing declared here, a name exported anyway, which
    is what a copied .claude/settings.local.json produces.

    The fixture gained an `.oss.json` when #191 split this state. That is not a
    weakening -- a name copied from ANOTHER repo is only identifiable as copied
    against this repo's own identity, and the case as filed is exactly a repo that
    has one and is not using it. Without the `.oss.json` the same fixture is the
    honestly-unknown arm, which is asserted separately below.
    """
    _oss_config_doc(tmp_path, {"repo": "Digital-Process-Tools/claude-oss"})
    _supertool_config(tmp_path, {"ops": {"radar": {}}})
    state, _detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss-supertool"}
    )
    assert state == "undeclared-export"


def test_watch_channel_export_with_no_supertool_config_at_all(tmp_path):
    _oss_config_doc(tmp_path, {"repo": "Digital-Process-Tools/claude-oss"})
    state, _detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss-supertool"}
    )
    assert state == "undeclared-export"


def test_watch_channel_default_is_not_the_same_state_as_an_unreadable_file(tmp_path):
    """Three states, not two: nothing declared and nothing exported is the shared
    default channel, and it must not render as the file that could not be read."""
    quiet = doctor.watch_channel_state(tmp_path, env={})[0]
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    broken = doctor.watch_channel_state(tmp_path, env={})[0]
    assert quiet == "default"
    assert broken == "unreadable"


def test_watch_channel_malformed_when_the_document_is_not_an_object(tmp_path):
    """A file that parsed is never reported as one that could not be read (#216).

    `[]` is valid JSON. The read succeeded, the parse succeeded, and the only
    thing wrong is the document's shape -- so `unreadable` here sends the reader
    to permissions, a lock or an encoding, none of which is true. The control is
    the arm below it, which is genuinely unparseable and must still say so."""
    (tmp_path / doctor.WATCH_CONFIG).write_text("[]", encoding="utf-8")
    parsed = doctor.watch_channel_state(tmp_path, env={})
    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    unparseable = doctor.watch_channel_state(tmp_path, env={})[0]
    assert parsed[0] == "malformed", parsed
    assert "not an object" in parsed[1]
    assert unparseable == "unreadable"


def test_watch_channel_malformed_when_ops_is_present_and_the_wrong_shape(tmp_path):
    """Three states, and the middle one is the whole point.

    A broken `ops` yields no names, which is what a repo declaring none also
    yields -- so folding those two renders an edited-and-broken file as `default`
    under a green line. But it read and parsed perfectly, so folding it the other
    way into `unreadable` names the wrong cause. Both controls are here: absent
    `ops` must stay `default`, and an unparseable file must stay `unreadable`."""
    (tmp_path / doctor.WATCH_CONFIG).write_text('{"ops": []}', encoding="utf-8")
    broken = doctor.watch_channel_state(tmp_path, env={})
    (tmp_path / doctor.WATCH_CONFIG).write_text('{"presets": ["git"]}', encoding="utf-8")
    absent = doctor.watch_channel_state(tmp_path, env={})[0]
    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    unparseable = doctor.watch_channel_state(tmp_path, env={})[0]
    assert broken[0] == "malformed", broken
    assert "`ops`" in broken[1] and "not an object" in broken[1]
    assert absent == "default"
    assert unparseable == "unreadable"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("[]", "malformed"),
        ('"oss"', "malformed"),
        ("3", "malformed"),
        ("null", "malformed"),
        ('{"ops": []}', "malformed"),
        ("{not json", "unreadable"),
        ("", "unreadable"),
    ],
)
def test_a_document_that_parsed_is_never_reported_as_unreadable(tmp_path, raw, expected):
    """Asserted against the INPUT SHAPE, not against `scaffold.check_radar`.

    #205's lesson: two checkers returning the same string would satisfy an
    agreement assertion just as happily when both are wrong, which is how the
    false comment at doctor.py:666 survived. So each shape is named here with the
    answer the shape itself earns, and both of doctor's readers of this file are
    held to it -- the divergence #216 tabulated was one reader of the two."""
    (tmp_path / doctor.WATCH_CONFIG).write_text(raw, encoding="utf-8")
    radar = doctor.radar_publish_state(tmp_path)
    channel = doctor.watch_channel_state(tmp_path, env={})
    assert radar[0] == expected, radar
    assert channel[0] == expected, channel


def test_check_watch_channel_sends_a_broken_shape_to_the_document_not_to_permissions(
    tmp_path, capsys
):
    """The harm #216 reports is a message, so the message is what is asserted.

    Without an arm of its own, `malformed` falls through to the `default` line --
    "none declared ... and nothing to derive one from" -- which is a remedy for a
    file that is fine. The control is the same fixture made genuinely unparseable,
    which must still say it could not be read."""
    (tmp_path / doctor.WATCH_CONFIG).write_text('{"ops": []}', encoding="utf-8")
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env={})
    shaped = list(doctor.FINDINGS)

    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env={})
    unread = list(doctor.FINDINGS)
    capsys.readouterr()

    assert [state for state, _ in shaped] == ["WARN"], shaped
    assert "not an object" in shaped[0][1], shaped
    assert "could not be read" not in shaped[0][1], shaped
    assert "none declared" not in shaped[0][1], shaped
    assert "could not be read" in unread[0][1], unread
    shaped[0][1].encode("ascii")


def test_watch_channel_conflict_still_names_a_path_override(tmp_path):
    """Two things can be wrong at once and they have different remedies. Reporting
    only the conflict drops the fact that the paths do not come from a name at all."""
    doc = {"ops": {"radar": {"watch_name": "oss"}, "gh-prs": {"watch_name": "other"}}}
    _supertool_config(tmp_path, doc)

    without = doctor.watch_channel_state(tmp_path, env={})
    with_override = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_SOCK": "/tmp/elsewhere"}
    )

    assert without[0] == "conflict"
    assert "SUPERTOOL_WATCH_SOCK" not in without[1]
    assert with_override[0] == "conflict"
    assert "SUPERTOOL_WATCH_SOCK" in with_override[1]


def test_watch_channel_declared_without_an_export_is_its_own_state(tmp_path):
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    assert doctor.watch_channel_state(tmp_path, env={})[0] == "declared-only"


def test_watch_channel_reports_op_blocks_that_disagree(tmp_path):
    _supertool_config(
        tmp_path,
        {"ops": {"radar": {"watch_name": "oss"}, "gh-prs": {"watch_name": "other"}}},
    )
    state, detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss"}
    )
    assert state == "conflict"
    assert "2" in detail


@pytest.mark.parametrize("var", ["SUPERTOOL_WATCH_SOCK", "SUPERTOOL_WATCH_STATE_DIR"])
def test_watch_channel_reports_a_path_override_over_an_agreeing_name(tmp_path, var):
    """An explicit socket or state directory overrides the name, so reporting
    `agree` here would be a green line about a comparison that decides nothing."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    state, detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss", var: "/tmp/elsewhere"}
    )
    assert state == "overridden"
    assert var in detail


def test_watch_channel_state_never_prints_a_value_the_repo_chose(tmp_path):
    """merge_permission_state's rule: counts and paths, never the file's text."""
    secret = "zzsentinelzz"
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": secret}}})
    for env in ({}, {"SUPERTOOL_WATCH_NAME": "other"}, {"SUPERTOOL_WATCH_NAME": secret}):
        _state, detail = doctor.watch_channel_state(tmp_path, env=env)
        assert secret not in detail


def test_watch_channel_state_reads_os_environ_when_no_env_is_passed(tmp_path, monkeypatch):
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    monkeypatch.setenv("SUPERTOOL_WATCH_NAME", "oss-supertool")
    monkeypatch.delenv("SUPERTOOL_WATCH_SOCK", raising=False)
    monkeypatch.delenv("SUPERTOOL_WATCH_STATE_DIR", raising=False)
    assert doctor.watch_channel_state(tmp_path)[0] == "mismatch"


def test_check_watch_channel_warns_on_a_mismatch_and_not_on_agreement(tmp_path, capsys):
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})

    doctor.check_watch_channel(tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss"})
    quiet = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    doctor.check_watch_channel(tmp_path, env={"SUPERTOOL_WATCH_NAME": "elsewhere"})
    loud = [state for state, _ in doctor.FINDINGS]

    assert quiet == ["OK"]
    assert loud == ["WARN"]
    assert capsys.readouterr().out.strip()


def test_check_watch_channel_prints_ascii_only(tmp_path):
    """Windows consoles encode with the codepage, not the source file's encoding,
    so a non-ASCII byte here kills the process at the print."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    for env in (
        {},
        {"SUPERTOOL_WATCH_NAME": "other"},
        {"SUPERTOOL_WATCH_NAME": "oss"},
        {"SUPERTOOL_WATCH_NAME": "oss", "SUPERTOOL_WATCH_SOCK": "/tmp/s.sock"},
    ):
        doctor.FINDINGS.clear()
        doctor.check_watch_channel(tmp_path, env=env)
        for _state, message in doctor.FINDINGS:
            message.encode("ascii")


def test_check_watch_channel_survives_an_unreadable_supertool_config(tmp_path):
    """The contract is exit 0 always: an OSError that is not absence must arrive
    as a WARN line, not as a traceback."""
    blocked = tmp_path / doctor.WATCH_CONFIG
    blocked.write_text("{}", encoding="utf-8")
    try:
        blocked.chmod(0o000)
        if os.access(str(blocked), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 file (root, or a filesystem without "
                "POSIX modes), so the unreadable arm cannot be reached here; the "
                "malformed-document arm above still covers the state"
            )
        state, _detail = doctor.watch_channel_state(tmp_path, env={})
    finally:
        blocked.chmod(0o644)
    assert state == "unreadable"


def test_main_reports_the_watch_channel(tmp_path, monkeypatch, capsys):
    _config(tmp_path)
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    monkeypatch.setenv("SUPERTOOL_WATCH_NAME", "oss-supertool")
    monkeypatch.delenv("SUPERTOOL_WATCH_SOCK", raising=False)
    monkeypatch.delenv("SUPERTOOL_WATCH_STATE_DIR", raising=False)
    # #621 self-review: a real `claude mcp get` call answers about this machine,
    # not this fixture.
    monkeypatch.setattr(doctor, "check_mcp_channel_registration", lambda **k: None)
    assert doctor.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert doctor.WATCH_NAME_ENV in out
    assert out.strip().splitlines()[-1].startswith("VERDICT:")


# --- #533: doctor compared two declarations and never asked whether the ------
# name they agreed on was one the consumer would actually accept. The control
# pair below is the reported ceiling exactly: a derived/declared name of 32
# characters is supertool's own cap and must still clear; one of 33 must WARN
# with the shared-default-socket wording; and a name doctor cannot classify
# (no registry, no install, no naming.py, an unreadable module) must be a
# third state that never renders as OK -- the absence this plugin is named
# after, reached here by the check that used to skip it.


def test_check_watch_channel_clears_a_32_character_name_the_consumer_accepts(
    tmp_path, monkeypatch, capsys
):
    """The must-not-fire arm: exactly at the reported cap, still OK."""
    name = "a" * 32
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": name}}})
    monkeypatch.setattr(
        doctor,
        "_consumer_watch_name_verdict",
        lambda got: ("accepted", "") if got == name else ("unknown", "wrong name"),
    )
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env={})
    capsys.readouterr()
    assert [state for state, _ in doctor.FINDINGS] == ["OK"]


def test_check_watch_channel_warns_a_33_character_name_the_consumer_discards(
    tmp_path, monkeypatch, capsys
):
    """The must-fire control for the test above: one character over the cap,
    and #533's own reported symptom -- this used to clear silently."""
    name = "a" * 33
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": name}}})
    monkeypatch.setattr(
        doctor,
        "_consumer_watch_name_verdict",
        lambda got: (
            ("rejected", "does not match ^[A-Za-z0-9][A-Za-z0-9._-]{0,31}\\Z")
            if got == name
            else ("unknown", "wrong name")
        ),
    )
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env={})
    capsys.readouterr()
    findings = list(doctor.FINDINGS)
    assert [state for state, _ in findings] == ["WARN"]
    assert "SHARED" in findings[0][1]
    assert "533" in findings[0][1]


def test_check_watch_channel_never_renders_ok_when_the_consumer_cannot_be_asked(
    tmp_path, monkeypatch, capsys
):
    """The third state: `unknown` must not be indistinguishable from `accepted`
    -- that silence is exactly what let a name over the cap clear here."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    monkeypatch.setattr(
        doctor,
        "_consumer_watch_name_verdict",
        lambda got: (
            "unknown",
            "~/.claude/plugins/installed_plugins.json could not be read (FileNotFoundError)",
        ),
    )
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env={})
    capsys.readouterr()
    findings = list(doctor.FINDINGS)
    assert [state for state, _ in findings] == ["WARN"]
    assert "OK" not in [state for state, _ in findings]


def test_consumer_watch_name_verdict_reads_the_installed_naming_rule(
    tmp_path, monkeypatch
):
    """Mirrors bin/oss-workspace's ASK_CONSUMER block (#231): same registry
    shape, same presets/watch/naming.py lookup, same NAME_RE match -- read
    from the version actually installed rather than a copy kept here to
    drift."""
    install_dir = tmp_path / "supertool-0.49.0"
    naming_dir = install_dir / "presets" / "watch"
    naming_dir.mkdir(parents=True)
    (naming_dir / "naming.py").write_text(
        "import re\n"
        "NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}\\Z')\n",
        encoding="utf-8",
    )
    registry = tmp_path / "installed_plugins.json"
    registry.write_text(
        json.dumps(
            {"plugins": {"supertool@marketplace": [{"installPath": str(install_dir)}]}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor.os.path,
        "expanduser",
        lambda p: str(registry) if p.endswith("installed_plugins.json") else p,
    )
    accepted = _REAL_CONSUMER_WATCH_NAME_VERDICT("a" * 32)
    rejected = _REAL_CONSUMER_WATCH_NAME_VERDICT("a" * 33)
    assert accepted == ("accepted", "")
    assert rejected[0] == "rejected"
    assert "naming.py" in rejected[1]


def test_consumer_watch_name_verdict_unknown_when_registry_is_absent(
    tmp_path, monkeypatch
):
    """No registry is `unknown`, never `accepted` -- silence here is #533."""
    monkeypatch.setattr(
        doctor.os.path,
        "expanduser",
        lambda p: str(tmp_path / "nope.json") if p.endswith("installed_plugins.json") else p,
    )
    verdict, why = _REAL_CONSUMER_WATCH_NAME_VERDICT("oss")
    assert verdict == "unknown"
    assert why


@pytest.mark.parametrize(
    "doc",
    [
        {"plugins": ["not", "a", "dict"]},
        {"plugins": {"supertool@marketplace": {"installPath": "/x"}}},
        {"plugins": {"supertool@marketplace": ["not-a-dict-entry"]}},
        ["not", "an", "object", "at", "all"],
    ],
)
def test_consumer_watch_name_verdict_survives_a_malformed_registry(
    tmp_path, monkeypatch, doc
):
    """Valid JSON in a shape this reader cannot use must answer `unknown`, not
    raise. Before this diff `check_watch_channel` never read this file at all,
    so an odd `installed_plugins.json` could not abort a doctor run -- the
    review round on #533 found exactly this: `.items()` on a list, `.get()` on
    a string, both AttributeError, both propagating out of every one of the
    four modified watch-channel states with no VERDICT line printed."""
    registry = tmp_path / "installed_plugins.json"
    registry.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(
        doctor.os.path,
        "expanduser",
        lambda p: str(registry) if p.endswith("installed_plugins.json") else p,
    )
    verdict, why = _REAL_CONSUMER_WATCH_NAME_VERDICT("oss")
    assert verdict == "unknown"
    assert why


# --- does anything publish to this repo's board? (#191) -----------------------
#
# The channel being open and the board being empty are different facts, and from
# every vantage point outside this file they render identically: `watches` shows
# a fleet, `channel:health` says FORWARDING, and nothing has ever been published.
# So every arm below asserts a DISTINCT state -- two arms both producing a WARN
# would reproduce the defect in the test.


def _oss_config_doc(root, doc):
    (root / doctor.OSS_CONFIG).write_text(json.dumps(doc), encoding="utf-8")


def test_radar_publish_reports_a_declared_board_with_a_route(tmp_path):
    """The must-not-fire arm. Its control is the test directly below, which uses
    the same fixture and removes only the tiers."""
    _supertool_config(
        tmp_path,
        {
            "presets": ["git", doctor.WATCH_PRESET],
            "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
        },
    )
    state, detail = doctor.radar_publish_state(tmp_path)
    assert state == "publishes", (state, detail)


def test_radar_publish_reports_no_tiers_against_the_same_fixture(tmp_path):
    """The must-fire control for the test above, and the state measured on this
    repository at the time #191 was filed: the tracked .supertool.json declares
    no ops at all, so nothing publishes while doctor printed OK."""
    _supertool_config(tmp_path, {"presets": ["git", doctor.WATCH_PRESET]})
    assert doctor.radar_publish_state(tmp_path)[0] == "no-tiers"


def test_radar_publish_no_config_file_is_its_own_state(tmp_path):
    assert doctor.radar_publish_state(tmp_path)[0] == "no-config"


def test_radar_publish_unreadable_is_not_the_same_as_declaring_none(tmp_path):
    """A file that could not be parsed yields no tiers, which is exactly what a
    file declaring none yields. Folding them sends a maintainer to add tiers to a
    file that already has some and cannot be read."""
    _supertool_config(tmp_path, {"presets": []})
    quiet = doctor.radar_publish_state(tmp_path)[0]
    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    broken = doctor.radar_publish_state(tmp_path)[0]
    assert quiet == "no-tiers"
    assert broken == "unreadable"


def test_radar_publish_an_empty_tier_object_declares_no_tier(tmp_path):
    _supertool_config(
        tmp_path,
        {"presets": [doctor.WATCH_PRESET], "ops": {"radar": {"radar_tiers": {}}}},
    )
    assert doctor.radar_publish_state(tmp_path)[0] == "no-tiers"


@pytest.mark.parametrize(
    "doc",
    [
        {"ops": []},
        {"ops": {"radar": "gh-prs"}},
        {"ops": {"radar": {"radar_tiers": ["gh-prs"]}}},
    ],
)
def test_radar_publish_malformed_is_not_the_same_as_declaring_none(tmp_path, doc):
    """Edited-and-broken has a different remedy from never-declared, and reporting
    the first as the second is a green-adjacent line about a file nobody can use."""
    _supertool_config(tmp_path, dict(doc, presets=[doctor.WATCH_PRESET]))
    assert doctor.radar_publish_state(tmp_path)[0] == "malformed"


def test_radar_publish_tiers_declared_with_no_route_to_the_op(tmp_path):
    """The other half measured in #191: tiers can be declared while the op that
    reads them is not loaded here at all, and each half is silent about the other."""
    _supertool_config(
        tmp_path,
        {
            "presets": ["git", "github"],
            "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
        },
    )
    assert doctor.radar_publish_state(tmp_path)[0] == "no-route"


@pytest.mark.parametrize("presets", [None, "watch", ["watch", 3]])
def test_radar_publish_route_unknown_when_presets_cannot_be_read(tmp_path, presets):
    """The third state for the route half. `presets` absent or the wrong shape is
    not evidence that the op is unrouted, and answering `no-route` there would
    send a maintainer to add a preset that may already be in effect."""
    doc = {"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}
    if presets is not None:
        doc["presets"] = presets
    _supertool_config(tmp_path, doc)
    assert doctor.radar_publish_state(tmp_path)[0] == "route-unknown"


def test_radar_publish_never_prints_a_value_the_repo_chose(tmp_path):
    """.supertool.json is contributor-writable in a managed repo, so a tier name
    reaching this output lets a tracked file write the diagnosis."""
    secret = "zzsentinelzz"
    _supertool_config(
        tmp_path,
        {
            "presets": [doctor.WATCH_PRESET, secret],
            "ops": {"radar": {"radar_tiers": {secret: {}}}},
        },
    )
    _state, detail = doctor.radar_publish_state(tmp_path)
    assert secret not in detail


def test_check_radar_publish_warns_on_an_empty_board_and_not_on_a_declared_one(
    tmp_path, capsys
):
    _supertool_config(
        tmp_path,
        {
            "presets": ["git", doctor.WATCH_PRESET],
            "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
        },
    )
    doctor.check_radar_publish(tmp_path)
    quiet = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    _supertool_config(tmp_path, {"presets": ["git", doctor.WATCH_PRESET]})
    doctor.check_radar_publish(tmp_path)
    loud = [state for state, _ in doctor.FINDINGS]

    assert quiet == ["OK"]
    assert loud == ["WARN"]
    assert capsys.readouterr().out.strip()


def test_check_radar_publish_prints_ascii_only_in_every_state(tmp_path):
    """Windows consoles encode with the codepage, not the source file's encoding,
    so a non-ASCII byte here kills the process at the print -- after the work that
    print was reporting already happened."""
    docs = [
        None,
        {"presets": ["git"]},
        {"presets": ["git"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
        {"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
        {"presets": [doctor.WATCH_PRESET], "ops": []},
        {
            "presets": [doctor.WATCH_PRESET],
            "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
        },
    ]
    seen = set()
    for doc in docs:
        doctor.FINDINGS.clear()
        target = tmp_path / doctor.WATCH_CONFIG
        if doc is None:
            if target.exists():
                target.unlink()
        else:
            _supertool_config(tmp_path, doc)
        seen.add(doctor.radar_publish_state(tmp_path)[0])
        doctor.check_radar_publish(tmp_path)
        for _state, message in doctor.FINDINGS:
            message.encode("ascii")
    # The loop is only worth its runtime if it actually walked the states. Six of
    # the seven; `unreadable` needs a permission fixture and has its own test.
    assert len(seen) == 6, sorted(seen)


def test_check_radar_publish_survives_an_unreadable_supertool_config(tmp_path):
    """exit 0 always: an OSError that is not absence arrives as a WARN, never as
    a traceback. The deny is attempted rather than assumed."""
    blocked = tmp_path / doctor.WATCH_CONFIG
    blocked.write_text("{}", encoding="utf-8")
    try:
        blocked.chmod(0o000)
        if os.access(str(blocked), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 file (root, or a filesystem without "
                "POSIX modes), so the unreadable arm cannot be reached here; the "
                "malformed-document arm above still covers a file that parses to "
                "nothing usable"
            )
        state, _detail = doctor.radar_publish_state(tmp_path)
    finally:
        blocked.chmod(0o644)
    assert state == "unreadable"


def test_the_preset_that_provides_radar_is_measured_against_supertool(tmp_path):
    """WATCH_PRESET is a transcription of a fact in a declared dependency, so it is
    measured against that dependency rather than asserted in a comment.

    A project enabling no presets is asked for `radar`; supertool names the preset
    that provides it in the refusal. If supertool is not installed, or its refusal
    names no preset at all, that is reported as untested rather than as a pass --
    an assertion that could not look must not render as one that looked.
    """
    if shutil.which("supertool") is None:
        pytest.skip(
            "supertool is not on PATH, so the preset name behind doctor.WATCH_PRESET "
            "went unmeasured here; it remains a transcription only"
        )
    _supertool_config(tmp_path, {"presets": []})
    probe = spawn_guard.run(
        ["supertool", "radar:--state"],
        subject="which preset supertool names for an unrouted 'radar', the transcription "
        "doctor.WATCH_PRESET is measured against",
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    blob = (probe.stdout or "") + (probe.stderr or "")
    if "preset" not in blob:
        pytest.skip(
            "supertool's answer for an unrouted 'radar' names no preset here, so the "
            "constant went unmeasured: " + " ".join(blob.split())[:200]
        )
    assert "'{}'".format(doctor.WATCH_PRESET) in blob, blob


# --- the shared default socket is a finding, not a shrug (#191) ---------------


def test_watch_channel_derives_a_name_when_oss_json_carries_a_repo(tmp_path):
    """bin/oss-workspace derives the channel name from .oss.json's repo when
    nothing declares or exports one, so `default` stopped meaning "the shared
    socket" the moment that landed. The control is the test below: the same
    fixture with the repo removed."""
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    state, detail = doctor.watch_channel_state(tmp_path, env={})
    assert state == "derived", (state, detail)


def test_watch_channel_is_the_shared_default_when_nothing_can_be_derived(tmp_path):
    """The must-fire control for the test above."""
    _oss_config_doc(tmp_path, {"default_branch": "main"})
    state, detail = doctor.watch_channel_state(tmp_path, env={})
    assert state == "default"
    assert doctor.OSS_CONFIG in detail


def test_watch_channel_default_names_which_of_three_reasons_it_was(tmp_path):
    """One state, three remedies. The reason travels in the detail rather than
    being dropped for arriving second."""
    absent = doctor.watch_channel_state(tmp_path, env={})[1]
    _oss_config_doc(tmp_path, {"repo": "   "})
    empty = doctor.watch_channel_state(tmp_path, env={})[1]
    (tmp_path / doctor.OSS_CONFIG).write_text("{not json", encoding="utf-8")
    broken = doctor.watch_channel_state(tmp_path, env={})[1]
    assert len({absent, empty, broken}) == 3, (absent, empty, broken)


def test_watch_channel_a_declaration_still_wins_over_the_derivation(tmp_path):
    """Precedence, mirroring bin/oss-workspace: export, then declaration, then
    derivation. A derivable repo must not turn a declaration into `derived`.

    The declared name here has to be the one this repo's own .oss.json derives
    to (#655 gave the declared-alone branch a comparison it used to skip), or
    this test would be asserting `declared-mismatch`, which is a real state but
    not the one this test is about."""
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "owner-name"}}})
    assert doctor.watch_channel_state(tmp_path, env={})[0] == "declared-only"
    assert (
        doctor.watch_channel_state(
            tmp_path, env={"SUPERTOOL_WATCH_NAME": "owner-name"}
        )[0]
        == "agree"
    )


def test_watch_channel_declared_alone_is_checked_against_this_repos_own_derivation(
    tmp_path,
):
    """#655: `declared-only` used to clear a name declared alone with no
    comparison against what this repo's own .oss.json derives -- so a
    .supertool.json copied from another repo cleared byte-identical to a
    correct declaration. This is the reproduction from the issue body: a
    declared name that is not this repo's own must not read as `declared-only`.

    The must-not-fire arm is the test above, which shares this fixture's repo
    and changes only the declared name to the one that agrees."""
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    _supertool_config(
        tmp_path, {"ops": {"radar": {"watch_name": "some-other-org-other-repo"}}}
    )
    assert doctor.watch_channel_state(tmp_path, env={})[0] == "declared-mismatch"


def test_check_watch_channel_warns_on_a_declared_name_this_repo_did_not_derive(
    tmp_path, capsys
):
    """The verdict, not just the state: `declared-mismatch` must print WARN, and
    the clean case beside it must stay OK -- same fixture, only the declared
    name differs, so a check that stopped firing cannot be told from a check
    that never ran."""
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "owner-name"}}})
    doctor.check_watch_channel(tmp_path, env={})
    quiet = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    _supertool_config(
        tmp_path, {"ops": {"radar": {"watch_name": "some-other-org-other-repo"}}}
    )
    doctor.check_watch_channel(tmp_path, env={})
    loud = [(state, message) for state, message in doctor.FINDINGS]

    assert quiet == ["OK"]
    assert [state for state, _ in loud] == ["WARN"]
    assert "655" in loud[0][1]


def test_watch_channel_state_never_prints_the_repo_it_derived_from(tmp_path):
    _oss_config_doc(tmp_path, {"repo": "zzsentinelzz/zzrepozz"})
    _state, detail = doctor.watch_channel_state(tmp_path, env={})
    assert "zzsentinelzz" not in detail


def test_check_watch_channel_warns_on_the_shared_socket_and_not_on_a_derivation(
    tmp_path, capsys
):
    """The verdict, not the state, is what #191 reports: `default` printed OK and
    the words "Nothing is broken" on a tree where every event this repo emitted
    was discarded."""
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    doctor.check_watch_channel(tmp_path, env={})
    quiet = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    (tmp_path / doctor.OSS_CONFIG).unlink()
    doctor.check_watch_channel(tmp_path, env={})
    loud = [(state, message) for state, message in doctor.FINDINGS]

    assert quiet == ["OK"]
    assert [state for state, _ in loud] == ["WARN"]
    assert "Nothing is broken" not in loud[0][1]
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("doc", [{"repo": "owner/name"}, {"default_branch": "main"}])
def test_check_watch_channel_says_the_holder_question_is_not_checked(tmp_path, doc):
    """Which server holds the socket is the half that decides delivery, and it is
    the half nothing here can see -- `channel:health` says so of itself, in its own
    output. The decision to decline it is printed rather than left in a comment."""
    _oss_config_doc(tmp_path, doc)
    doctor.check_watch_channel(tmp_path, env={})
    message = doctor.FINDINGS[0][1]
    assert "not established" in message.lower(), message
    assert "channel:health" in message, message


def test_check_watch_channel_prints_ascii_only_in_the_derived_and_default_states(
    tmp_path,
):
    for doc in ({"repo": "owner/name"}, {"default_branch": "main"}, None):
        doctor.FINDINGS.clear()
        target = tmp_path / doctor.OSS_CONFIG
        if doc is None:
            if target.exists():
                target.unlink()
        else:
            _oss_config_doc(tmp_path, doc)
        doctor.check_watch_channel(tmp_path, env={})
        for _state, message in doctor.FINDINGS:
            message.encode("ascii")


def test_the_refused_state_prints_ascii_even_for_a_non_ascii_repo(tmp_path):
    """`refused` (#207) is the first watch-channel message to embed the config's
    own value, so the guard above stopped covering the states that can print one.

    The encodability half is not the interesting one and is not what was broken:
    `report()` funnels everything through `_one_line`, which already replaces
    anything outside printable ASCII with `?`, so doctor's `exit 0 always, one
    VERDICT line` contract was never at risk here. It is asserted anyway, because
    it is the property that must not regress if that funnel is ever bypassed.

    The half that WAS broken is the second one. `_one_line` reduces a CJK repo to
    `repo-??`, so the receipt reported that a value is invalid while making that
    value unidentifiable -- and the remedy is to correct that exact value. Escaping
    before the funnel keeps the receipt able to name what it is complaining about.
    """
    _oss_config_doc(tmp_path, {"repo": "repo-中文"})
    doctor.check_watch_channel(tmp_path, env={})
    message = doctor.FINDINGS[0][1]
    message.encode("ascii")
    assert "repo-" in message, message
    assert "u4e2d" in message, message


def test_oss_json_that_parsed_is_not_reported_as_one_that_could_not_be_read(tmp_path):
    """#216's class, on the OTHER config file this module reads.

    `_derivable_watch_name` folded a parsed-but-wrong-shape `.oss.json` into
    `unreadable` exactly as `_supertool_document` did, and the sentence reaches the
    reader through the same `watch channel` line. Both controls are in the fixture:
    a genuinely unparseable file must stay `unreadable`, and an absent one must stay
    `no-config` -- the state that would otherwise absorb this one silently."""
    target = tmp_path / doctor.OSS_CONFIG
    target.write_text("[]", encoding="utf-8")
    parsed = doctor._derivable_watch_name(tmp_path)
    target.write_text("{not json", encoding="utf-8")
    unparseable = doctor._derivable_watch_name(tmp_path)[0]
    target.unlink()
    absent = doctor._derivable_watch_name(tmp_path)[0]
    assert parsed[0] == "malformed", parsed
    assert parsed[1] == "" and parsed[2] == "", parsed
    assert unparseable == "unreadable"
    assert absent == "no-config"


@pytest.mark.parametrize("env", [{}, {"SUPERTOOL_WATCH_NAME": "oss-supertool"}])
def test_check_watch_channel_sends_a_broken_oss_json_to_the_document(tmp_path, env):
    """The harm is the printed sentence, in both states that render this reason.

    With no export the line is `default`; with one it is
    `undeclared-export-unknown`. Each carries its own reason dictionary, so a key
    added to one and not the other would raise a KeyError here rather than print
    the wrong remedy -- and before the fix both printed "could not be read" for a
    file that was read. The control is the same fixture made unparseable."""
    (tmp_path / doctor.OSS_CONFIG).write_text("[]", encoding="utf-8")
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env=env)
    shaped = doctor.FINDINGS[0][1]

    (tmp_path / doctor.OSS_CONFIG).write_text("{not json", encoding="utf-8")
    doctor.FINDINGS.clear()
    doctor.check_watch_channel(tmp_path, env=env)
    unread = doctor.FINDINGS[0][1]

    assert "not an object" in shaped, shaped
    assert "could not be read" not in shaped, shaped
    assert "could not be read" in unread, unread
    shaped.encode("ascii")


def test_doctor_and_the_launcher_agree_on_what_is_derivable(tmp_path):
    """Two copies of one rule, cross-checked rather than restated.

    `bin/oss-workspace` decides derivability in an embedded heredoc; doctor decides
    it in `_derivable_watch_name`. This runs the launcher's own program against the
    same fixtures and asserts it prints a name exactly when doctor says it can --
    a second measurement, not a second assertion. If the heredoc cannot be located
    the guard fails loudly, because a copy that went unchecked must not render as
    a copy that agreed.
    """
    launcher = (REPO_ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")
    marker = "DERIVE_NAME"
    opening = "<<'" + marker + "'"
    closing = "\n" + marker + "\n"
    tail = launcher.split(opening, 1)[1] if opening in launcher else ""
    if "\n" not in tail or closing not in tail:
        pytest.fail(
            "bin/oss-workspace no longer carries a {} heredoc, so doctor's copy of "
            "the derivation rule went unchecked".format(marker)
        )
    # The rest of the opening line belongs to the shell, not to the heredoc.
    program = tail.split("\n", 1)[1].split(closing, 1)[0]
    script = tmp_path / "derive.py"
    script.write_text(program, encoding="utf-8")

    target = tmp_path / doctor.OSS_CONFIG
    cases = [
        ({"repo": "owner/name"}, "yes"),
        ({"repo": "   "}, "no-repo"),
        ({"default_branch": "main"}, "no-repo"),
        ("{not json", "unreadable"),
        (None, "no-config"),
        # #207: a repo the validator refuses is a fifth answer, and it must not
        # arrive as `no-repo` -- the remedy is to correct a value, not add a key.
        ({"repo": ".."}, "refused"),
        ({"repo": "../../etc"}, "refused"),
        # #216's class, one config file over: `[]` reads and parses, so reporting
        # it as `unreadable` sends the reader to permissions rather than to the
        # document. The launcher half of this cross-check needs no change -- it
        # was already required to print no name here, and still must.
        ("[]", "malformed"),
        ('"owner/name"', "malformed"),
    ]
    for doc, expected in cases:
        if doc is None:
            if target.exists():
                target.unlink()
        elif isinstance(doc, str):
            target.write_text(doc, encoding="utf-8")
        else:
            _oss_config_doc(tmp_path, doc)
        assert doctor._derivable_watch_name(tmp_path)[0] == expected, (doc, expected)
        run = spawn_guard.run(
            [sys.executable, str(script), str(target), str(REPO_ROOT / "scripts")],
            subject="whether the launcher derives a watch name for this config, which is "
            "the half of the agreement doctor cannot answer for itself",
            capture_output=True,
            text=True,
            timeout=120,
        )
        printed = bool(run.stdout.strip())
        assert printed == (expected == "yes"), (doc, run.stdout, run.stderr)


def test_main_reports_whether_anything_publishes_to_the_board(tmp_path, monkeypatch):
    _config(tmp_path)
    _supertool_config(tmp_path, {"presets": ["git"]})
    monkeypatch.delenv("SUPERTOOL_WATCH_NAME", raising=False)
    monkeypatch.delenv("SUPERTOOL_WATCH_SOCK", raising=False)
    monkeypatch.delenv("SUPERTOOL_WATCH_STATE_DIR", raising=False)
    # #621 self-review: a real `claude mcp get` call answers about this machine,
    # not this fixture.
    monkeypatch.setattr(doctor, "check_mcp_channel_registration", lambda **k: None)
    assert doctor.main(["--root", str(tmp_path)]) == 0
    assert [m for _s, m in doctor.FINDINGS if m.startswith("radar board:")]


def test_the_supertool_config_this_plugin_writes_satisfies_its_own_diagnostic(tmp_path):
    """The plugin's own default, judged by the plugin's own check (#191).

    `scaffold.SUPERTOOL_JSON` is written into a repo that has none, and its comment
    says radar is on by default so "a managed repo should have a board the first
    time someone opens it". Registering tiers is only half of that: the op reading
    them is provided by a preset, and a template registering a board with no route
    to it hands every scaffolded repo the exact state #191 reports -- a channel
    that renders as healthy and publishes nothing.

    A second measurement rather than a second assertion: this reads the template
    through the diagnostic instead of restating what the template ought to say, so
    the two cannot agree with each other while both being wrong.
    """
    (tmp_path / doctor.WATCH_CONFIG).write_text(scaffold.SUPERTOOL_JSON, encoding="utf-8")
    state, detail = doctor.radar_publish_state(tmp_path)
    assert state == "publishes", (state, detail)

# --- an export that the repo itself derives is not a copied one (#191) --------
#
# The composition defect this branch sits on. `bin/oss-workspace` now derives
# SUPERTOOL_WATCH_NAME from .oss.json's repo, so an export with no declaration
# beside it became the ORDINARY state of every managed repo -- and that is exactly
# the shape `undeclared-export` was written to accuse of a hand-copied
# settings.local.json. Neither #192's diff nor this one shows the seam; it exists
# only in their composition. The original case is real and must keep firing, so
# the state is split rather than deleted.


def test_watch_channel_an_export_this_repo_derives_is_not_the_copied_case(tmp_path):
    """The must-not-fire arm. Its control is the test directly below, which uses
    the same fixture and changes only the exported value."""
    _oss_config_doc(tmp_path, {"repo": "Digital-Process-Tools/claude-oss"})
    state, _detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "Digital-Process-Tools-claude-oss"}
    )
    assert state == "derived-export", state


def test_watch_channel_an_export_that_differs_from_the_derivation_still_fires(tmp_path):
    """The must-fire control. The filed case is a name copied from another repo,
    and splitting the state must not stop it being reported."""
    _oss_config_doc(tmp_path, {"repo": "Digital-Process-Tools/claude-oss"})
    state, _detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss-supertool"}
    )
    assert state == "undeclared-export", state


@pytest.mark.parametrize(
    "doc", [None, "{not json", {"default_branch": "main"}, {"repo": "   "}]
)
def test_watch_channel_cannot_compare_an_export_with_nothing_to_derive_from(
    tmp_path, doc
):
    """The third answer, and it is the whole point of the split. With no repo to
    derive from, `derived` and `hand-copied` are indistinguishable -- so it is
    answered as neither rather than falling silently to the accusation."""
    target = tmp_path / doctor.OSS_CONFIG
    if doc is None:
        if target.exists():
            target.unlink()
    elif isinstance(doc, str):
        target.write_text(doc, encoding="utf-8")
    else:
        _oss_config_doc(tmp_path, doc)
    state, _detail = doctor.watch_channel_state(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss-supertool"}
    )
    assert state == "undeclared-export-unknown", state


def test_watch_channel_a_declaration_still_decides_against_an_export(tmp_path):
    """The derivation is consulted only where the launcher consults it: after a
    declaration and an export have both failed to answer. A derivable repo must
    not turn `agree` or `mismatch` into anything else."""
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    assert (
        doctor.watch_channel_state(tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss"})[0]
        == "agree"
    )
    assert (
        doctor.watch_channel_state(tmp_path, env={"SUPERTOOL_WATCH_NAME": "other"})[0]
        == "mismatch"
    )


def test_watch_channel_derived_export_detail_prints_no_name(tmp_path):
    """No-leak, and the split that produced the two details being asserted.

    The state assertions are not decoration. Without them this test is green
    against the code BEFORE the split, whose detail for both exports was the
    literal string `SUPERTOOL_WATCH_NAME` -- which contains neither sentinel, so
    a no-leak assertion alone passes on a version that never made the comparison.
    A test whose name claims to cover a feature has to fail when the feature is
    gone.
    """
    _oss_config_doc(tmp_path, {"repo": "zzsentinelzz/zzrepozz"})
    seen = []
    for exported in ("zzsentinelzz-zzrepozz", "zzotherzz"):
        state, detail = doctor.watch_channel_state(
            tmp_path, env={"SUPERTOOL_WATCH_NAME": exported}
        )
        seen.append(state)
        assert "zzsentinelzz" not in detail, detail
        assert "zzotherzz" not in detail, detail
    assert seen == ["derived-export", "undeclared-export"], seen


def test_check_watch_channel_does_not_accuse_an_export_the_repo_derives(
    tmp_path, capsys
):
    """The verdict is the deliverable. The old line accused the maintainer of a
    copied settings file and named a remedy that would be wrong to follow."""
    _oss_config_doc(tmp_path, {"repo": "Digital-Process-Tools/claude-oss"})

    doctor.check_watch_channel(
        tmp_path, env={"SUPERTOOL_WATCH_NAME": "Digital-Process-Tools-claude-oss"}
    )
    quiet = list(doctor.FINDINGS)
    doctor.FINDINGS.clear()

    doctor.check_watch_channel(tmp_path, env={"SUPERTOOL_WATCH_NAME": "oss-supertool"})
    loud = list(doctor.FINDINGS)

    assert [state for state, _ in quiet] == ["OK"]
    assert [state for state, _ in loud] == ["WARN"]
    # The accusation must be absent from the derived arm and present in the control,
    # or "the warning went away" cannot be told from "doctor stopped printing".
    assert "hand-copied" not in quiet[0][1], quiet[0][1]
    assert "hand-copied" in loud[0][1], loud[0][1]
    assert capsys.readouterr().out.strip()


def test_check_watch_channel_prints_ascii_only_in_the_export_states(tmp_path):
    _oss_config_doc(tmp_path, {"repo": "owner/name"})
    envs = [
        {"SUPERTOOL_WATCH_NAME": "owner-name"},
        {"SUPERTOOL_WATCH_NAME": "elsewhere"},
    ]
    seen = set()
    for env in envs:
        doctor.FINDINGS.clear()
        seen.add(doctor.watch_channel_state(tmp_path, env=env)[0])
        doctor.check_watch_channel(tmp_path, env=env)
        for _state, message in doctor.FINDINGS:
            message.encode("ascii")
    (tmp_path / doctor.OSS_CONFIG).unlink()
    doctor.FINDINGS.clear()
    seen.add(doctor.watch_channel_state(tmp_path, env=envs[0])[0])
    doctor.check_watch_channel(tmp_path, env=envs[0])
    for _state, message in doctor.FINDINGS:
        message.encode("ascii")
    assert seen == {"derived-export", "undeclared-export", "undeclared-export-unknown"}


def test_doctor_derives_the_same_name_as_the_launcher_does(tmp_path):
    """The drift guard, at the level that matters now: the VALUE, not just whether
    one exists.

    Since #207 there is only one spelling of the rule -- `oss_config` holds it and
    both doctor and the launcher read it -- so this no longer guards two copies of
    a regex. It guards the launcher's own PROGRAM: that its argv wiring reaches
    the validator at all, that the value it prints is the validator's, and that it
    prints NOTHING for the values the validator refuses. Everything between
    `.oss.json` on disk and stdout is still only measurable by running it.

    So the table below is deliberately split, and both halves are asserted: a
    launcher that had lost its import would print nothing for every row and pass
    any assertion phrased only as "refused rows are silent". If the heredoc cannot
    be located the guard fails loudly -- a copy that went unchecked must not render
    as a copy that agreed.
    """
    launcher = (REPO_ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")
    marker = "DERIVE_NAME"
    opening = "<<'" + marker + "'"
    closing = "\n" + marker + "\n"
    tail = launcher.split(opening, 1)[1] if opening in launcher else ""
    if "\n" not in tail or closing not in tail:
        pytest.fail(
            "bin/oss-workspace no longer carries a {} heredoc, so doctor's copy of "
            "the derivation went unchecked".format(marker)
        )
    script = tmp_path / "derive.py"
    script.write_text(tail.split("\n", 1)[1].split(closing, 1)[0], encoding="utf-8")

    target = tmp_path / doctor.OSS_CONFIG
    repos = [
        "Digital-Process-Tools/claude-oss",
        "owner/name",
        "  owner/name  ",
        "Owner/Name.With.Dots",
        "owner/name_with_underscore",
        "owner/name with spaces",
        "owner/name:colon",
        "owner//name",
        "owner/naïve",
        "owner/repo-中文",
        "...",
        "/",
    ]
    accepted = 0
    refused = 0
    # Since #270 the block takes a third argument: the one sentence saying where the
    # session actually landed, computed once by the shell and handed to every arm. It
    # used to be spelled out inside each heredoc, which is why one arm got fixed and
    # eight did not. This caller has no session, so it passes a sentinel and asserts
    # the sentinel comes back -- restating the real sentence here would put a second
    # spelling of it in the repository, which is the defect being closed.
    #
    # What the sentence SAYS, in both directions and per arm, is measured in
    # tests/test_workspace_launcher.py against the launcher actually running.
    landing = "LANDING-SENTENCE-FROM-THE-CALLER."
    for repo in repos:
        _oss_config_doc(tmp_path, {"repo": repo})
        run = spawn_guard.run(
            [sys.executable, str(script), str(target),
             str(REPO_ROOT / "scripts"), landing],
            subject="the name the launcher derives for this repo, compared against "
            "oss_config.watch_channel_name",
            capture_output=True,
            text=True,
            timeout=120,
        )
        name, problem = oss_config.watch_channel_name(repo)
        assert run.stdout.strip("\n") == ("" if problem else name), (
            repo,
            run.stdout,
            run.stderr,
        )
        if problem:
            refused += 1
            # A refusal that says nothing is the shared default socket reached in
            # silence, which is the state this whole check exists to report.
            assert landing in run.stderr, (repo, run.stderr)
        else:
            accepted += 1
    # Both halves of the table were exercised. Without this the guard passes
    # against a launcher that refuses everything and against one that refuses
    # nothing, which are the two ways #207 can be got wrong.
    assert accepted >= 3 and refused >= 3, (accepted, refused)


# --- the remedies these checks print, measured rather than asserted -----------


def test_the_radar_remedy_this_check_prints_actually_satisfies_the_check(tmp_path):
    """A remedy is a claim about what would fix the thing. Reading it back through
    the check is the only way to find out that it does -- an assertion about the
    remedy's text would pass just as happily on a remedy that fixes nothing."""
    (tmp_path / doctor.WATCH_CONFIG).write_text(
        json.dumps(doctor.RADAR_REMEDY_CONFIG), encoding="utf-8"
    )
    state, detail = doctor.radar_publish_state(tmp_path)
    assert state == "publishes", (state, detail)


def test_the_radar_remedy_names_both_halves_and_says_not_to_replace_presets(tmp_path):
    """A repo scaffolded before the preset fix already HAS a `presets` list, so a
    remedy pasted over it would drop `git` and `github`. The line has to say which
    of the two operations it means."""
    assert doctor.WATCH_PRESET in doctor.RADAR_REMEDY
    assert doctor.RADAR_TIERS_KEY in doctor.RADAR_REMEDY
    assert "rather than replacing" in doctor.RADAR_REMEDY, doctor.RADAR_REMEDY


def test_a_repo_scaffolded_today_passes_the_radar_check(tmp_path):
    """End to end rather than through the template constant: run the scaffolder and
    ask the diagnostic about what actually landed on disk."""
    config = _config(tmp_path)
    scaffold.apply(tmp_path, config, plugin_root=REPO_ROOT)
    doctor.check_radar_publish(tmp_path)
    assert [state for state, _ in doctor.FINDINGS] == ["OK"], doctor.FINDINGS


def test_a_repo_scaffolded_before_the_preset_fix_warns_and_its_remedy_works(tmp_path):
    """The reverse direction, and the one a maintainer actually meets: an existing
    repo carrying the old template. It must warn, and following the warning must
    reach `publishes` -- measured by applying the remedy, not by reading it."""
    stale = {
        "presets": ["git", "github"],
        "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
    }
    (tmp_path / doctor.WATCH_CONFIG).write_text(json.dumps(stale), encoding="utf-8")
    assert doctor.radar_publish_state(tmp_path)[0] == "no-route"
    doctor.check_radar_publish(tmp_path)
    assert [state for state, _ in doctor.FINDINGS] == ["WARN"], doctor.FINDINGS

    # The remedy, as the line states it: add the preset to the list that is there
    # rather than replacing it.
    stale["presets"].append(doctor.WATCH_PRESET)
    (tmp_path / doctor.WATCH_CONFIG).write_text(json.dumps(stale), encoding="utf-8")
    assert doctor.radar_publish_state(tmp_path)[0] == "publishes"


# --- #644: doctor's own no-tiers / no-route WARNs still printed a fragment a
# maintainer has to merge by hand, while #622 gave scaffold's sibling checks the
# whole corrected document. route-unknown must NOT get this treatment -- a merge
# cannot safely decide what to append an unreadable value to.


def test_no_tiers_warn_carries_the_whole_corrected_document_not_a_fragment(tmp_path):
    """#644: the model is #622's scaffold.check_radar. A maintainer who pastes the
    remedy fragment over an existing key can produce a board that looks configured
    from outside and still publishes nothing -- the whole document sidesteps that
    by construction."""
    _supertool_config(tmp_path, {"presets": ["git", "github"]})
    doctor.check_radar_publish(tmp_path)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "The whole file, corrected:" in message
    merged = json.loads(message.split("The whole file, corrected: ", 1)[1])
    assert doctor.WATCH_PRESET in merged["presets"]
    assert merged["ops"]["radar"]["radar_tiers"]


def test_no_route_warn_carries_the_whole_corrected_document_too(tmp_path):
    stale = {
        "presets": ["git", "github"],
        "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}},
    }
    _supertool_config(tmp_path, stale)
    doctor.check_radar_publish(tmp_path)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "The whole file, corrected:" in message
    merged = json.loads(message.split("The whole file, corrected: ", 1)[1])
    assert doctor.WATCH_PRESET in merged["presets"]
    assert merged["ops"]["radar"]["radar_tiers"] == {"gh-prs": {}}


def test_route_unknown_warn_still_prints_only_a_fragment(tmp_path):
    """Must-not-fire control for the two tests above: `route-unknown` means
    `presets` could not be read at all, and a merge cannot safely decide what to
    append an unreadable value to -- #622's own distinction, preserved here."""
    _supertool_config(
        tmp_path,
        {"presets": "watch", "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
    )
    doctor.check_radar_publish(tmp_path)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "The whole file, corrected:" not in message


def test_no_tiers_merged_document_declines_on_a_malformed_presets_shape(tmp_path):
    """`_radar_merged_document` must return None -- print nothing rather than
    something wrong -- when `presets` is present but not a list of strings, even
    though the state here is still `no-tiers` (presets absent is fine; a
    malformed non-list `presets` is the case this guards)."""
    _supertool_config(tmp_path, {"presets": ["git", 3]})
    doctor.check_radar_publish(tmp_path)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "The whole file, corrected:" not in message


@pytest.mark.parametrize(
    "doc",
    [
        {},
        {"presets": ["git", "github"]},
        {"presets": ["git", "github"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
        {"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
        {"presets": [doctor.WATCH_PRESET]},
        {"presets": ["git", 3]},
        {"ops": []},
        {"presets": ["git"], "ops": {"radar": "gh-prs"}},
        {"presets": ["git"], "ops": {"radar": {"radar_tiers": ["gh-prs"]}}},
    ],
)
def test_doctor_and_scaffold_merged_documents_agree(doc):
    """#644's own guard against the two copies drifting apart: not a string
    comparison of the two functions' bodies (their docstrings legitimately cite
    different issue numbers), but a behavioural one over the same fixtures --
    the two copies exist because `doctor` imports `scaffold` only optionally, so
    the check that keeps them honest has to run both and compare what they
    produce, the same way #622's own two remedy strings are held together."""
    assert doctor._radar_merged_document(doc) == scaffold._radar_merged_document(doc)


# --- #260: the fragments README is a default, and scaffold cannot deliver a section
# added to its template after a repo was already scaffolded (#259). This check reports
# rather than fixes, because a default is never replaced once it exists.


def _fragments_readme(root, changelog_dir, body):
    directory = root / changelog_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "README.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_fragments_readme_ok_when_it_documents_the_compatibility_bullet(tmp_path):
    _fragments_readme(
        tmp_path, "changelog.d",
        "# Fragments\n\n- Compatibility: breaking|compatible - <reason>\n",
    )
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "changelog.d"})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "changelog.d" in message


def test_fragments_readme_warns_and_names_that_scaffold_will_not_fix_it(tmp_path):
    """The remedy must not name a command that declines to act -- naming one that does
    nothing reads as a fix and performs nothing, which is the `misdirects` row."""
    _fragments_readme(tmp_path, "changelog.d", "# Fragments\n\nNo compatibility section here.\n")
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "changelog.d"})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "/oss:scaffold will not fix it" in message
    assert "--show" in message


def test_fragments_readme_absent_is_the_ordinary_state_not_a_pass_or_a_finding(tmp_path):
    """Most repos have no fragment practice at all. That must not render as a
    finding (WARN/FAIL) -- it would warn on nearly every scaffolded repo -- and the
    wording must not read as a verified pass either."""
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "changelog.d"})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "not a finding" in message
    assert "absent" in message


def test_fragments_readme_resolves_changelog_dir_from_config_not_a_hardcoded_name(tmp_path):
    """#259's second defect on this same line: a hardcoded directory name. A custom
    `changelog_dir` must be the directory actually checked."""
    # Built with Path, not a "notes/fragments" string literal: the point of this
    # assertion is that the check followed the CONFIGURED directory rather than
    # the hardcoded changelog.d/ default, and a POSIX-literal substring stops
    # proving that on Windows -- the message is rendered with str(Path), which is
    # backslash-joined there, so "notes/fragments" never matches a passing run
    # (#260 review). Comparing the resolved Path's own str() asserts the same
    # fact on every platform: the message names THIS directory, joined the way
    # this platform joins it.
    expected_dir = tmp_path / "notes" / "fragments"
    _fragments_readme(tmp_path, "notes/fragments", "- Compatibility: breaking|compatible - <reason>\n")
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "notes/fragments"})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert str(expected_dir) in message

    # Must-fire control: the default directory name must NOT be consulted when a
    # non-default one is configured, or this would pass by accident on the default.
    doctor.FINDINGS.clear()
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "changelog.d"})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "absent" in message
    assert str(expected_dir) not in message


def test_fragments_readme_warn_remedy_is_a_command_scaffold_show_accepts(tmp_path):
    """#438: `doctor.sh` and `CLAUDE_PROJECT_DIR` hand this an ABSOLUTE `project_dir`
    (`tmp_path` already is one), so `directory / "README.md"` is absolute too --
    `scaffold.show` matches by string equality against repo-relative template keys,
    so quoting the absolute form in the remedy names a command that fails on the
    ordinary invocation and only works under `--root .`.

    Paired must-fire control: the diagnostic clause naming the file on disk must
    stay absolute -- the fix belongs in the remedy's command, not in what the WARN
    says exists."""
    readme = _fragments_readme(
        tmp_path, "changelog.d", "# Fragments\n\nNo compatibility section here.\n"
    )
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "changelog.d"})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"

    # Diagnostic half: still names the absolute file on disk.
    assert str(readme) in message

    # Remedy half: the `--show` argument, pulled out of the message, is one
    # `scaffold.show` accepts without raising -- the positive control the issue's
    # reporter ran by hand (repo-relative form, exit 0).
    marker = "--show "
    start = message.index(marker) + len(marker)
    end = message.index("`", start)
    shown_path = message[start:end]
    assert shown_path == "changelog.d/README.md", message
    scaffold.show(tmp_path, {"changelog_dir": "changelog.d"}, path=shown_path)


def test_fragments_readme_unmeasured_without_config(tmp_path):
    doctor.check_fragments_readme(tmp_path, None)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not checked" in message


def _scaffolded_gate(root, gated_dir):
    workflow = root / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        "name: oss changelog\n"
        "        run: python3 .oss/assemble_changelog.py --check --dir '{0}' "
        "--changelog CHANGELOG.md\n"
        "          python3 .oss/assemble_changelog.py --check-links --dir '{0}' "
        "--changelog CHANGELOG.md || status=$?\n".format(gated_dir),
        encoding="utf-8",
    )


def test_fragments_readme_follows_a_nulled_changelog_dir_to_the_scaffolded_gate(tmp_path):
    """#325: `changelog_dir: null` does not always mean "no fragment practice" -- a
    repo scaffolded with a non-default directory and later nulled still carries a
    gate on disk policing that directory, and `release_version._fragment_dir`
    resolves it from there rather than the default. This check must read the same
    file, or it silently inspects `changelog.d/` while the directory the release
    gate actually reads sits elsewhere -- a false "no fragment practice" OK on a
    repo that has one."""
    # See the sibling assertion in test_fragments_readme_resolves_changelog_dir_
    # from_config_not_a_hardcoded_name for why this is str(Path) and not a
    # "docs/frags" string literal (#260 review): the message is rendered with
    # str(Path), backslash-joined on Windows, and a POSIX literal never matches
    # a passing run there.
    expected_dir = tmp_path / "docs" / "frags"
    _scaffolded_gate(tmp_path, "docs/frags")
    _fragments_readme(tmp_path, "docs/frags", "no compatibility section here\n")
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": None})
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN", doctor.FINDINGS
    assert str(expected_dir) in message
    assert "/oss:scaffold will not fix it" in message

    # Must-fire control: the same gate, with the bullet actually present, grades OK.
    doctor.FINDINGS.clear()
    _fragments_readme(tmp_path, "docs/frags", "- Compatibility: breaking|compatible - <reason>\n")
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": None})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK", doctor.FINDINGS
    assert str(expected_dir) in message


def test_fragments_readme_invalid_changelog_dir_does_not_fall_back_to_the_default(tmp_path):
    """A `changelog_dir` that fails validation is a broken value, not an absent one --
    trying the default in its place would check a directory nobody named."""
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "README.md").write_text(
        "- Compatibility: breaking|compatible - <reason>\n", encoding="utf-8"
    )
    doctor.check_fragments_readme(tmp_path, {"changelog_dir": "/etc/passwd"})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK", doctor.FINDINGS
    assert "no directory this run could resolve" in message


# --- can the merge call skip supertool's own confirm gate? (#421) -------------


def test_publish_confirm_needs_force_is_the_default_with_no_config_at_all(tmp_path):
    """No `.supertool.json` at all is the shipped default -- `needs-force`, never
    `could-not-tell`. The absence of a file is not the same failure as a file that
    is there and broken."""
    state, _detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "needs-force"


def test_publish_confirm_reports_confirmable_when_the_config_flag_is_set(tmp_path):
    """The must-fire arm for `confirmable`."""
    _supertool_config(tmp_path, {"presets": ["git", "github"], "no_publish_confirm": True})
    state, detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "confirmable"
    assert "gh-pr-merge" in detail


def test_publish_confirm_reports_confirmable_when_the_env_var_is_set(tmp_path):
    """The env opt-out is read too, not only the config key."""
    _supertool_config(tmp_path, {"presets": ["git", "github"]})
    state, _detail = doctor.publish_confirm_state(
        tmp_path, env={"SUPERTOOL_NO_PUBLISH_CONFIRM": "1"}
    )
    assert state == "confirmable"


def test_publish_confirm_needs_force_when_neither_opt_out_is_set(tmp_path):
    """The must-not-fire control for the test above: same fixture, no env
    override -- and it must NOT read as `confirmable`."""
    _supertool_config(tmp_path, {"presets": ["git", "github"]})
    state, detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "needs-force"
    assert "gh-pr-merge" in detail


def test_publish_confirm_detail_is_grammatical_with_no_config_at_all(tmp_path):
    """No `.supertool.json` at all means `presets` cannot be read either, so the
    `route_known is False` arm composes with the rest of the sentence -- this is
    the single most common repo state a fresh check like this one will hit, and
    a composition bug there would go unnoticed by a test that only asserts the
    state."""
    state, detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "needs-force"
    assert detail == (
        "no opt-out is set, so which op(s) it gates could not be read "
        "(`presets` in {} is absent or not a list of strings)".format(
            doctor.WATCH_CONFIG
        )
    )


def test_publish_confirm_detail_is_grammatical_when_confirmable_with_no_route(tmp_path):
    """The must-fire pair for the test above: same unreadable-route shape, this
    time with the opt-out on, so the `confirmable` branch's own composition of
    the same `reach` fragment is exercised too."""
    _supertool_config(tmp_path, {"no_publish_confirm": True})
    state, detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "confirmable"
    assert detail == (
        "`no_publish_confirm` in {} is truthy, so which op(s) it reaches "
        "could not be read (`presets` in {} is absent or not a list of "
        "strings)".format(doctor.WATCH_CONFIG, doctor.WATCH_CONFIG)
    )


def test_publish_confirm_names_every_op_the_switch_reaches_not_only_the_merge(tmp_path):
    """The opt-out is wider than the merge: `require_confirm` gates three ops, and
    a project whose `presets` enable more than `github` must see all of them
    named, not only `gh-pr-merge` (#421's own point about a half-told line)."""
    _supertool_config(
        tmp_path,
        {"presets": ["git", "github", "devto", "bluesky"], "no_publish_confirm": True},
    )
    state, detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "confirmable"
    assert "gh-pr-merge" in detail
    assert "devto_publish" in detail
    assert "bluesky_publish" in detail


def test_publish_confirm_names_none_reached_today_when_no_publish_preset_is_loaded(
    tmp_path,
):
    """A project whose `presets` exclude every op the gate covers still gets an
    honest `confirmable`, but the detail says the switch reaches nothing today --
    the shape #421 calls out: the flag disables confirmation for whatever is
    routed NOW, silently, for whatever arrives later."""
    _supertool_config(tmp_path, {"presets": ["git"], "no_publish_confirm": True})
    state, detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "confirmable"
    assert "none" in detail


def test_publish_confirm_could_not_tell_on_an_unreadable_config(tmp_path):
    """exit 0 always: an OSError that is not absence arrives as `could-not-tell`,
    never guessed into `confirmable` or `needs-force`. The deny is attempted
    rather than assumed."""
    blocked = tmp_path / doctor.WATCH_CONFIG
    blocked.write_text("{}", encoding="utf-8")
    try:
        blocked.chmod(0o000)
        if os.access(str(blocked), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 file (root, or a filesystem without "
                "POSIX modes), so the unreadable arm cannot be reached here"
            )
        state, _detail = doctor.publish_confirm_state(tmp_path, env={})
    finally:
        blocked.chmod(0o644)
    assert state == "could-not-tell"


def test_publish_confirm_could_not_tell_on_a_malformed_config(tmp_path):
    """A file that parses but is not an object is `could-not-tell`, not folded
    into the shipped default."""
    (tmp_path / doctor.WATCH_CONFIG).write_text("[]", encoding="utf-8")
    state, _detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "could-not-tell"


def test_publish_confirm_reads_a_truthy_non_boolean_flag_like_the_real_gate(tmp_path):
    """`_publish_safety.require_confirm` reads the key with plain `bool()`, not a
    type check -- `"yes"` really does turn confirmation off there, so reporting
    it as `could-not-tell` would be a wrong answer dressed as caution."""
    _supertool_config(tmp_path, {"presets": ["github"], "no_publish_confirm": "yes"})
    state, _detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "confirmable"


def test_publish_confirm_needs_force_control_for_a_falsy_non_boolean_flag(tmp_path):
    """The must-not-fire control for the test above: same shape, a falsy value --
    `bool("")` is `False`, same as the gate it reports on."""
    _supertool_config(tmp_path, {"presets": ["github"], "no_publish_confirm": ""})
    state, _detail = doctor.publish_confirm_state(tmp_path, env={})
    assert state == "needs-force"


def test_check_publish_confirm_never_renders_needs_force_as_a_fault(tmp_path, capsys):
    """The shipped default is reported as neutral information, not a warning --
    flagging the default trains a maintainer to skim doctor output."""
    _supertool_config(tmp_path, {"presets": ["git", "github"]})
    doctor.check_publish_confirm(tmp_path, env={})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK", doctor.FINDINGS
    assert "|force" in message


def test_check_publish_confirm_warns_on_could_not_tell_and_not_on_the_default(
    tmp_path, capsys
):
    """Must-fire/must-not-fire pair in one fixture family: a malformed file warns,
    the shipped default (no file at all) does not."""
    (tmp_path / doctor.WATCH_CONFIG).write_text("[]", encoding="utf-8")
    doctor.check_publish_confirm(tmp_path, env={})
    loud = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    doctor.check_publish_confirm(tmp_path.parent / "nonexistent-dir-for-421", env={})
    quiet = [state for state, _ in doctor.FINDINGS]

    assert loud == ["WARN"]
    assert quiet == ["OK"]


def test_check_publish_confirm_scopes_confirmable_to_supertools_own_gate(tmp_path):
    """A `confirmable` OK must say it is supertool's own gate only -- the
    harness's own permission layer sits above it and can still refuse the call
    (#421's own comment measured exactly that)."""
    _supertool_config(tmp_path, {"presets": ["github"], "no_publish_confirm": True})
    doctor.check_publish_confirm(tmp_path, env={})
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "harness" in message


def test_check_publish_confirm_prints_ascii_only_in_every_state(tmp_path):
    """Windows consoles encode with the codepage, not the source file's encoding,
    so a non-ASCII byte here kills the process at the print."""
    docs = [
        None,
        {"presets": ["git"]},
        {"presets": ["github"], "no_publish_confirm": True},
        {"presets": ["git", "github", "devto", "bluesky"], "no_publish_confirm": True},
        [],
    ]
    seen = set()
    for doc in docs:
        doctor.FINDINGS.clear()
        target = tmp_path / doctor.WATCH_CONFIG
        if doc is None:
            if target.exists():
                target.unlink()
        elif isinstance(doc, list):
            target.write_text(json.dumps(doc), encoding="utf-8")
        else:
            _supertool_config(tmp_path, doc)
        seen.add(doctor.publish_confirm_state(tmp_path, env={})[0])
        doctor.check_publish_confirm(tmp_path, env={})
        for _state, message in doctor.FINDINGS:
            message.encode("ascii")
    assert len(seen) == 3, sorted(seen)
