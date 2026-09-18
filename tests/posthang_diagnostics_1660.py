"""#1660: dump every thread's stack if the process is still alive well after
pytest's own summary line -- the gap this issue found unaccounted for.

The `pytest (windows-latest, 3.12)` leg was cancelled twice, back to back, on the
same green commit: both runs report a full `N passed` summary, and then a
`KeyboardInterrupt` lands in the MAIN THREAD, blocked inside a `threading`
wait/join, roughly five minutes later -- something is not exiting once pytest
itself is done, and which thread that is could not be determined from a static
read of this repository (#1660's own recon: no `faulthandler` use anywhere in the
tree, `grep:faulthandler:.` returned zero hits). This module is the issue's own
"what would settle it" ask: arm a periodic stack dump once a session has
finished, so a recurrence leaves a real answer in the CI log instead of only a
bare `KeyboardInterrupt` traceback.

Deliberately `exit=False`: this is a diagnostic, not a second timeout. The job's
own `timeout-minutes` (`.github/workflows/tests.yml`) stays the real backstop:
this only makes the CI log say WHERE the process was stuck when that backstop
(or a human reading the log before it fires) catches it.

Silent on every normal run: `pytest_sessionfinish` arms the timer but nothing
here ever cancels it -- if the process exits normally, which it does on every
green run measured before #1660's own two cancellations, the timer never fires
and this produces zero output. It only speaks when there IS a gap this large.

Runs once per pytest session -- once per `-n auto` worker AND once for the
controller, since each loads `tests/conftest.py` (and therefore this plugin)
independently, which is a feature here: a worker-level hang gets its own dump
without needing the controller to notice anything is wrong.

Registered as a pytest plugin via `pytest_plugins` in the top-level
`tests/conftest.py`, matching `must_assert_plugin`/`duration_report_plugin`/
`root_scratch_guard`'s own registration shape in that same file.

Python 3.9 compatible (`faulthandler.dump_traceback_later` has shipped since 3.3).
"""

import faulthandler
import sys

#: Seconds after a session finishes (i.e. right around when pytest's own
#: "N passed" summary is printed) before the first stack dump fires, repeating
#: at the same interval until the process actually exits. Short enough that a
#: five-minute gap (#1660's own measurement) yields several samples before the
#: job's own `timeout-minutes` cap kills it; long enough that it never fires on
#: an ordinary run, where session-finish-to-process-exit is a matter of seconds.
POST_SESSION_DUMP_AFTER_SECONDS = 60


def pytest_sessionfinish(session, exitstatus):
    """Arm a repeating stack dump; nothing here ever cancels it on purpose --
    a process that exits normally within POST_SESSION_DUMP_AFTER_SECONDS never
    lets it fire, so an ordinary run is untouched."""
    faulthandler.dump_traceback_later(
        POST_SESSION_DUMP_AFTER_SECONDS, repeat=True, file=sys.stderr, exit=False
    )
