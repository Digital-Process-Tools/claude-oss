---
title: "scripts/*.py counters and checks: an absence dropped silently renders as a clean answer"
description: "Four instances in one audit round: an unreadable file dropped with no counter, an unparseable timestamp dropped with no counter, a bare substring match with no word boundary reporting a false ok, and a glob that inspects only the first of several matched files. Each is this repo's own named defect class -- a check that never looked and a check that found nothing render identically."
match: (^|/)scripts/[^/]+\.py$
---

**This fires on every `scripts/*.py`, deliberately.** All four of these were
found in a different module from the others, in the same release-audit round
-- narrowing this to the four named modules would stay silent for the fifth.

- **A silent `continue` on an unreadable or malformed input is a dropped
  record, not a clean scan, unless there is a counter proving otherwise.**
  `agent_cost.py` drops an unreadable transcript or unlistable directory
  with a bare `except OSError: continue`, and `loop_cost_report.py` drops a
  record with an absent, non-string or unparseable timestamp the same way --
  both while their own docstrings promise every candidate is accounted for.
  A `chmod 000` file and a genuine "no match" both render as `no-match`.
  Sibling scripts in the same codebase get this right
  (`loop_cost_report.py`'s own `unreadable`/`malformed` lists for other
  cases, `script_call_survey.py`'s stated rule "must never render as called:
  an unreadable file"). **Every skip needs a counter in the payload, even
  the skips that feel too small to matter** -- the module that already has
  two working counters and misses a third is the harder bug to catch than
  one with none.

- **A bare substring match with no word boundary reports `found` for input
  that merely contains the letters.** `lane_setup_brief_schema.py`'s recon
  check does `if "recon" not in lowered`, so "Please reconsider the
  approach" or "we should reconstruct the fixture" both read as recon
  material present, with nothing that actually orients a lane. Anchor on a
  word boundary or the section's own heading, never a bare substring, for
  any check whose job is "is this concept actually here".

- **A glob that can match several files but reads only the first is a
  coverage claim wider than what ran.** `doctor_check_event_filter.py` does
  `path = paths[0]` against a glob that can match one state file per polled
  branch, then reports OK "for all of them" with nothing naming which one
  was actually inspected. A second poller added beside a correctly-
  configured one produces a byte-identical OK line. **Iterate every matched
  file, or name which one you actually read** -- never report on the set
  while reading one member of it.

- **An arg parser that finds the flag but not its value has a fourth
  outcome, not three.** `plugin_update.py`'s and `statusline.py`'s
  `_arg_value(argv, flag, default)` both return `default` identically
  whether the flag was never passed or was passed as the very last token
  with nothing after it -- so `--root` with nothing following silently
  answers "root is cwd" for an invocation that was actually malformed, with
  no warning printed either way. **Passed-but-valueless and never-passed are
  two different facts a caller might want distinguished** -- worth a state,
  or at least a printed notice, in any new `_arg_value`-shaped helper rather
  than repeating the same silent collapse.

**Must-fire control:** a script under `scripts/` that drops a malformed record
with a bare `continue` and no counter. **Must-not-fire control:** the
identical shape inside `tests/` (this rule is about the loop's own operational
scripts, not the suite that exercises them) -- `tests/test_agent_cost_1499.py`
sits right beside the file this rule actually governs and must stay silent.

Routed via /oss:curate from `trap.d/1499.agent-cost-unreadable-transcript-
dropped-silently.md`, `trap.d/1499.loop-cost-report-drops-unparseable-
timestamp-silently.md`, `trap.d/1499.lane-setup-brief-schema-recon-check-no-
word-boundary.md` and `trap.d/1508.doctor-event-filter-reports-one-poller-as-
all.md`.
