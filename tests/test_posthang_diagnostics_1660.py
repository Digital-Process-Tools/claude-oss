"""Tests for tests/posthang_diagnostics_1660.py.

Python 3.9 compatible.
"""

import sys

import posthang_diagnostics_1660 as phd

from test_pytest_leg_timeout_1658 import (  # noqa: E402
    OBSERVED_WORST_CASE_SUITE_MINUTES,
    needs_yaml,
    _pytest_job,
)


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

    # `exit=False` is asserted here, on the REAL call tuple, rather than by a
    # separate source-text search for the substring "exit=False" -- a string
    # match would also pass if that text sat in a comment or an unreachable
    # branch, so it is not a substitute for checking what was actually called
    # with what. `exit=True` would os._exit(1) after dumping -- a diagnostic
    # that kills the job is worse than the hang it is meant to explain; the
    # job's own `timeout-minutes` is still the real backstop.
    assert calls == [(phd.POST_SESSION_DUMP_AFTER_SECONDS, True, sys.stderr, False)]


@needs_yaml
def test_dump_delay_fits_inside_the_jobs_own_margin():
    """#1660's own recurrence, reported after this diagnostic first shipped: the
    `pytest (windows-latest, 3.12)` job was cancelled a THIRD time (job
    #105442284149, commit `c201a8a0`), summary line `1773.10s (0:29:33)` against
    the (by-then-raised) 30-minute cap -- a margin of 1800 - 1773.10 = 26.9s. No
    `faulthandler` output appeared anywhere in that job's 1414-line log.

    That is not a mystery once the two numbers are compared: this module's own
    `POST_SESSION_DUMP_AFTER_SECONDS` was 60 at the time, so the first dump was
    never scheduled to fire until 60s after session-finish -- 33s AFTER the job's
    own cap already killed it. The diagnostic #1660 added specifically to explain
    a recurrence was, on its first real recurrence, structurally incapable of
    firing at all. This is not `cap > 0` (#303's weaker bound) and not `margin >=
    N minutes` (the now-falsified assumption `posthang_diagnostics_1660.py`
    itself used to pick 60): it is the one thing that actually matters for this
    diagnostic's own purpose -- that it gets scheduled to fire strictly before the
    job's own wall-clock cap can kill the process first.

    What this does NOT do, so it is not mistaken for more than it is: it compares
    two HAND-MAINTAINED constants (this delay, and
    `OBSERVED_WORST_CASE_SUITE_MINUTES` above), neither of which is read from a
    live CI measurement. It would have PASSED against the old 60s delay had
    `OBSERVED_WORST_CASE_SUITE_MINUTES` still held its pre-this-issue value
    (1176.55s -> margin 623.45s, comfortably clearing 60s) -- it only catches
    THIS delay going stale relative to whatever the OTHER constant currently
    says, which is exactly why that constant is updated in the same commit as
    this test. A fourth recurrence still needs a human to transcribe the new
    worst-case runtime into `OBSERVED_WORST_CASE_SUITE_MINUTES` before this test
    can say anything about it.
    """
    job = _pytest_job()
    cap_minutes = job.get("timeout-minutes")
    assert isinstance(cap_minutes, int), "timeout-minutes is not an int: {!r}".format(
        cap_minutes
    )
    margin_seconds = (cap_minutes * 60) - (OBSERVED_WORST_CASE_SUITE_MINUTES * 60)
    assert phd.POST_SESSION_DUMP_AFTER_SECONDS < margin_seconds, (
        "posthang_diagnostics_1660.POST_SESSION_DUMP_AFTER_SECONDS ({!r}s) is not "
        "less than the job's own margin over the observed worst-case suite "
        "runtime ({:.1f}s) -- the diagnostic would be killed by the job's own "
        "timeout-minutes cap before it ever gets a chance to dump a stack, "
        "exactly the #1660 recurrence this module exists to explain".format(
            phd.POST_SESSION_DUMP_AFTER_SECONDS, margin_seconds
        )
    )
