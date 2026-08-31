"""#716 -- a spawn that never answered measured nothing, and must not render as a
failed assertion about what it would have said.

#712 fixed exactly one site: `tests/test_oss_rules.py`'s `_ere_matches`, where a
Windows runner's `awk.EXE` did not answer a one-line `BEGIN` block inside ten
seconds and the uncaught `subprocess.TimeoutExpired` reported as a **failed ERE
assertion** on a release commit that touched neither the rule, the pattern nor the
function. The defect is not the timeout. It is that a spawn producing no answer
rendered identically to one producing the wrong answer.

This module is the general form, in two halves that fail differently:

- **The runtime half.** `spawn_guard.run` is the one place a `TimeoutExpired`
  becomes a `pytest.skip` carrying what went unmeasured. Fourteen-odd hand-written
  skip messages would drift; one helper cannot.
- **The static half.** `spawn_guard.scan_tree` re-derives the sweep #716 was filed
  from, over `tests/` as it stands, so site number forty arrives guarded or red
  rather than unnoticed. A guard built for one hand-named site, in a set that
  grows, goes quietly narrower than its own subject -- which is what happened
  between #712 and #716.

Both halves carry their positive control in the same fixture. A "must not fire"
assertion also passes when nothing fires at all: the sweep is paired with a check
that it reached the suite at all, and the timeout skip is paired with a real
non-zero exit that must still come back to the caller to assert on.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# Stated rather than inherited: pytest's default import mode puts this directory
# on sys.path as a side effect, and that stops under `--import-mode=importlib`.
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402


# --- the runtime half ----------------------------------------------------------------


def test_a_timeout_skips_the_whole_test_and_says_what_went_unmeasured(monkeypatch):
    """The outcome type is pinned to pytest's own skip exception rather than left
    to `Exception`. `pytest.raises(Exception)` does NOT catch a skip -- pytest's
    outcome exceptions derive from `BaseException` (the trap CLAUDE.md records, and
    re-measured in `test_pytest_skip_is_not_an_exception_subclass` below) -- so a
    helper that merely swallowed the timeout and returned `None` would pass an
    `Exception`-typed assertion for entirely the wrong reason.
    """

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["nonesuch-binary", "-x"], timeout=7)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(pytest.skip.Exception) as caught:
        spawn_guard.run(
            ["nonesuch-binary", "-x"],
            subject="whether the widget answers at all",
            timeout=7,
        )
    said = str(caught.value)
    assert "nonesuch-binary" in said, said
    assert "7" in said, said
    assert sys.platform in said, said
    assert "whether the widget answers at all" in said, said
    assert "716" in said, said


def test_pytest_skip_is_not_an_exception_subclass():
    """Measured here rather than asserted in a comment, because the test above is
    only meaningful if this holds -- and it is a fact about the installed pytest,
    which is a dependency this repository does not pin to a single version.
    """
    assert not issubclass(pytest.skip.Exception, Exception)
    assert issubclass(pytest.skip.Exception, BaseException)


def test_timeoutexpired_is_not_an_oserror():
    """The other fact the sweep depends on. Several call sites in this suite guard
    a spawn with `except OSError` for an unspawnable binary; that handler does not
    catch a timeout, so `scan_tree` must not read one as a timeout guard.
    """
    assert not issubclass(subprocess.TimeoutExpired, OSError)
    assert issubclass(subprocess.TimeoutExpired, subprocess.SubprocessError)


def test_the_positive_control_a_real_non_zero_exit_still_reaches_the_caller():
    """Must fire. Only the no-answer case changes: a tool that ran and refused
    produced a real answer about a real invocation, and every converted call site
    still asserts on it. A helper that swallowed this too would turn fourteen tests
    green while measuring nothing -- the failure this whole change exists to avoid,
    reproduced by its own fix.
    """
    result = spawn_guard.run(
        [sys.executable, "-c", "import sys; sys.stdout.write('spoke'); sys.exit(3)"],
        subject="a control: the exit code and stdout must both come back",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 3
    assert result.stdout.strip() == "spoke"


def test_check_true_still_raises_on_a_non_zero_exit():
    """`check=True` is a real answer arriving as an exception, not a no-answer, so
    it must pass straight through.
    """
    with pytest.raises(subprocess.CalledProcessError):
        spawn_guard.run(
            [sys.executable, "-c", "import sys; sys.exit(4)"],
            subject="a control: check=True must still raise",
            timeout=60,
            check=True,
        )


def test_an_unspawnable_binary_is_not_a_timeout(tmp_path):
    """An `OSError` says the spawn never started, which is a different finding from
    a spawn that started and went quiet. It is deliberately not folded in here: the
    call sites that care already carry their own `except OSError` arm with their own
    sentence, and swallowing it centrally would take that arm's answer away.
    """
    missing = tmp_path / "definitely-not-a-binary"
    with pytest.raises(OSError):
        spawn_guard.run([str(missing)], subject="a control: never spawned", timeout=60)


def test_a_call_with_no_timeout_is_refused_at_the_signature():
    """A spawn with no timeout cannot time out and cannot be skipped; it hangs. The
    helper takes `timeout` as a required keyword so that routing a call through it
    cannot quietly drop the thing it exists to handle.
    """
    with pytest.raises(TypeError):
        spawn_guard.run([sys.executable, "-c", ""], subject="no timeout given")


def test_a_call_with_no_subject_is_refused_at_the_signature():
    """The skip message is only useful if it names what went unmeasured, so the
    subject is required too -- a helper that defaulted it would produce fourteen
    identical, useless skip reasons.
    """
    with pytest.raises(TypeError):
        spawn_guard.run([sys.executable, "-c", ""], timeout=60)


# --- the static half: controls first, then the sweep ---------------------------------


UNGUARDED = textwrap.dedent(
    """
    import subprocess

    def test_thing():
        result = subprocess.run(["tool"], capture_output=True, timeout=10)
        assert result.returncode == 0
    """
)

GUARDED_BY_TIMEOUTEXPIRED = textwrap.dedent(
    """
    import subprocess
    import pytest

    def test_thing():
        try:
            result = subprocess.run(["tool"], capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            pytest.skip("no answer")
        assert result.returncode == 0
    """
)

GUARDED_BY_SUBPROCESSERROR = textwrap.dedent(
    """
    import subprocess

    def test_thing():
        try:
            result = subprocess.run(["tool"], capture_output=True, timeout=10)
        except subprocess.SubprocessError:
            return
        assert result.returncode == 0
    """
)

GUARDED_BY_OSERROR_ONLY = textwrap.dedent(
    """
    import subprocess

    def test_thing():
        try:
            result = subprocess.run(["tool"], capture_output=True, timeout=10)
        except OSError:
            return
        assert result.returncode == 0
    """
)

NO_TIMEOUT_AT_ALL = textwrap.dedent(
    """
    import subprocess

    def test_thing():
        result = subprocess.run(["tool"], capture_output=True)
        assert result.returncode == 0
    """
)

THROUGH_THE_HELPER = textwrap.dedent(
    """
    import spawn_guard

    def test_thing():
        result = spawn_guard.run(["tool"], subject="x", capture_output=True, timeout=10)
        assert result.returncode == 0
    """
)


def test_control_an_unguarded_spawn_is_reported():
    """The must-fire half. Without this the two must-not-fire controls below, and
    the sweep itself, all pass just as happily against an analyzer that reports
    nothing at all.
    """
    scan = spawn_guard.scan_source(UNGUARDED, "synthetic.py")
    assert len(scan.spawns) == 1, scan
    assert len(scan.unguarded) == 1, scan
    assert scan.unguarded[0].func == "test_thing"
    assert scan.unguarded[0].lineno == 5


@pytest.mark.parametrize(
    "source",
    [GUARDED_BY_TIMEOUTEXPIRED, GUARDED_BY_SUBPROCESSERROR],
    ids=["TimeoutExpired", "SubprocessError"],
)
def test_control_a_spawn_whose_try_catches_a_timeout_is_clean(source):
    scan = spawn_guard.scan_source(source, "synthetic.py")
    assert len(scan.spawns) == 1, scan
    assert scan.unguarded == [], scan


def test_control_an_oserror_only_guard_is_not_a_timeout_guard():
    """`except OSError` catches an unspawnable binary and NOT a timeout -- measured
    in `test_timeoutexpired_is_not_an_oserror` above. An analyzer that accepted any
    handler at all would call eight sites in this suite clean while every one of
    them still renders a timeout as a failure.
    """
    scan = spawn_guard.scan_source(GUARDED_BY_OSERROR_ONLY, "synthetic.py")
    assert len(scan.unguarded) == 1, scan


def test_control_a_spawn_with_no_timeout_is_out_of_scope():
    """A spawn with no timeout at all hangs rather than misreporting, which is a
    different defect and not this one. It is neither counted nor reported, and the
    module docstring says so rather than leaving the silence to be read as a pass.
    """
    scan = spawn_guard.scan_source(NO_TIMEOUT_AT_ALL, "synthetic.py")
    assert scan.spawns == [], scan
    assert scan.unguarded == [], scan


ALIASED_SUBPROCESS = textwrap.dedent(
    """
    import subprocess as sp

    def test_thing():
        result = sp.run(["tool"], capture_output=True, timeout=10)
        assert result.returncode == 0
    """
)

FROM_IMPORTED_SPAWN = textwrap.dedent(
    """
    from subprocess import run

    def test_thing():
        result = run(["tool"], capture_output=True, timeout=10)
        assert result.returncode == 0
    """
)

ALIASED_HELPER = textwrap.dedent(
    """
    from spawn_guard import run as guarded

    def test_thing():
        result = guarded(["tool"], subject="x", capture_output=True, timeout=10)
        assert result.returncode == 0
    """
)

UNRELATED_RUN = textwrap.dedent(
    """
    from mymodule import run

    def test_thing():
        result = run(["tool"], timeout=10)
        assert result
    """
)


@pytest.mark.parametrize(
    "source", [ALIASED_SUBPROCESS, FROM_IMPORTED_SPAWN], ids=["as-alias", "from-import"]
)
def test_control_a_spawn_reached_through_an_alias_is_still_seen(source):
    """Must fire. The analyzer resolves the module's own `import` statements rather
    than matching the literal spelling `subprocess.`: an aliased spawn that the
    sweep could not see would report as clean, which is this module's own subject
    one level up in the tool. (Raised by the audit on this change; there is no such
    import in `tests/` today, and that is precisely why the first one would produce
    no signal.)
    """
    scan = spawn_guard.scan_source(source, "synthetic.py")
    assert len(scan.spawns) == 1, scan
    assert len(scan.unguarded) == 1, scan


def test_control_an_aliased_helper_call_is_seen_and_clean():
    scan = spawn_guard.scan_source(ALIASED_HELPER, "synthetic.py")
    assert len(scan.spawns) == 1, scan
    assert scan.unguarded == [], scan


def test_control_an_unrelated_run_from_another_module_is_not_a_spawn():
    """The must-not-fire half of the two above. Resolving bare names by binding
    would otherwise turn every `run(..., timeout=...)` in the suite into a finding,
    which is a guard nobody could keep green and so a guard somebody switches off.
    """
    scan = spawn_guard.scan_source(UNRELATED_RUN, "synthetic.py")
    assert scan.spawns == [], scan


def test_control_a_call_routed_through_the_helper_is_counted_and_clean():
    """Counted, not dropped. A converted site that left the population would make
    the sweep's own positive control below weaken by exactly as much as this change
    improved things -- and a fully converted suite would then be indistinguishable
    from one the analyzer never read.
    """
    scan = spawn_guard.scan_source(THROUGH_THE_HELPER, "synthetic.py")
    assert len(scan.spawns) == 1, scan
    assert scan.unguarded == [], scan


def test_a_file_that_does_not_parse_is_reported_as_unscannable_not_as_clean(tmp_path):
    """The third state. A file the analyzer could not read produced no finding, and
    no finding is exactly what a clean file produces -- so it is returned in its own
    list and the sweep below fails on it separately.
    """
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    (tmp_path / "fine.py").write_text(UNGUARDED, encoding="utf-8")
    scan = spawn_guard.scan_tree(tmp_path)
    assert len(scan.unscannable) == 1, scan
    assert scan.unscannable[0].path.endswith("broken.py"), scan
    assert scan.unscannable[0].reason, "an unscannable file with no reason is a shrug"
    assert len(scan.unguarded) == 1, scan


# --- the sweep itself ----------------------------------------------------------------


def test_the_sweep_reached_this_suite_at_all():
    """The positive control for the two assertions below: an analyzer that matched
    nothing would pass both of them while measuring nothing. The floor is set well
    under the count observed when #716 was implemented. Measured by running
    `scan_tree` against `tests/` as it stood at the parent commit `cb5b28d`: **50**
    spawns, of which 39 were unguarded and converted here and 11 already carried
    their own try; and 57 after this change, counting the spawns its own new test
    files add. The floor is well below both so that deleting a test file does not
    redden an unrelated pull request.

    Those two numbers were 51 and 12 in the first draft of this file -- an
    off-by-one transcription of the lane's own sweep, caught by the review of this
    very commit. Worth leaving the correction visible: a wrong "measured" count in
    the one file whose whole subject is not letting an unmeasured thing pass for a
    measured one is the same defect one level up, and re-derivation is the only
    thing that catches it.
    """
    scan = spawn_guard.scan_tree(REPO_ROOT / "tests")
    assert len(scan.spawns) > 30, len(scan.spawns)


def test_every_test_file_in_this_suite_could_be_scanned():
    scan = spawn_guard.scan_tree(REPO_ROOT / "tests")
    assert scan.unscannable == [], (
        "these files could not be parsed, so nothing is known about the spawns in "
        "them -- which is not the same as their having none: {}".format(
            [(u.path, u.reason) for u in scan.unscannable]
        )
    )


def test_no_spawn_in_this_suite_lets_a_timeout_render_as_a_failure():
    scan = spawn_guard.scan_tree(REPO_ROOT / "tests")
    assert scan.unguarded == [], (
        "these spawns carry a timeout that nothing catches, so a runner too slow to "
        "answer reports whatever the test would have asserted about the answer "
        "instead of reporting that there was none (#716). Route each one through "
        "spawn_guard.run(..., subject=...), or wrap it in a try that catches "
        "subprocess.TimeoutExpired: {}".format(
            ["{}:{} in {}".format(s.path, s.lineno, s.func) for s in scan.unguarded]
        )
    )
