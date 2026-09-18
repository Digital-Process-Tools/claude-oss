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


def test_pytest_configure_arms_controller_watchdog_when_not_a_worker(monkeypatch):
    """#1671: the controller must arm its own watchdog too, and early.

    A worker's `pytest_sessionfinish` dump (above) is armed relative to when
    IT finishes, then forwarded to the controller's own captured job log.
    But the 2026-09-18 recurrence showed both workers idle, waiting on the
    controller, with NO controller dump anywhere in that same log -- so if
    the controller is stuck somewhere other than its own post-summary
    teardown, the sessionfinish-armed timer never gets a chance to run
    there at all. `pytest_configure` arms a second, controller-only timer
    at process start instead, covering the controller's whole lifetime.

    A plain object with no `workerinput` attribute stands in for the
    controller's own `Config`, exactly like a non-xdist run's `Config` --
    xdist sets `workerinput` only on a worker's.
    """
    calls = []

    def fake_dump_traceback_later(timeout, repeat=False, file=None, exit=False):
        calls.append((timeout, repeat, file, exit))

    monkeypatch.setattr(
        phd.faulthandler, "dump_traceback_later", fake_dump_traceback_later
    )

    class FakeControllerConfig:
        pass

    phd.pytest_configure(FakeControllerConfig())

    assert calls == [(phd.CONTROLLER_DUMP_AFTER_SECONDS, True, sys.stderr, False)]


def test_pytest_configure_does_not_arm_for_an_xdist_worker(monkeypatch):
    """The positive control's pair: a worker must NOT get this second timer.

    A worker already gets its own watchdog from `pytest_sessionfinish`,
    armed relative to when it finishes -- which is what matters for a
    worker, since a worker's whole life is running tests. Arming this
    early timer there too would just be a redundant second timer with no
    diagnostic gain. Without this test, a helper that always returns
    `True` (or one that is never actually called) would make the sibling
    test above pass for the wrong reason -- this is the "must not fire"
    half CLAUDE.md's own negative-assertion rule requires.
    """
    calls = []

    def fake_dump_traceback_later(timeout, repeat=False, file=None, exit=False):
        calls.append((timeout, repeat, file, exit))

    monkeypatch.setattr(
        phd.faulthandler, "dump_traceback_later", fake_dump_traceback_later
    )

    class FakeWorkerConfig:
        workerinput = {"workerid": "gw0"}

    phd.pytest_configure(FakeWorkerConfig())

    assert calls == []


@needs_yaml
def test_controller_dump_delay_fits_inside_the_jobs_own_margin():
    """The controller-only timer must fire strictly before the job's own cap,
    and strictly after the suite's own observed worst-case runtime -- else it
    either never gets a chance to dump (killed by the cap first, #1660's own
    original bug) or fires spuriously on every green run (armed tighter than
    the suite itself normally takes).
    """
    job = _pytest_job()
    cap_minutes = job.get("timeout-minutes")
    assert isinstance(cap_minutes, int), "timeout-minutes is not an int: {!r}".format(
        cap_minutes
    )
    cap_seconds = cap_minutes * 60
    worst_case_seconds = OBSERVED_WORST_CASE_SUITE_MINUTES * 60
    assert phd.CONTROLLER_DUMP_AFTER_SECONDS > worst_case_seconds, (
        "posthang_diagnostics_1660.CONTROLLER_DUMP_AFTER_SECONDS ({!r}s) is not "
        "greater than the observed worst-case suite runtime ({:.1f}s) -- the "
        "controller's own watchdog would fire on every ordinary green run, not "
        "only on a real hang".format(
            phd.CONTROLLER_DUMP_AFTER_SECONDS, worst_case_seconds
        )
    )
    assert phd.CONTROLLER_DUMP_AFTER_SECONDS < cap_seconds, (
        "posthang_diagnostics_1660.CONTROLLER_DUMP_AFTER_SECONDS ({!r}s) is not "
        "less than the job's own timeout-minutes cap ({:.1f}s) -- the "
        "controller's own watchdog would be killed by the job's cap before it "
        "ever gets a chance to dump a stack, exactly the #1660 recurrence this "
        "module exists to explain".format(
            phd.CONTROLLER_DUMP_AFTER_SECONDS, cap_seconds
        )
    )


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
