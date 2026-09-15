---
title: "Adding or changing a doctor check: two tests it has to pass first"
description: "A WARN no manual op and no scaffold run can clear is a bug in the check, not work for the maintainer. And the remedy has to be executable by the agent reading it, not only clickable by a human."
match: (^|/)(scripts/doctor(_check_[a-z0-9_]+)?\.(py|sh)|commands/doctor\.md)$
---

**What the diagnostic is for.** Report whether the plugin, the environment and the repository are
configured properly, give one overall status, and then help the human or the LLM **remove every
warning** -- by a manual op, or by `/oss:scaffold`. It performs no writes and gains no `--apply`:
naming the command is not running it, and the decision to run stays with the session.

Two tests, both from #1065.

**1. If nothing can clear it, the bug is in the check -- unless a clock clears it instead.** The
states are `OK` / `NOTICE` / `WAIT` / `WARN` / `FAIL`. `NOTICE` is reserved for a check that has
declared itself structurally unable to *ever* answer (#764). `WAIT` (#1440) is the third kind of
absence: the check ran, the reading is real, and it settles on its own -- a cache clock, a session
relaunch -- with no manual op and no scaffold run involved at all. There is no state for a WARN that
is simply wrong, so a false positive renders as work -- and in the worst case the work makes the
repository worse. #1062 is the measured instance: `CodeQL coverage` warns on a repository CodeQL
already scans through GitHub's default setup, and the workflow it asks for would displace the setup
already running. Its verdict is not *add the workflow*; it is *this check must not WARN here*. Apply
the test before adding a check, and to every existing one: no manual op, no scaffold run that clears
it, and no clock that clears it either -- WARN only when none of those three exist.

**2. The remedy has to be runnable, not only clickable.** `/oss:doctor` runs inside a session whose
agent is expected to clear what it reports. `Enable it from the repo's Settings > ... page (URL)` is
a sentence only a human can act on; the same finding cleared in one call as

    gh api -X PUT repos/<owner>/<repo>/automated-security-fixes

`gh` reaches every forge-side setting this diagnostic reports on, so that is the general shape of the
family, not a special case. Name the command where one exists; keep the settings URL as the fallback
where none does, and for the human who prefers it.

`doctor.py`'s own `owned_drift_summary` docstring states this split directly since #1065 shipped it
-- a per-line remedy belongs in `doctor.py`, the overall next step (`/oss:tick`) belongs in
`commands/doctor.md`. If you find yourself reading it as forbidding test 2 above, the docstring has
drifted again; fix it there rather than adding a second correction here.

Every check still owes its own third state -- `WARN ... could not be determined`, never folded into
either answer. A permission-limited read that cannot see a setting must not render as a setting
confirmed absent; `branch protection` already does this and is the model.

**Three concrete instances of test 1 above, all from doctor's own WAIT arm
(#1448, #1474):**

- **A `could-not-check` demoted to WAIT needs an actual clock to settle it,
  not just a readable install record.** `doctor_check_auto_update.py`
  answered only "is `installed_plugins.json` readable right now" and used
  that single fact to demote *every* `could-not-check` to WAIT. Three of
  the four `could-not-check` causes (marketplace refresh failed, every
  update call failed, an undeterminable opt-out) can have a perfectly
  readable install record and no clock coming to settle them -- a standing,
  actionable WARN prints as WAIT and never gets counted.
- **A dead sentinel makes a real WARN unreachable, permanently, with no
  trace.** `doctor_check_mcp_channel_connection.py`'s WAIT/WARN split used to
  read an env sentinel whose only writer had been removed by a later change
  as "dead, never read" -- true for that writer, false for this reader. The
  condition was always true, the WAIT arm always fired, the WARN arm (a real
  gap: something should have bound the socket and did not) was unreachable,
  and nothing anywhere recorded that this had happened. #1523 found the WAIT
  text was also making a false claim on its own terms and removed the arm
  entirely rather than re-wiring the dead sentinel -- `check_mcp_channel_
  connection` now reports the WARN unconditionally. **Before removing an env
  relay as a dead writer, grep for every reader too** (`grep -rn NAME`,
  not just `grep -rn` the export site) -- a stale claim about consumers is
  the exact shape the defect class at the top of `CLAUDE.md` names.
- **The VERDICT line's own tally does not count WAIT.** `doctor.py` appends
  `", N notice(s)"` to VERDICT when NOTICE findings exist but says nothing
  about WAIT, so a run whose only findings are WAIT lines still prints a
  bare `VERDICT: ok` -- indistinguishable from a run with no findings at
  all from the one-line summary alone. The individual WAIT lines still
  print, so `--findings` or the full report still shows them; only the
  one-line tail-read is blind to them.
