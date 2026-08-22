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
"""

import sys
from pathlib import Path

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
    result = pytester.runpytest_subprocess()
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
    result = pytester.runpytest_subprocess()
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
    result = pytester.runpytest_subprocess()
    assert result.ret == 0


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
    result = pytester.runpytest_subprocess()
    assert result.ret == 0
