r"""#881 step 1: CI cannot say which tests are slow, because nothing collects timings.

`pyproject.toml`'s `addopts` used to be `-rs --cov=scripts --cov-report=term-missing
--cov-fail-under=85` -- no `--durations` anywhere -- so every one of the 13 CI legs
reported a single total (`3 failed, 5025 passed, ... in 230.61s`) and nothing about
where those seconds went. A test that takes 4 seconds and one that takes 4
milliseconds were indistinguishable in every artifact CI produces.

This is deliberately step 1 only: it proves the flag reaches pytest's resolved
configuration, nothing else. No test is touched, no optimisation made, no
pytest-xdist added -- those are steps 2 and 3 of #881 and out of scope here.

The check has to be over the *resolved* configuration, not a string search over
the file, per the issue's own test shape: "an option silently dropped from
`addopts` and an option never added render identically in a green build." A
plain `"--durations" in pyproject.toml.read_text()` would pass just as happily if
the flag were misspelled inside a comment, added to the wrong ini section (e.g.
`[tool.pytest]` instead of `[tool.pytest.ini_options]`), or shadowed by a
competing `PYTEST_ADDOPTS` env var. So this drives a real pytest run in a fresh
`sys.executable -m pytest` subprocess -- not this suite's own in-process Config,
because this file is itself collected by the outer suite's pytest, and nesting a
second Config resolution inside that process is exactly the kind of thing
coverage instrumentation can perturb -- against a trivial stub test placed
*inside this repository's own tree* (required: pytest discovers `pyproject.toml`
by walking up from the given test path, not from the caller's cwd, so a target
outside the repo would silently pick up no config and every check below would be
vacuous; the positive control proves this fires as expected against the stub
test's own trivial pass, not against collection with nothing executed --
`--durations` only reports call-phase timings once a test has actually run, so a
`--collect-only` probe would never show the header regardless of the flag, which
is exactly the trap this docstring is recording).

Every assertion is paired with a positive or negative control per CLAUDE.md's
"must fire" pairing: the header appears when durations reporting really is wired
(current `pyproject.toml`, one real test run), and does not appear when `addopts`
is invoked without it (the pre-#881 string, explicitly), proving the probe would
have caught the exact silent-drop failure #881 names.
"""

import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_ADDOPTS_LINE = re.compile(r'(?m)^addopts\s*=\s*"([^"]*)"')
# `--durations=N` (N > 0) prints "slowest N durations"; `--durations=0` (show all)
# prints "slowest durations" with no count. Both are pytest's own durations
# summary header, so the count is optional in the pattern.
_DURATIONS_HEADER = re.compile(r"slowest (\d+ )?durations?", re.IGNORECASE)

_STUB_TEST_BODY = "def test_stub_trivial():\n    assert True\n"

#: pre-#881 addopts, transcribed verbatim from the issue's own quoted string --
#: the exact configuration the flag was silently dropped *from*, for the negative
#: control below.
_PRE_881_ADDOPTS = "-rs --cov=scripts --cov-report=term-missing --cov-fail-under=85"


def _declared_addopts():
    """The literal `addopts` string in `pyproject.toml`'s `[tool.pytest.ini_options]`."""
    match = _ADDOPTS_LINE.search(Path(REPO_ROOT, "pyproject.toml").read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _run_stub_test(addopts_override=None):
    """Run one trivial, always-passing test in a fresh subprocess, from inside this
    repository's own tree, and return everything it printed.

    `addopts_override` replaces pyproject.toml's addopts for this one invocation
    via pytest's own `-o` override, without touching the file -- the negative
    control needs to prove the probe *would* have caught #881's failure mode
    without actually breaking the fix under test.
    """
    stub_dir = REPO_ROOT / ("_durprobe_881_" + uuid.uuid4().hex[:8])
    stub_dir.mkdir()
    stub_path = stub_dir / "test_stub.py"
    try:
        stub_path.write_text(_STUB_TEST_BODY, encoding="utf-8")
        args = [sys.executable, "-m", "pytest", "-q", str(stub_path)]
        if addopts_override is not None:
            args += ["-o", "addopts=" + addopts_override]
        result = subprocess.run(
            args,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout + result.stderr
    finally:
        # shutil.rmtree, not unlink()+rmdir(): running the stub test compiles
        # test_stub.py, leaving a __pycache__/ directory inside stub_dir, so a
        # bare rmdir() (which requires an empty directory) raises here. Measured
        # directly rather than assumed: .pytest_cache/ itself lands at REPO_ROOT,
        # not inside stub_dir -- it is the bytecode cache, not pytest's own cache,
        # that makes rmdir() fail.
        shutil.rmtree(stub_dir, ignore_errors=True)


# ------------------------------------------------------------------- positive controls


def test_pyproject_declares_an_addopts_line_at_all():
    """Positive control: if this stops being true, every check below is vacuous."""
    assert _declared_addopts() is not None, "pyproject.toml no longer declares addopts"


def test_probe_reports_the_durations_header_when_durations_is_forced_on():
    """Positive control for the probe mechanism itself: with `--durations=0` passed
    directly via an addopts override, the subprocess must show the durations
    header for its one real test. If this fails, the probe cannot detect the
    header under any configuration and the checks below prove nothing."""
    output = _run_stub_test(addopts_override="--durations=0")
    assert _DURATIONS_HEADER.search(output), (
        "the durations header never appeared even with --durations=0 forced via "
        "an addopts override -- the probe itself cannot see durations reporting:\n"
        + output
    )


# ------------------------------------------------------------------------ the real checks


def test_durations_flag_is_declared_in_addopts():
    """Content check over the resolved source of addopts: #881 step 1's actual ask."""
    addopts = _declared_addopts()
    assert addopts is not None
    assert re.search(r"--durations(=\d+)?\b", addopts), (
        "pyproject.toml's addopts does not request --durations (#881) -- CI has no "
        "way to say which tests are slow"
    )


def test_addopts_durations_actually_reaches_pytests_resolved_configuration():
    """The teeth: not just present in the file, but honoured by pytest itself when
    invoked exactly as CI and a contributor's documented command invoke it -- no
    extra flags, relying purely on pyproject.toml's own addopts."""
    output = _run_stub_test()
    assert _DURATIONS_HEADER.search(output), (
        "pyproject.toml declares --durations but a real pytest run against this "
        "repo's own config never printed a durations summary -- the flag is "
        "present in the file but not resolved into pytest's real configuration "
        "(wrong ini section, typo, or a competing PYTEST_ADDOPTS):\n" + output
    )


# ------------------------------------------------------------------------ negative control


def test_a_config_without_durations_would_fail_this_check():
    """Negative control: proves the check has teeth by reproducing #881's exact
    failure mode -- an option silently dropped from addopts renders identically to
    one never added, in a green build, unless something actually looks. Here,
    something looks: invoking the same real test run with addopts overridden to
    the pre-#881 string (no --durations) must NOT show the durations header."""
    output = _run_stub_test(addopts_override=_PRE_881_ADDOPTS)
    assert not _DURATIONS_HEADER.search(output), (
        "the durations header appeared even with addopts overridden to the "
        "pre-#881 string with no --durations flag -- this check cannot actually "
        "detect the option being dropped, which is the exact failure #881 names"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
