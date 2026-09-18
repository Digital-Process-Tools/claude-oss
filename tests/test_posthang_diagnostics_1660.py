"""Tests for tests/posthang_diagnostics_1660.py.

Python 3.9 compatible.
"""

import sys

import posthang_diagnostics_1660 as phd


def test_pytest_sessionfinish_arms_a_repeating_stack_dump(monkeypatch):
    """The hook must arm faulthandler's own periodic dump, not merely import it.

    A hook that is registered but never calls the real function would pass any
    test that only checks the module imports cleanly -- this asserts the actual
    call and its arguments, mocked so the real suite process never gets a timer
    armed against it by its own test run.
    """
    calls = []

    def fake_dump_traceback_later(timeout, repeat=False, file=None, exit=False):
        calls.append((timeout, repeat, file, exit))

    monkeypatch.setattr(
        phd.faulthandler, "dump_traceback_later", fake_dump_traceback_later
    )

    phd.pytest_sessionfinish(session=None, exitstatus=0)

    assert calls == [(phd.POST_SESSION_DUMP_AFTER_SECONDS, True, sys.stderr, False)]


def test_it_never_asks_faulthandler_to_exit_the_process():
    """`exit=True` would os._exit(1) after dumping -- a diagnostic that kills the
    job is worse than the hang it is meant to explain; the job's own
    `timeout-minutes` is still the real backstop."""
    import inspect

    source = inspect.getsource(phd.pytest_sessionfinish)
    assert "exit=False" in source, (
        "pytest_sessionfinish must pass exit=False to dump_traceback_later, or "
        "the diagnostic itself would terminate the process"
    )
