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
