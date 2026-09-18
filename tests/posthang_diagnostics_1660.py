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
Every leg measured before #1660's own two cancellations exited well inside that
window -- but this is reasoned from ordinary process-exit behaviour, not measured
per-leg on every OS/interpreter combination this repository runs; a leg with
genuinely slow (but not hung) teardown could still see a stray dump in its log,
which is log noise, not a failure (nothing here reads or gates on stderr).

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

Python 3.9 compatible (`faulthandler.dump_traceback_later` has shipped since 3.3).
"""

import faulthandler
import sys

#: Seconds after a session finishes (i.e. right around when pytest's own
#: "N passed" summary is printed) before the first stack dump fires, repeating
#: at the same interval until the process actually exits. Chosen well above the
#: ~24s of job-wall-clock margin #1660 measured left under the OLD 20-minute cap
#: (so an ordinary run's own teardown, however it compares to that margin, does
#: not trip this), and well below the ~10 minutes of margin the NEW 30-minute
#: cap leaves over the current worst-case suite runtime, so several samples are
#: still possible before that cap fires on a genuine hang.
POST_SESSION_DUMP_AFTER_SECONDS = 60


def pytest_sessionfinish(session, exitstatus):
    """Arm a repeating stack dump; nothing here ever cancels it on purpose --
    a process that exits normally within POST_SESSION_DUMP_AFTER_SECONDS never
    lets it fire, so an ordinary run is untouched."""
    faulthandler.dump_traceback_later(
        POST_SESSION_DUMP_AFTER_SECONDS, repeat=True, file=sys.stderr, exit=False
    )
