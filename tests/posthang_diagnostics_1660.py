"""#1660: dump every thread's stack if the process is still alive well after
pytest's own summary line -- the gap this issue found unaccounted for.

The `pytest (windows-latest, 3.12)` leg was cancelled twice, back to back, on the
same green commit: both runs report a full `N passed` summary, and then a
`KeyboardInterrupt` lands in the MAIN THREAD, blocked inside a `threading`
wait/join. HOW LONG the process was alive after that summary printed is not
established -- both runs were cut off by the job's own 20-minute cap before that
duration could be observed, so all that is known is that it is non-zero, not
that it is "several minutes" (an earlier draft of this fix claimed that and was
wrong: caught in review, since the ~300s of growth between #1658's and #1660's
own measured suite runtimes is pytest's OWN self-reported test-execution time,
not time spent after its summary line). Which thread is stuck, and for how long,
could not be determined from a static read of this repository (#1660's own
recon: no `faulthandler` use anywhere in the tree, `grep:faulthandler:.`
returned zero hits). This module is the issue's own "what would settle it" ask:
arm a periodic stack dump once a session has finished, so a recurrence leaves a
real answer in the CI log instead of only a bare `KeyboardInterrupt` traceback.

Deliberately `exit=False`: this is a diagnostic, not a second timeout. The job's
own `timeout-minutes` (`.github/workflows/tests.yml`) stays the real backstop:
this only makes the CI log say WHERE the process was stuck when that backstop
(or a human reading the log before it fires) catches it.

Silent on every normal run, REASONED rather than observed: `pytest_sessionfinish`
arms the timer but nothing here ever cancels it, so it only speaks if the process
is still alive POST_SESSION_DUMP_AFTER_SECONDS after its own session finished.
Every leg measured before #1660's own two cancellations exited well inside the
ORIGINAL 60s window -- but this is reasoned from ordinary process-exit behaviour,
not measured per-leg on every OS/interpreter combination this repository runs;
a leg with genuinely slow (but not hung) teardown could still see a stray dump
in its log, which is log noise, not a failure (nothing here reads or gates on
stderr). That reasoning has NOT been re-verified against the tighter 15s window
this module now uses (a third occurrence, after this file first shipped, showed
60s itself was too slow -- see the constant's own comment below): whether every
leg's own post-summary teardown genuinely finishes inside 15s, on every
OS/interpreter this repository runs, is unmeasured, so a stray dump becoming
more common on a legitimately-just-slow leg is a real, accepted possibility
here, not a claim that 15s carries the same margin 60s did.

Runs once per pytest session -- once per `-n auto` worker AND once for the
controller, since each loads `tests/conftest.py` (and therefore this plugin)
independently. Confirmed to load and not error under a real
`-n 2 --dist loadfile` invocation of this repository's own suite; NOT confirmed
against the specific failure shape this issue reports -- a worker process's
raw `stderr` write, from a background watchdog thread, arriving in the
Windows-runner's own captured job log after that worker has already reported
completion to the controller over its execnet channel. If xdist's own output
forwarding does not carry a worker's post-report `stderr` through, this
diagnostic could be silent for a worker-level hang specifically, and only
useful for a controller-level one -- REASONED, not observed on Windows+xdist.

Registered as a pytest plugin via `pytest_plugins` in the top-level
`tests/conftest.py`, matching `must_assert_plugin`/`duration_report_plugin`/
`root_scratch_guard`'s own registration shape in that same file.

#1671's own addition: `pytest_sessionfinish` above fires in every process
that loads this plugin, worker and controller alike, but a worker's dump
only ever reaches the job's own captured log via xdist's own forwarding of
that worker's `stderr` over its execnet channel, while the controller
writes to that log directly. The 2026-09-18 recurrence (job
#105500444279) showed both `-n auto` WORKER processes dumping identically
and repeatedly, idle in `gateway_base.py:534 read`, waiting on the
controller to send them either a test or a shutdown -- and NO controller
dump anywhere in that same 1414-line log. If the controller is what is
actually stuck, and stuck somewhere OTHER than its own post-summary
`pytest_sessionfinish` teardown -- e.g. still dispatching work, still
collecting worker reports, or in its own shutdown sequence -- the
sessionfinish-armed timer above never gets a chance to run there at all:
it only arms once the controller itself reaches that hook, and a
controller wedged before reaching it leaves no diagnostic of its own in
the log, exactly what was observed. `pytest_configure` below arms a
SECOND, controller-only timer at process start instead of at session
finish, so the watchdog covers the controller's entire lifetime rather
than only its post-summary teardown -- REASONED to close the gap the
2026-09-18 recurrence's log showed, NOT yet observed to actually catch a
controller-side hang, since no recurrence has been measured since this
was added.

Caught in this same diff's own self-review, so recorded rather than left
implicit: `pytest_configure` fires when the pytest PROCESS starts, which
is not the same point in the JOB's own wall clock as the job's own start
-- `timeout-minutes` counts from there, and checkout/setup-python/install
all happen, as separate steps, before pytest ever runs. This timer's own
constant (`CONTROLLER_DUMP_AFTER_SECONDS` below) is calibrated against
pytest's OWN internal clock, not the job's, so its real margin against the
job's cap is NOT the comfortable one an earlier draft of this docstring
claimed -- see that constant's own comment for the honest accounting.

Python 3.9 compatible (`faulthandler.dump_traceback_later` has shipped since 3.3).
"""

import faulthandler
import sys

#: Seconds after a session finishes (i.e. right around when pytest's own
#: "N passed" summary is printed) before the first stack dump fires, repeating
#: at the same interval until the process actually exits.
#:
#: Was 60, chosen against a claim -- "well below the ~10 minutes of margin the
#: NEW 30-minute cap leaves" -- that #1660's own THIRD occurrence falsified
#: before this module had ever fired once: job #105442284149 (commit
#: `c201a8a0`) printed its summary at 1773.10s against the by-then-raised
#: 30-minute (1800s) cap, a margin of only 26.9s. A 60s delay is not "well
#: below" a 26.9s margin, it is 33.1s PAST it -- the diagnostic added
#: specifically to explain a recurrence was, on its first real recurrence,
#: mathematically incapable of ever firing, which is the whole explanation for
#: why that job's 1414-line log carried no `faulthandler` output at all.
#:
#: 15 is chosen to sit comfortably under every margin observed so far (~24s,
#: ~24s, ~26.9s across three occurrences at two different cap values) while
#: staying well above how long an ordinary session's own post-summary teardown
#: is reasoned to take (not measured per-leg on every OS/interpreter this
#: repository runs -- see the module docstring's own caveat on that). If a
#: FOURTH occurrence is measured, `tests/test_pytest_leg_timeout_1658.py`'s
#: `OBSERVED_WORST_CASE_SUITE_MINUTES` has to be updated to it by hand, same as
#: the first three times -- this constant is not read from a live CI
#: measurement. `test_dump_delay_fits_inside_the_jobs_own_margin` in
#: `tests/test_posthang_diagnostics_1660.py` only catches THIS delay going
#: stale against WHATEVER `OBSERVED_WORST_CASE_SUITE_MINUTES` says at the time
#: -- it is a coupling check between two hand-maintained constants, not an
#: independent measurement, and it cannot notice a real-world margin eroding
#: further until that constant is updated to reflect it.
POST_SESSION_DUMP_AFTER_SECONDS = 15


def pytest_sessionfinish(session, exitstatus):
    """Arm a repeating stack dump; nothing here ever cancels it on purpose --
    a process that exits normally within POST_SESSION_DUMP_AFTER_SECONDS never
    lets it fire, so an ordinary run is untouched."""
    faulthandler.dump_traceback_later(
        POST_SESSION_DUMP_AFTER_SECONDS, repeat=True, file=sys.stderr, exit=False
    )


#: Seconds after the CONTROLLER process starts (`pytest_configure`, not
#: `pytest_sessionfinish`) before its own first stack dump fires, repeating
#: at the same interval until the process actually exits.
#:
#: NOT the same absolute point in the job's wall clock that the worker-side
#: POST_SESSION_DUMP_AFTER_SECONDS timer targets -- an earlier draft of this
#: comment claimed that and was wrong, caught in this diff's own self-review.
#: `pytest_configure` fires when the `pytest` PROCESS starts, which is
#: already some way into the JOB's own wall clock: `timeout-minutes` counts
#: from job start, and `actions/checkout` / `actions/setup-python` / the
#: dependency install all run, as separate steps, BEFORE the "Run tests"
#: step ever invokes pytest. OBSERVED_WORST_CASE_SUITE_MINUTES (1773.10s,
#: `tests/test_pytest_leg_timeout_1658.py`) is pytest's OWN self-reported
#: elapsed time -- i.e. measured from close to this same `pytest_configure`
#: to `pytest_sessionfinish` -- so the ~26.9s gap between that figure and the
#: job's 1800s cap is the TOTAL slack left over for everything pytest's own
#: clock does not cover: checkout/setup/install BEFORE pytest starts, and
#: teardown/cancellation-handling AFTER it finishes, combined. How that ~27s
#: splits between the two halves is NOT measured. This constant therefore
#: carries a real, unquantified risk this diagnostic accepts rather than
#: hides: if checkout+setup+install alone take longer than
#: `1800 - CONTROLLER_DUMP_AFTER_SECONDS` seconds, this timer fires AFTER
#: the job's own cap has already killed the process, reproducing -- for the
#: controller specifically -- the exact "diagnostic mathematically incapable
#: of firing" failure #1660's own original 60s choice suffered for the
#: worker-side timer. Set close to OBSERVED_WORST_CASE_SUITE_MINUTES*60
#: (only +7s, deliberately smaller than POST_SESSION_DUMP_AFTER_SECONDS's
#: own +15s) specifically to leave as much of that ~27s of total slack as
#: possible for the unmeasured pre-pytest half, at the cost of a smaller
#: buffer above a normal green run's own worst-case duration (so a stray
#: controller dump on an ordinary run is a somewhat more real possibility
#: here than on the worker-side timer -- the same class of accepted
#: tradeoff POST_SESSION_DUMP_AFTER_SECONDS's own comment already names for
#: itself). Hand-maintained, same as POST_SESSION_DUMP_AFTER_SECONDS above
#: and for the same reason: not read from a live CI measurement, and
#: `test_controller_dump_delay_fits_inside_the_jobs_own_margin` in
#: `tests/test_posthang_diagnostics_1660.py` only catches this value going
#: stale against whatever the two constants it is derived from currently
#: say -- it cannot measure, and does not claim to measure, the real
#: pre-pytest overhead this constant is silent about.
CONTROLLER_DUMP_AFTER_SECONDS = 1780


def _is_xdist_worker(config):
    """True inside a worker's own process config, never inside the controller's.

    Mirrors `tests/root_scratch_guard.py`'s own `_is_xdist_worker` (there
    keyed off `session.config`; here off `config` directly, since
    `pytest_configure` receives the config itself, not a session) -- xdist
    sets `workerinput` only on a worker's own `Config`, never on the
    controller's and never on a plain non-xdist run's, so this needs no
    import of `xdist` itself (which may not even be installed when this
    suite runs without `-n auto`, e.g. a contributor's own
    `python3 -m pytest tests/ -q`).
    """
    return getattr(config, "workerinput", None) is not None


def pytest_configure(config):
    """Arm a second, controller-only watchdog at process start (#1671).

    `pytest_sessionfinish` above fires in every process that loads this
    plugin, but it only ARMS once that process reaches its own session
    finish -- a controller wedged somewhere earlier (still dispatching
    work, still collecting worker reports, or its own shutdown sequence)
    never reaches that hook at all, so the sessionfinish-based timer alone
    would leave that controller with no diagnostic of its own in the log,
    which is exactly what the 2026-09-18 recurrence's log showed: both
    workers dumping, idle, waiting on the controller; no controller dump
    anywhere. Arming here instead starts the clock at process start,
    covering the controller's entire lifetime rather than only its
    post-summary teardown.

    Controller-only, deliberately: a worker already gets its own watchdog
    from `pytest_sessionfinish`, armed relative to when IT finishes, which
    is what matters for a worker since a worker's whole life is running
    tests. Arming this same early, coarse timer in every worker too would
    add CONTROLLER_DUMP_AFTER_SECONDS-scale redundant timers there for no
    diagnostic gain the sessionfinish-based one does not already give.
    """
    if _is_xdist_worker(config):
        return
    faulthandler.dump_traceback_later(
        CONTROLLER_DUMP_AFTER_SECONDS, repeat=True, file=sys.stderr, exit=False
    )
