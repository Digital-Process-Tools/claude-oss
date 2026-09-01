"""`must_assert_on` -- #430.

#265 established, over four rounds, that a Windows junction can be measured
for real on an unelevated `windows-latest` runner. Nothing before this test
existed would notice if a future runner image, Python version, or policy
change took that mechanism away again: the one test written to measure it
would quietly start SKIPPING instead of asserting, and a skip does not fail a
build.

`tests/must_assert_plugin.py` is the fix: a pytest plugin, loaded for the
whole suite via `tests/conftest.py`, that fails the SESSION if a test marked
`@pytest.mark.must_assert_on(PLATFORM)` reports SKIPPED while
`sys.platform == PLATFORM`.

The subject here is session-level exit-code behaviour, not a single test's
return value, so ordinary in-process assertions cannot reach it -- there is
no way to assert "the outer pytest run would have failed" from inside a test
that outer run is itself executing. `pytest`'s own `pytester` fixture is the
standard way to test a pytest plugin: it drives a real, separate pytest
subprocess over a throwaway directory and hands back that subprocess's exit
code and terminal output.

Every case here loads `must_assert_plugin.py` verbatim as the throwaway
run's conftest -- not a rewritten copy -- so a bug in the module under test is
exactly as visible to these tests as it would be to the real suite.

## #719: the harness itself has a third state

`pytester.runpytest_subprocess()` spawns a *child* interpreter, and
`_pytest.pytester.Pytester.__init__` unconditionally relocates that child's
`HOME` (and `USERPROFILE`) to a fresh scratch directory, for the lifetime of
the fixture, on every platform. On a machine where pytest resolves from the
Python *user* site-packages -- which is relative to `HOME` -- the child
cannot import pytest at all, and every case below reported six false
assertions about `must_assert_on` instead of the one true fact: the probe
never ran. See #719 for the full measurement, including the control pair
that pins the mechanism to the relocated `HOME` rather than to "a different
binary".

`_run()`, below, is the fix, and it is a **skip**, not a repair of the
child's environment: reaching into the child interpreter's import path would
be a second hazard stacked on the one this file exists to catch, is not
shown to survive a machine this repository has not tested on, and is exactly
what the issue's own "What the fix is not" section warns against generalising
into believing solves anything -- a virtualenv makes the failure rarer, not
absent, and this file has to be able to say "I could not run this probe"
regardless of how rare it is. This mirrors the shape `CLAUDE.md` already
requires of a permission fixture whose deny did not take, and of `#712`'s
timeout skip in `tests/spawn_guard.py`.

`_run()` and its detector live in this file rather than in `tests/conftest.py`
or `tests/spawn_guard.py`. This file is, measured at the time of writing, the
only place in the suite that spawns a subprocess interpreter through
`pytester` at all (`tests/conftest.py` merely registers the `pytester` plugin
for the suite; nothing else uses it) -- so there is no second caller for a
shared fixture to serve yet, and `spawn_guard.py`'s own subject is a
different failure shape (`subprocess.TimeoutExpired` on a spawn that
answered too slowly, not a child that could not import the thing driving it).
If a second `pytester`-based test arrives, `_run()` is what should move to
`tests/conftest.py` as a fixture; scoping it here now is not a narrower
version of that future population, since that population is presently one.
"""

import re
import sys
from pathlib import Path

import pytest

import must_assert_plugin

pytest_plugins = ["pytester"]

_PLUGIN_SOURCE = Path(must_assert_plugin.__file__).read_text(encoding="utf-8")

# The real marker names an actual OS value ("win32"). These tests must run
# identically regardless of which platform hosts them, so they use
# `sys.platform` -- guaranteed to match the pytester subprocess, which is a
# child of this same interpreter on this same machine -- for the "matches"
# cases, and a platform string nothing will ever run under for "does not
# match".
_NO_SUCH_PLATFORM = "not-a-real-platform-430"

# #719: the exact startup failure a `pytester` child prints when it cannot
# import pytest under its relocated `HOME`. Matched loosely enough to survive
# a Python release quoting the module name differently -- 3.9 and 3.12, both
# checked directly against this machine, print it unquoted, but nothing here
# is willing to bet the next release keeps it that way.
_CHILD_COULD_NOT_IMPORT_PYTEST = re.compile(r"No module named ['\"]?pytest['\"]?")


def _child_could_not_run(result):
    """`None`, or the stderr line proving `result` measures nothing.

    Two facts distinguish "the child never started a pytest session" from
    "the child ran one and it came back TESTS_FAILED", and both are checked
    -- not the message text alone, which is one interpreter release away from
    drifting, and not the empty stdout alone, since nothing here has reason
    to believe that is unique to this one failure:

    - a pytest session that actually starts always writes at least a header
      line to stdout, pass or fail; a child that died on import writes none.
    - the surviving stderr line names the exact failure #719 measured.
    """
    if result.outlines:
        return None
    for line in result.errlines:
        if _CHILD_COULD_NOT_IMPORT_PYTEST.search(line):
            return line
    return None


def _run(pytester):
    """`pytester.runpytest_subprocess()`, with #719's third state surfaced.

    Every case in this file goes through here rather than calling
    `runpytest_subprocess()` directly, so a harness that could not run
    SKIPS, loudly, naming what happened -- instead of six assertions about
    `must_assert_on` reading as failures of the plugin under test.
    """
    result = pytester.runpytest_subprocess()
    reason = _child_could_not_run(result)
    if reason is not None:
        pytest.skip(
            "the pytester child could not import pytest ({!r}) -- this "
            "measures nothing about must_assert_on, not a defect in it "
            "(#719)".format(reason)
        )
    return result


def test_a_marked_test_that_skips_on_the_matching_platform_fails_the_session(pytester):
    """Must-fire case: the exact regression #430 is about. A test promised
    (via the marker) to assert on this platform skips instead -- the session
    must come back red, not green.
    """
    pytester.makeconftest(_PLUGIN_SOURCE)
    pytester.makepyfile(
        test_probe="""
        import sys
        import pytest

        @pytest.mark.must_assert_on(sys.platform)
        def test_it():
            pytest.skip("pretend the mechanism vanished")
        """
    )
    result = _run(pytester)
    assert result.ret != 0
    result.stdout.re_match_lines([r".*must_assert_on.*1 test\(s\).*"])
    result.stdout.fnmatch_lines(["*test_probe.py::test_it*"])


def test_a_marked_test_that_asserts_normally_does_not_fail_the_session(pytester):
    """Must-not-fire control, same fixture shape: the marked test runs its
    real assertion and passes -- nothing here should turn a clean pass into
    a failure.
    """
    pytester.makeconftest(_PLUGIN_SOURCE)
    pytester.makepyfile(
        test_probe="""
        import sys
        import pytest

        @pytest.mark.must_assert_on(sys.platform)
        def test_it():
            assert 1 + 1 == 2
        """
    )
    result = _run(pytester)
    assert result.ret == 0
    assert "must_assert_on" not in "\n".join(result.outlines)


def test_a_marked_test_that_skips_on_a_different_platform_does_not_fail_the_session(pytester):
    """A skip is correct and permanent on a platform the marker does not
    name -- e.g. a POSIX leg with no Windows junction to measure. This must
    stay green: the check is not "any skip is a defect", it is "a skip on
    the ONE platform this test promised to assert on is a defect".
    """
    pytester.makeconftest(_PLUGIN_SOURCE)
    pytester.makepyfile(
        test_probe="""
        import pytest

        @pytest.mark.must_assert_on({!r})
        def test_it():
            pytest.skip("this platform has nothing to measure")
        """.format(_NO_SUCH_PLATFORM)
    )
    result = _run(pytester)
    assert result.ret == 0


def test_a_marker_with_no_positional_platform_argument_fails_collection(pytester):
    """Reviewer finding on this same round: `marker.args` is empty for both
    `@pytest.mark.must_assert_on()` (bare) and
    `@pytest.mark.must_assert_on(platform=sys.platform)` (keyword) -- either
    spelling made the old `if marker is None or not marker.args: continue`
    silently disable the check for that test, with no error anywhere. A
    malformed instance of a promise this plugin exists to hold to account
    must not itself go unheld: this must fail loudly, at collection, rather
    than being read as "no marker" and passed over in silence.
    """
    pytester.makeconftest(_PLUGIN_SOURCE)
    pytester.makepyfile(
        test_probe="""
        import pytest

        @pytest.mark.must_assert_on()
        def test_it():
            pytest.skip("this would have gone unnoticed before the fix")
        """
    )
    result = _run(pytester)
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*must_assert_on*requires one positional*"])


def test_a_marker_with_a_keyword_platform_argument_fails_collection(pytester):
    """Same defect, the other spelling: `platform=` as a keyword rather than
    positional. `marker.args` is empty either way.
    """
    pytester.makeconftest(_PLUGIN_SOURCE)
    pytester.makepyfile(
        test_probe="""
        import sys
        import pytest

        @pytest.mark.must_assert_on(platform=sys.platform)
        def test_it():
            pytest.skip("this would have gone unnoticed before the fix")
        """
    )
    result = _run(pytester)
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*must_assert_on*requires one positional*"])


def test_an_unmarked_skip_does_not_fail_the_session(pytester):
    """The suite this ships into has 180+ ordinary `pytest.skip()` calls with
    no marker at all -- every one of them a legitimate "this environment
    cannot answer the question" skip. None of them must be touched.
    """
    pytester.makeconftest(_PLUGIN_SOURCE)
    pytester.makepyfile(
        test_probe="""
        import pytest

        def test_it():
            pytest.skip("no capability here, and that is fine")
        """
    )
    result = _run(pytester)
    assert result.ret == 0


def test_a_child_that_could_not_import_pytest_is_skipped_not_asserted_on(pytester, monkeypatch):
    """Must-fire control for #719's own detection.

    `runpytest_subprocess()` is monkeypatched to hand back exactly the
    `RunResult` this machine produces when the child's relocated `HOME` has
    no pytest under it -- empty stdout, one stderr line reading "No module
    named pytest" -- rather than actually forcing that failure by relocating
    `HOME`. #719's own comment measured why that would not be portable: CI's
    pytest is venv-installed and stays importable regardless of `HOME`, so a
    test that tries to reproduce the failure via `HOME` alone would be green
    on the very machines this fix exists for and red only on a machine that
    already has the bug -- backwards for a regression test. Constructing the
    `RunResult` this machine actually measured tests the same detector
    deterministically everywhere.
    """
    monkeypatch.setattr(
        pytester,
        "runpytest_subprocess",
        lambda *a, **kw: pytest.RunResult(
            ret=1,
            outlines=[],
            errlines=["/usr/bin/python3: No module named pytest"],
            duration=0.05,
        ),
    )
    with pytest.raises(pytest.skip.Exception):
        _run(pytester)


def test_a_child_that_ran_normally_is_not_skipped(pytester, monkeypatch):
    """Must-not-fire control, same fixture shape: a `RunResult` carrying real
    pytest output -- pass or fail, it does not matter which -- must pass
    through `_run` unchanged. #719's detector must not turn an ordinary
    result into a skip.

    A bare `_run(pytester)` call that unexpectedly raised `pytest.skip.Exception`
    would report as SKIPPED here, not FAILED -- pytest does not distinguish
    "this test chose to skip" from "an exception of that one specific type
    propagated out of it", and a SKIPPED among six genuine skips from the cases
    above is exactly the silent result CLAUDE.md's own note on
    `pytest.raises(Exception)` and skips warns about one level up: nothing here
    is inside `pytest.raises`, so that note does not literally apply, but the
    same failure mode does -- a broken detector must FAIL this test, not
    quietly join the skip count. So the skip is caught explicitly and turned
    into a hard failure.
    """
    real_result = pytest.RunResult(
        ret=0,
        outlines=["collected 1 item", "test_probe.py::test_it PASSED", "1 passed in 0.01s"],
        errlines=[],
        duration=0.05,
    )
    monkeypatch.setattr(pytester, "runpytest_subprocess", lambda *a, **kw: real_result)
    try:
        outcome = _run(pytester)
    except pytest.skip.Exception as exc:
        pytest.fail("_run() skipped an ordinary result: {}".format(exc))
    assert outcome is real_result
