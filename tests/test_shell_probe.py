"""The launcher suites must measure the shell they spawn, not name it.

`shutil.which("bash")` answers with the first `bash` on PATH. On a Windows runner
that is regularly System32's `bash.exe` -- WSL's launcher, which is a real POSIX
shell with no distribution behind it, or with one whose filesystem has never heard
of the Windows path the test is about to hand it. The name matches; the binary is
the wrong one.

Both failures that produces are wrong in a way that hides the cause:

* a shell that starts and cannot do the job turns every assertion in the file red,
  and each failure reads as a bug in `doctor.sh` or `oss-workspace`;
* no shell at all skips the WHOLE file, including the assertions that only read the
  script's source text and never wanted a shell -- a green run that measured nothing.

So this file simulates both conditions against the real launcher suites, by running
them in a child pytest with a doctored PATH. It is the only place in the tree where
those two states are observed rather than reasoned about.
"""

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# Stated rather than inherited: pytest's default import mode puts this directory on
# sys.path as a side effect, and the bare import breaks under `--import-mode=importlib`.
sys.path.insert(0, str(REPO_ROOT / "tests"))

import shell_probe  # noqa: E402

LAUNCHER_SUITES = [
    str(REPO_ROOT / "tests" / "test_doctor_launcher.py"),
    str(REPO_ROOT / "tests" / "test_workspace_launcher.py"),
]

# The assertions in those two files that read a script's source text and spawn
# nothing. They must run on every platform, because the branch they protect is the
# one nobody exercises locally.
SOURCE_ONLY = "strip_either_separator or bare_python3 or posix_sh_not_bash"

SOURCE_ONLY_COUNT = 3

# What WSL's bash.exe says when no distribution is installed. Recorded rather than
# imagined; the real thing arrives UTF-16-encoded, which is why the classifier has
# to survive interleaved NULs.
WSL_REFUSAL = "Windows Subsystem for Linux has no installed distributions."


def _stub_bash(directory):
    """A `bash` that resolves, spawns, exits non-zero and is not a usable shell."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "bash"
    path.write_text(
        "\n".join(["#!/bin/sh", 'echo "' + WSL_REFUSAL + '" >&2', "exit 1", ""]),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


#: #908: the full-suite child below runs both launcher suites -- 101 tests that spawn shells,
#: measured at 83s on their own -- so a leg that runs it pays roughly 44s for this one test.
#: Paid on all 13 legs it was 9.5 minutes of runner time per push for a condition that cannot
#: occur on 8 of them.
#:
#: It runs where the condition it simulates is real (Windows, where WSL's `bash` sits ahead of
#: the usable one on `PATH`) and on exactly one POSIX leg so the other path stays covered. The
#: interpreter is pinned so "one Linux leg" is one and not four.
#:
#: `test_the_matrix_still_has_a_leg_for_each_run_condition` is what keeps this honest: a skip
#: condition no leg satisfies disables the test everywhere and says nothing, which is a check
#: that never ran rendering as a check that found nothing -- this repository's own defect class,
#: applied to the fix rather than to the bug.
FULL_SUITE_POSIX_LEG = (3, 9)
FULL_SUITE_POSIX_OS = "ubuntu-latest"
FULL_SUITE_WINDOWS_OS = "windows-latest"


def _full_suite_leg():
    """`(runs_here, why)` -- never a bare boolean, so the skip can say where it does run."""
    if platform.system() == "Windows":
        return True, "Windows: the System32/WSL case this simulates is a Windows one"
    pinned = "{}.{}".format(*FULL_SUITE_POSIX_LEG)
    if sys.version_info[:2] == FULL_SUITE_POSIX_LEG:
        return True, "the pinned POSIX leg (Python {})".format(pinned)
    return False, (
        "runs on every Windows leg and on the pinned POSIX leg (Python {}), not on this one "
        "(Python {}.{} on {}). UNTESTED here: whether a broken shell earlier on PATH leaves the "
        "launcher suites able to run -- covered by those legs, and "
        "test_the_matrix_still_has_a_leg_for_each_run_condition fails if the matrix stops "
        "carrying them.".format(
            pinned, sys.version_info[0], sys.version_info[1], platform.system()
        )
    )


def _child_pytest(path_entries, args):
    """Run the launcher suites in a child pytest under a PATH we control.

    `sys.executable` is absolute, so the child starts regardless of what PATH says;
    that is deliberate, because the PATH here is the thing under test and starving
    the child of an interpreter would be a fixture failure wearing a finding's
    clothes.
    """
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([entry for entry in path_entries if entry])
    env.pop("OSS_TEST_BASH", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "--no-cov",
         "-p", "no:cacheprovider"] + list(args),
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _collected(suites):
    """How many tests those suites contain, asked of pytest rather than counted here.

    Collection runs under the ambient PATH: it is the baseline the doctored run is
    compared against, so doctoring it too would compare a number to itself.
    """
    done = _child_pytest(
        [os.environ.get("PATH", "")], list(suites) + ["--collect-only"]
    )
    assert done.returncode == 0, done.stdout[-4000:]
    return len([line for line in done.stdout.splitlines() if "::test_" in line])


def test_a_broken_shell_earlier_on_path_does_not_turn_the_suites_red(tmp_path):
    """The System32 case. A `bash` that spawns and fails sits ahead of the real one,
    exactly as WSL's does on a Windows runner; a usable shell is still reachable
    further along PATH. Nothing here is a defect in either launcher, so nothing here
    may be reported as one.
    """
    stub = _stub_bash(tmp_path / "stubbin")
    # The fixture's own premise, checked rather than assumed. The condition being
    # simulated is a binary that SPAWNS and fails; a stub that cannot be started at
    # all is a different condition, and on Windows a `#!` script planted under a
    # binary's name is exactly that. Left unchecked, this test would pass there
    # having simulated nothing -- which is the defect it exists to catch.
    ok, note = shell_probe.probe(stub, [REPO_ROOT / "README.md"])
    assert ok is False, note
    if not note.startswith("exit "):
        pytest.skip(
            "a broken shell cannot be planted on this platform, so the condition was "
            "never created: the stub answered {!r} rather than running and "
            "failing".format(note)
        )
    runs_here, why = _full_suite_leg()
    if not runs_here:
        pytest.skip(why)
    done = _child_pytest([str(stub.parent), os.environ.get("PATH", "")], LAUNCHER_SUITES)
    assert "failed" not in done.stdout, done.stdout[-4000:]
    assert done.returncode == 0, done.stdout[-4000:]
    # The positive control, and the whole claim. "Nothing failed" and "exit 0" are
    # both satisfied by a run in which every test SKIPPED, which is precisely the
    # outcome this fix must not produce here: a usable shell was reachable, so the
    # suites had to run. The expected count is collected rather than written down,
    # so adding a test to either suite cannot quietly weaken this to "some passed".
    assert "{} passed".format(_collected(LAUNCHER_SUITES)) in done.stdout, done.stdout[-4000:]


def test_no_shell_at_all_does_not_silence_the_assertions_that_never_wanted_one(tmp_path):
    """The other half. With no shell reachable the spawning tests can only report
    that they could not run -- but the source-text assertions spawn nothing, and a
    file-wide skip that takes them down is this plugin's own defect class: a check
    that never ran, rendered exactly like a check that found nothing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    assert shutil.which("bash", path=str(empty)) is None
    done = _child_pytest([str(empty)], LAUNCHER_SUITES + ["-k", SOURCE_ONLY])
    assert "{} passed".format(SOURCE_ONLY_COUNT) in done.stdout, done.stdout[-4000:]


def test_a_suite_that_could_not_find_a_shell_says_what_it_tried(tmp_path):
    """The third state has to be legible. "no bash" fires identically where a shell
    is genuinely absent and where one was looked for in the wrong place, and nobody
    reading the log can tell those apart.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    done = _child_pytest([str(empty)], LAUNCHER_SUITES)
    assert "no usable shell" in done.stdout, done.stdout[-4000:]
    assert "failed" not in done.stdout, done.stdout[-4000:]

# The classifier's own controls. They spawn nothing, so they run everywhere -- which
# is the point: a blanket skip on "no shell here" would take down the only thing
# standing between "this machine has no shell" and "the probe has quietly started
# rejecting every shell, everywhere".


def test_a_wsl_refusal_is_not_a_usable_shell():
    """The recorded reply, NUL-interleaved the way UTF-16 delivers it."""
    encoded = "\x00".join(WSL_REFUSAL) + "\x00"
    ok, note = shell_probe.classify(1, encoded, expected=2)
    assert ok is False
    assert "no installed distributions" in note


def test_a_shell_that_sees_everything_handed_to_it_is_usable():
    """The positive control for the assertion above. Without it, a classifier that
    rejected every input would pass the whole file.
    """
    ok, note = shell_probe.classify(0, "shell\nsees\nsees\n", expected=2)
    assert ok is True
    assert "all 2 paths" in note


def test_a_shell_that_sees_only_some_of_them_is_not_usable():
    """The half-answer. It exits 0 and it is a shell, so a returncode check and a
    name check both wave it through; it is the WSL-with-a-distribution shape, where
    the shell is real and the Windows paths are not there.
    """
    ok, note = shell_probe.classify(0, "shell\nsees\n", expected=2)
    assert ok is False
    assert "1 of the 2" in note


def test_a_silent_success_is_not_usable():
    """Exits 0, says nothing. The sentinel is what rejects it."""
    assert shell_probe.classify(0, "", expected=0)[0] is False


def test_the_report_names_every_candidate_and_what_it_said():
    tried = [("/w/bash", (False, "exit 1: refused")), ("/g/bash", (False, "not spawnable"))]
    said = shell_probe.report(tried)
    assert "no usable shell" in said
    assert "/w/bash" in said and "refused" in said
    assert "/g/bash" in said and "not spawnable" in said


def test_the_report_says_so_when_there_was_nothing_to_try():
    """Distinct from every candidate failing. Rendering those two the same is how a
    search that looked in the wrong place reads as a machine with no shell.
    """
    said = shell_probe.report([])
    assert "no candidate was found to try" in said


def test_a_broken_candidate_ahead_of_a_working_one_is_not_picked():
    """`pick` takes the first candidate that ANSWERED usably, not the first that
    resolved. Ordering on PATH is not evidence about the binary.
    """
    broken = ("/system32/bash.exe", (False, "exit 1: no installed distributions"))
    working = ("/git/bin/bash.exe", (True, "ok"))
    assert shell_probe.pick([broken, working]) == "/git/bin/bash.exe"
    assert shell_probe.pick([broken]) is None


def test_a_real_shell_is_probed_by_spawning_it():
    """The end-to-end control: `classify` above is fed recorded strings, so without
    this nothing proves a real spawn ever produces one of them.
    """
    witness = REPO_ROOT / "README.md"
    tried = shell_probe.attempts([witness])
    candidate = shell_probe.pick(tried)
    if candidate is None:
        pytest.skip(shell_probe.report(tried))
    assert shell_probe.probe(candidate, [witness])[0] is True
    assert shell_probe.probe(candidate, [REPO_ROOT / "nothing-is-here"])[0] is False


# --- #908's guard: the skip above must not be able to disable this everywhere ------------
#
# `_full_suite_leg` names two legs by hand. Nothing stops somebody dropping `windows-latest`
# from the matrix, or moving the floor off 3.9 -- and the expensive test would then skip on
# every leg, reporting `1 skipped` where nobody reads it, with no failure anywhere. This reads
# the matrix and fails instead, naming the skip it just orphaned.

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard below
    yaml = None


def test_the_yaml_parser_this_guard_needs_is_present_on_ci():
    """A skipped guard and a passing guard are the same tick, so CI must not skip this."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so #908's matrix guard did not run on a "
            "runner. requirements-dev.txt declares it and the pytest job installs it; if that "
            "changed, this guard went quiet rather than red."
        )
    pytest.skip(
        "pyyaml is not installed, so the matrix behind _full_suite_leg was not read. UNTESTED "
        "here: whether the legs that run the full-suite child still exist in tests.yml."
    )


def _matrix():
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in spec["jobs"].values():
        matrix = job.get("strategy", {}).get("matrix")
        if matrix and "os" in matrix and "python-version" in matrix:
            return matrix
    raise AssertionError("no job in tests.yml declares an os/python-version matrix")


def _check_matrix(matrix):
    """The assertions, over a matrix passed in rather than read here.

    Separated so the control below can hand it a matrix that must fail. A guard whose
    failure path is never executed is an assertion that nothing is wrong and an assertion
    that nothing was checked, wearing the same green tick.
    """
    versions = [str(v) for v in matrix["python-version"]]
    pinned = "{}.{}".format(*FULL_SUITE_POSIX_LEG)
    assert FULL_SUITE_WINDOWS_OS in matrix["os"], (
        "_full_suite_leg runs the full-suite child on Windows and the matrix no longer has "
        "{!r}, so that half of the condition is unreachable and the test would skip there "
        "silently. Matrix os: {}".format(FULL_SUITE_WINDOWS_OS, matrix["os"])
    )
    assert FULL_SUITE_POSIX_OS in matrix["os"], (
        "_full_suite_leg's POSIX half needs {!r} in the matrix. Matrix os: {}".format(
            FULL_SUITE_POSIX_OS, matrix["os"]
        )
    )
    assert pinned in versions, (
        "_full_suite_leg pins the POSIX leg to Python {}, which the matrix no longer runs, so "
        "the full-suite child would run on no POSIX leg at all. Matrix python-version: "
        "{}. Move FULL_SUITE_POSIX_LEG to a version the matrix has.".format(pinned, versions)
    )


def test_the_matrix_still_has_a_leg_for_each_run_condition():
    """Must fire: both halves of `_full_suite_leg`'s run condition are reachable in CI."""
    if yaml is None:
        pytest.skip("pyyaml is not installed; see the guard above")
    _check_matrix(_matrix())


def test_the_guard_fails_on_a_matrix_that_dropped_either_leg():
    """Must not fire, executed rather than asserted about.

    `AssertionError` and not `Exception`: pytest's own outcome exceptions derive from
    `BaseException` and a `pytest.skip` inside a `raises(Exception)` block sails past it,
    skipping the enclosing test -- a green tick over an assertion that never ran.
    """
    real = {"os": [FULL_SUITE_WINDOWS_OS, FULL_SUITE_POSIX_OS], "python-version": ["3.9", "3.12"]}
    _check_matrix(real)  # the control's own control: this shape must pass

    for dropped in (
        {"os": [FULL_SUITE_POSIX_OS], "python-version": ["3.9"]},
        {"os": [FULL_SUITE_WINDOWS_OS], "python-version": ["3.9"]},
        {"os": [FULL_SUITE_WINDOWS_OS, FULL_SUITE_POSIX_OS], "python-version": ["3.12"]},
    ):
        with pytest.raises(AssertionError):
            _check_matrix(dropped)
