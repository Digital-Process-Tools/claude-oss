"""#1228: extend #1214's root-level scratch-artifact detector to run for
the WHOLE suite, not just around the two known nested-pytest stub runs.

## Scope, stated explicitly rather than left implicit

`tests/test_root_scratch_isolation_1214.py`'s own `_RootWatcher` already
solves a NARROWER version of this: it watches the repository root's direct
children, with a must-fire positive control, but only while the two known
stub runs (`test_durations_recorded_881.py`, `test_duration_report_
plugin_910.py`) execute. This module generalises that same read-only
mechanism to the whole session -- the issue's original, narrower ask
(#1228's own "Shape of a fix, not a prescription" section) -- and
deliberately declines the harder generalization from the issue's own
comment thread (2026-09-07): "any path inside the checkout that is shared
between concurrent workers and written, created or removed during a run".
That covers the tracked-source-directory race (`skills/manager/phases/
undeclared-control.md`, #1228's own "site 3") and the pre-existing shared
file race (`.coverage`, #1228's own "site 4") this issue's comments
document. Site 4 has a direct fix instead --
`tests/test_durations_recorded_881.py`'s own nested pytest invocation now
passes `--no-cov`, so it never touches the shared `.coverage` file at all
(see that file's own new tests). Site 3, and the general "any shared path"
case, are a harder design problem than one lane should decide under time
pressure -- see this issue's own report for the follow-up filed for it.

## Two design decisions this module states rather than leaves to be
## re-derived by whoever reads it next

1. **Read-only, always.** This watcher only ever calls `Path.iterdir()`.
   It never writes, deletes or renames anything at the repository root --
   the exact defect class #1225's own self-review caught in an earlier
   version of a different fix that verified a flag by deleting the shared
   `.pytest_cache` directory (this issue's own first stated constraint).

2. **Controller-only, not per-worker.** Under `-n auto --dist loadfile`
   every xdist worker process also runs `pytest_sessionstart`/
   `pytest_sessionfinish`. N workers each independently watching the same
   shared root would each need to tell a real sibling's legitimate
   artifact apart from an unexpected one -- N copies of the exact
   allowlist problem this module exists to keep small. The controller
   process (or the only process, when xdist is not in play at all) sees
   the same filesystem every worker writes to, on the same machine, so one
   watcher on the controller sees everything N per-worker watchers would,
   with one allowlist instead of N. `_is_xdist_worker()` below is the
   check: xdist sets `session.config.workerinput` on a worker's own
   config and nowhere else, so this needs no import of `xdist` itself
   (which may not be installed at all when this suite runs without
   `-n auto`, e.g. a contributor's own `python3 -m pytest tests/ -q`).

## Why this never depends on `.coverage`'s own liveness

The 4th and 5th firings logged on this issue both killed `_RootWatcher`'s
own probe indirectly, by killing the NESTED pytest subprocess it was
watching (via the very `.coverage` race site 4 names) -- the guard for
this class was being killed by the class it guards against. This module
spawns no subprocess and reads no coverage data; it only lists the root
directory's own direct children on a plain background thread, so it
cannot be taken out by the same race it exists to detect. If `iterdir()`
itself ever raises (a genuinely unreadable root, which would be its own
much larger problem), the poll loop skips that tick rather than raising --
consistent with `_RootWatcher`'s own `except OSError: pass` a few lines
away in the sibling module.
"""

import fnmatch
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Root-level entries a real CI run legitimately creates or touches, and
# which this guard must never treat as a scratch artifact a test forgot to
# clean up. Kept intentionally short: #1214's own fixes moved every known
# nested-pytest scratch site off the shared root entirely, so growth here
# should be rare, and each addition should be a real, named, understood
# multi-worker artifact rather than a guess.
_ALLOWLIST_EXACT = frozenset({".coverage", ".pytest_cache"})
_ALLOWLIST_GLOBS = (
    # coverage.py / pytest-cov per-worker data files under xdist, combined
    # into `.coverage` at session finish; briefly present, sometimes still
    # present if the combine step has not run yet when this checks.
    ".coverage.*",
)


def _is_allowed(name):
    if name in _ALLOWLIST_EXACT:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in _ALLOWLIST_GLOBS)


class _SessionRootWatcher(object):
    """Background, read-only poller over `root`'s own direct children.

    Same mechanism as `tests/test_root_scratch_isolation_1214.py`'s own
    `_RootWatcher` (continuous polling, not a before/after snapshot, so a
    name that appears and vanishes between polls is still seen) --
    generalised to run for a whole pytest session's lifetime rather than
    around one known call, and filtered through the allowlist above.
    """

    def __init__(self, root):
        self.root = root
        try:
            self._baseline = set(p.name for p in root.iterdir())
        except OSError:
            self._baseline = set()
        self._seen_new = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)

    def _poll(self):
        while not self._stop.is_set():
            try:
                for p in self.root.iterdir():
                    if p.name not in self._baseline:
                        self._seen_new.add(p.name)
            except OSError:
                pass
            time.sleep(0.005)

    def offenders(self):
        """Every name seen new during the run that the allowlist does not
        excuse -- sorted, for a deterministic report."""
        return sorted(name for name in self._seen_new if not _is_allowed(name))


_watcher = None


def _is_xdist_worker(session):
    """True on an xdist worker's own config, false on the controller (or
    the only process, when xdist is not driving this run at all)."""
    return getattr(session.config, "workerinput", None) is not None


def pytest_sessionstart(session):
    global _watcher
    if _is_xdist_worker(session):
        return
    _watcher = _SessionRootWatcher(REPO_ROOT)
    _watcher.start()


def pytest_sessionfinish(session, exitstatus):
    global _watcher
    if _watcher is None:
        return
    _watcher.stop()
    offenders = _watcher.offenders()
    _watcher = None
    if not offenders:
        return
    message = (
        "root_scratch_guard: {} unexpected entr{} appeared directly under "
        "the repository root during this run: {} -- a third #1214 site, "
        "the class #1228 exists to catch before it reddens CI as an "
        "unrelated, misattributed failure".format(
            len(offenders),
            "y" if len(offenders) == 1 else "ies",
            ", ".join(offenders),
        )
    )
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", message, red=True)
        for name in offenders:
            reporter.write_line("  " + name)
    else:
        sys.stderr.write(message + "\n" + "\n".join(offenders) + "\n")
    session.exitstatus = 1
