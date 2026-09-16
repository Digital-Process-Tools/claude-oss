---
title: "A CI reading is about the commit it ran on, and nothing else"
description: "A check that passed on a tree without your change renders identically to one that passed because of it. Name the sha beside any 'CI confirms X' claim, and remember a rerun re-runs the merge-ref it already had."
tool: Bash
match: ~gh-run|gh-branch|gh-pr:[0-9]+:status
mode: once
---

**Name the sha beside any "CI confirms X" claim.** A claim that names its commit is falsifiable
in one call; one that does not is prose. Green renders identically whether the reading is about
your change or not -- the tell is only ever in which sha it came from.

- **A rerun re-runs the merge-ref it already had, not a fresh one (#389).** Push a real
  `git merge origin/main` and let a new run compute a new ref, rather than re-running a completed
  one -- the checkout for a `pull_request`-triggered workflow is frozen at run start.
- **Watch the last merge of a tick to conclusion before the tick closes (#968).** A merge train's
  intermediate commits routinely never go GREEN between merges; that is only tolerable when every
  PR merged on its own concluded, rebased run. A rebase skipped on file-disjointness grounds removes
  that backstop.
- **A `pr_green.py` PENDING downgrade can misreport why, though it never turns a real failure green
  (#1458).** `_unresolved_runs` only reaches `pull_request`+`completed`-with-zero-jobs, which also
  covers a completed failure whose conclusion goes unread.
- **A supersede check must key on (workflow, name), not name alone (#1458).** Two same-named jobs
  in different workflows on one commit could let an unrelated job's start clear a genuinely failed
  one. Not observed on a managed repo yet; check before trusting new supersede logic on a repo with
  more than one workflow.
- **A same-sha `unknown`-then-`went_green` pair 36-40 s apart is a transient API read, not a
  regression (#1499).** Do not investigate that sha further; investigate only when a *different*
  sha's state is in question. Also: a GREEN sentence lists only the workflows that produced a run --
  a workflow producing none on this trigger (e.g. `changelog` on a push) reads as `unknown`, not
  covered.
- **A commit with zero check-runs is not a green commit (#1266).** "Nothing pending" is true
  vacuously when an expected workflow never started. Enumerate the workflows expected on the ref and
  require each a `completed` run; the runs API (`actions/runs?head_sha=SHA`) also distinguishes
  `cancelled` (superseded, no check-runs left) from failed.
- **A `went_not_green` saying "nothing has failed" is a pending reading that expires, not a failure
  (#1214).** The same verdict category covers both "not concluded yet" and "a leg failed"; treat it
  as a promise to look again, never as a state.
- **Events from two watchers do not order against each other (#1214).** `ts` is the poller's
  observation time; only within one `watcher_source`/`id` does order hold.
- **A freeze, tag or sweep that reports work done must leave something a later session can read
  (#1122).** A "frozen at N" handback with no corresponding label/state change is unverifiable, and
  a later session reading only the handback carries it forward as fact regardless.
