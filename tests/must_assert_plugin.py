"""The `must_assert_on` pytest marker and the check that reads it -- #430.

#265 spent four rounds and a real Windows CI failure moving three claims about
a Windows-only mechanism from *reasoned* to *observed*. Nothing here would
notice if a future runner image, Python version or Windows policy took the
mechanism away again: a test that is EXPECTED to assert on a given platform
can start SKIPPING there instead, and a skip does not fail a build. `-rs`
prints the reason, but nothing is obliged to read it, so the regression is
invisible in the one place CI is actually watched -- the green checkmark.

`@pytest.mark.must_assert_on("win32")` on a test is a promise: on that
platform, this test must run its real assertion, never skip. This module is
the pytest plugin that holds that promise to account -- it fails the WHOLE
session (nonzero exit) if any marked test reports SKIPPED while
`sys.platform` matches the platform the marker names.

Deliberately on the test, not in the workflow: the fact "this test must
assert on platform X" lives beside the test it describes, in one file, so
there is nothing for a CI-side list of test IDs to go stale against. It also
runs everywhere pytest runs -- a contributor's own machine included -- not
only inside a named CI step, so the earliest possible signal is a local run
on the matching platform.

A test whose skip is CORRECT and PERMANENT on a platform (a POSIX leg has no
Windows junction to measure) is untouched: the marker names the ONE platform
the test must assert on, so this check is silent everywhere else by
construction -- it does not, and structurally cannot, treat every skip as a
defect.

Registered as a pytest plugin via `pytest_plugins` in the top-level
`tests/conftest.py`, so `pytest_configure`/`pytest_runtest_logreport`/
`pytest_sessionfinish` below run for every collection this suite performs.
`tests/test_must_assert_on_430.py` drives this same module, unmodified, as a
subprocess conftest via the `pytester` fixture -- the only way to observe
session-level exit-code behaviour rather than a single test's outcome.
"""

import sys

import pytest

MARKER_NAME = "must_assert_on"

_skipped_nodeids = set()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "{}(platform): this test must assert for real (never SKIP) whenever "
        "sys.platform == platform; the whole session fails if it skips there "
        "anyway (#430)".format(MARKER_NAME),
    )


def pytest_collection_modifyitems(config, items):
    # A reviewer finding on this same round: `marker.args` is empty for both
    # a bare `@pytest.mark.must_assert_on()` and a keyword
    # `@pytest.mark.must_assert_on(platform="win32")` -- either spelling made
    # the session-finish check below read it as "no marker" and silently
    # pass the test over, which is the exact failure mode this plugin exists
    # to catch, moved one layer up into its own configuration surface. A
    # malformed instance of the promise is refused loudly, at collection,
    # rather than treated as absent.
    for item in items:
        marker = item.get_closest_marker(MARKER_NAME)
        if marker is None:
            continue
        if not marker.args:
            raise pytest.UsageError(
                "{}: {}(...) requires one positional platform argument (e.g. "
                "'win32'), given as `sys.platform` would give it -- a keyword "
                "argument or a bare marker is silently ignored instead of "
                "checked, which is the exact defect #430 exists to catch "
                "(#430)".format(item.nodeid, MARKER_NAME)
            )


def pytest_runtest_logreport(report):
    # `pytest.skip()` called in a fixture/setup reports skipped at the
    # "setup" phase and the test body ("call") never runs; skip.skip() from
    # inside the test body itself reports skipped at "call". Either is a
    # skip of the test, so both phases are tracked.
    if report.skipped and report.when in ("setup", "call"):
        _skipped_nodeids.add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    offenders = []
    for item in session.items:
        marker = item.get_closest_marker(MARKER_NAME)
        if marker is None or not marker.args:
            continue
        platform_name = marker.args[0]
        if sys.platform != platform_name:
            continue
        if item.nodeid in _skipped_nodeids:
            offenders.append(item.nodeid)
    if not offenders:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    message = (
        "must_assert_on: {} test(s) marked to assert on {} SKIPPED here "
        "instead -- a skip does not fail a build, so this session is failed "
        "in its place (#430)".format(len(offenders), sys.platform)
    )
    if reporter is not None:
        reporter.write_sep("=", message, red=True)
        for nodeid in offenders:
            reporter.write_line("  {}".format(nodeid))
    else:
        sys.stderr.write(message + "\n" + "\n".join(offenders) + "\n")
    session.exitstatus = 1
