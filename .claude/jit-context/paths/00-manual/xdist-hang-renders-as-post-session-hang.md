---
title: "A test hung under pytest -n auto renders exactly like a post-session hang -- and durations can't see it"
description: "Four issues read the same Windows CI cancellation as a post-session hang across fourteen consecutive runs, because nothing in the log said which test was running. faulthandler_timeout settled it in one run; --durations never would have."
match: (^|/)tests/|(^|/)\.github/workflows/tests\.yml$
---

**A `[ 99%]` line with no `[100%]` after it means the suite did not finish, whatever the summary
line says.** Four issues (#1658, #1660, #1671, #1673) each read the same shape -- progress stalled
at 99%, idle worker stacks dumping every 15s, a final `N passed in 1770s` printed by pytest's own
`KeyboardInterrupt` handler at the job cap -- as a hang *after* the session ended, and built two
watchdogs and a per-step timing script before anything measured the right thing.

**`--durations` only lists tests that reported; a hang is invisible there by construction.** The
summed per-test time matched a green run to within a few percent, because the stuck test never
finished and so never contributed a duration at all.

**What actually settles it: `-o faulthandler_timeout=180` on the pytest command line.** pytest's
built-in faulthandler plugin dumps the stack of any test still running after N seconds, with that
test's own file and line -- this is what named the real culprit (`<frozen os>:1066 fdopen`, called
from a specific test file and line) in one run, after days of the wrong mechanism. Permanent in
`.github/workflows/tests.yml` now; add it first when a suite goes red with no clear failing test.

**The underlying cause here, if it recurs elsewhere: never probe a low-numbered fd to learn whether
a caller set something up.** Under an execnet worker on Windows, fd 3 is one of execnet's own live
descriptors -- `os.fdopen(3, ...)` on it blocks forever rather than raising. Detail and the fix
(opt-in `--progress-fd`) live in `windows-subprocess-resolution.md`, which governs the file this
happened in.

Routed via /oss:curate from `trap.d/1673.a-hung-test-renders-as-a-post-session-hang-under-xdist.md`.
