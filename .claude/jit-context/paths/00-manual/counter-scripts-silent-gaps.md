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

- **A gate that returns early on one failure mode hides a sibling failure mode
  present in the same run.** `doctor_check_action_pins.py`'s `if drifted: ...
  return` fires before `if unresolved:` is ever reached, so a run carrying
  both an unresolved pin (a live SHA that could not be fetched) and a
  drifted one reports only the drift -- the unresolved action drops out
  with no mention it was never checked. Confirmed with a synthetic run
  carrying both. Never let one non-`ok` branch `return` before every other
  one has had a chance to report; fold every reportable state into one
  combined report instead.

- **A parser that skips a name it cannot classify has to say so, not
  silently under-count.** `outbound_draft.py`'s `pending_count` increments
  no bucket for an entry that fails `FRAGMENT_RE` (an unparseable draft
  name), so a directory entirely full of unparseable names reports the
  same `0` a genuinely empty directory would -- the function's own
  docstring promises `None` only for `could-not-read`, silent on this
  third case. `render()` gets this right elsewhere in the same module
  (`[name does not parse as ...]` per entry); a summary counter sitting
  next to a correct per-entry reporter is the harder version of this bug
  to catch.

- **Two independent implementations of one naming convention will
  disagree, with nothing comparing them.** `statusline.py`'s
  `_outbound_count` and `outbound_draft.py`'s `FRAGMENT_RE` both parse
  `outbound/<n>.<state>.<slug>.md` and already accept different inputs
  (one requires a non-empty slug, the other does not) -- deliberate
  duplication (`statusline.py` ships standalone and cannot import the
  other), but nothing pins them to agreement the way
  `tests/test_supertool_rule_sync_577.py` already does for exactly this
  shape. The same gap recurs at `release_ci_wait.py`'s and
  `pr_green.py`'s rate-limit backoff constants: two copies, both correct
  today, nothing comparing them to each other. **A deliberately
  duplicated fact needs a same-value test between the two copies**, not
  just a test pinning each copy alone.

- **A function whose own docstring argues against silent fallthrough can still fall through two
  lines later.** `release_trigger.py`'s `_stale_local_head` (#1566) fetches the tracked remote and
  correctly reports a *failed fetch* as `could-not-evaluate` rather than silently comparing against
  a possibly-stale ref -- but the very next call, `git rev-list --count HEAD..upstream`, still
  returns `None` on failure (`if not ok or not out.isdigit(): return None`), and the caller reads
  `None` as "this check does not apply" and proceeds on an unconfirmed `HEAD`. Confirmed still live
  by direct read after the fetch-path fix (#1591) shipped -- the docstring's own argument was never
  applied to its sibling call three lines below. The same shape (`delta if delta is not None else
  release_delta.compute(repo)`, with no staleness guard at all) is also live in every other direct
  caller of `release_delta.compute()`: `agents/release-auditor.md`'s and `commands/release.md`'s
  gate 3 invocation, `release_version.py`'s `_baseline()`, and `triage_trigger.py`'s own
  `compute()` -- none of which got the guard `release_trigger.py` itself received. Whether the fix
  belongs in `release_delta.compute()` itself, once, rather than repeated per-caller, is an open
  question; the releaser's own fresh-checkout worktree is a real (if unconfirmed-sufficient)
  mitigant the scheduler's long-lived clone does not have.

**Must-fire control:** a script under `scripts/` that drops a malformed record
with a bare `continue` and no counter. **Must-not-fire control:** the
identical shape inside `tests/` (this rule is about the loop's own operational
scripts, not the suite that exercises them) -- `tests/test_agent_cost_1499.py`
sits right beside the file this rule actually governs and must stay silent.

Routed via /oss:curate from `trap.d/1499.agent-cost-unreadable-transcript-
dropped-silently.md`, `trap.d/1499.loop-cost-report-drops-unparseable-
timestamp-silently.md`, `trap.d/1499.lane-setup-brief-schema-recon-check-no-
word-boundary.md`, `trap.d/1508.doctor-event-filter-reports-one-poller-as-
all.md`, `trap.d/1571.doctor-action-pins-drops-unresolved-when-drift-present.md`,
`trap.d/1519.outbound-draft-pending-count-renders-unparseable-names-as-zero.md`,
`trap.d/1519.outbound-naming-convention-forked-and-the-two-copies-already-
disagree.md`, `trap.d/1571.ratelimit-backoff-constants-duplicated-with-no-
cross-check.md`, `trap.d/1566.release-trigger-stale-head-second-git-call-swallows-failure.md`
and `trap.d/1566.stale-head-shape-also-lives-in-release-delta-siblings.md`.
