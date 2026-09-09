---
title: "A CI reading is about the commit it ran on, and nothing else"
description: "A check that passed on a tree without your change renders identically to one that passed because of it. Name the sha beside any 'CI confirms X' claim, and remember a rerun re-runs the merge-ref it already had."
tool: Bash
match: ~gh-run|gh-branch|gh-pr:[0-9]+:status
mode: remind
---

**The first two below are one shape: a green reading was taken from a commit that did not contain
the change it was being offered as evidence for.** Green renders identically either way, and the
tell is never in the result — it is in which sha the reading came from. The third is the adjacent
case, and it is here because it is answered by the same habit: a reading that was never taken at
all, in a window where you would have to have been looking to notice. Naming the sha catches the
first two; noticing that no sha was ever cleared catches the third.

- **Evidence about a tree without the change (#761/PR #1038).** A handback called `main`'s clean
  CodeQL leg on `387d8cc` "independent confirmation that lane 761's fix resolved the false
  positive". `387d8cc` was a *different* PR's squash — the fix was still unmerged on `fix/761`.
  Settled afterwards from `code-scanning/analyses`: the alert existed only under
  `refs/pull/1038/head`, going 3 results to 0 across the lane's own commits, and `main` read `0` at
  every scan because it never contained the code. The fix was sound; the argument for it was not,
  and nothing in the loop would have caught it. **Name the sha in the claim** — a claim that names
  its commit is falsifiable in one call, one that does not is prose.

- **A rerun re-runs the merge-ref it already had (#389).** `tests.yml` triggers on plain
  `pull_request`, so the checkout is a merge-ref computed **when the run started**. Re-running a
  completed run's jobs reuses that frozen ref. So when a fix lands on the default branch and a PR
  is red because its base lacked it, re-running the PR reproduces the identical failure — and reads
  as evidence the fix did not work. Push a real `git merge origin/main` (no rewrite, no force-push)
  and let a fresh run compute a fresh ref. May differ under `pull_request_target` or a `push`
  trigger; the shape that holds regardless is *a rerun re-runs what the run already was*.

- **A green default branch after a merge train is an artefact of the train ending (#968).** Across
  four merges in one tick, `main` was never once observed GREEN between them: each squash produced
  `no_run`, then `went_not_green` because `tests` had not concluded, then nothing, because the next
  merge moved `main` first. That is tolerable *only* because each PR merged on its own concluded run
  against its own rebased head. Where it stops being tolerable is a rebase skipped on
  file-disjointness grounds — the combined content then ran nowhere, and `main`'s own run is the
  only backstop. If the train always outpaces it, the backstop never fires. **Watch the last merge
  of a tick to conclusion before the tick closes.**

And read a GREEN sentence for what it excludes. `gh-branch` names the workflows that produced no
run — in this repo `changelog` produces none on a push commit, every time — so "every leg passed"
routinely describes 2 of 3 declared workflows. That third one is `unknown`, never covered.

**A commit with zero check-runs is not a green commit (#1266).** A poll
shaped as "read `commits/SHA/check-runs`, break when nothing is
`in_progress` or `queued`, then report the tally" fired within seconds
of a merge and reported `{"success": 2}` -- CodeQL's two Analyze legs.
The `tests` workflow had produced no check-run at all, so "nothing
pending" was true vacuously, and a commit with 16 unstarted legs was
reported concluded and green. The same poll made the same false report
one merge earlier. **Enumerate the workflows expected on the ref and
require each to have a run whose status is `completed`.** Zero runs for
an expected workflow is a third state -- not-yet-created -- and folding
it into the pass arm is this repository's own defect class.

The runs API answers where check-runs cannot, and tells a `cancelled`
run (superseded by a later merge, leaving no check-runs behind) from a
failed one: read `repos/OWNER/REPO/actions/runs?head_sha=SHA` and take
each run's own `name`, `status` and `conclusion`.

**A `went_not_green` saying "nothing has failed" is a pending reading,
not a failure reading, and it expires (#1214).** The watcher emits that
event for two states meaning opposite things and emits nothing when one
becomes the other: `main` was NOT GREEN for "not concluded yet", then
NOT GREEN because a leg had genuinely failed, and the verdict string
never changed category, so no second event fired. `main` stayed red for
12 minutes and two further merges landed on top of it. Treat such an
event as a promise to look again, never as a state.

**Events from two watchers do not order against each other (#1214).**
The `ts` is the poller's observation time, not the forge's event time,
so a per-PR watcher routinely reports checks for a pull request the feed
watcher has not yet announced as open -- three times in one evening.
Within one `watcher_source` and one `id` the order holds; across sources
it does not.

**A freeze, a tag or a sweep that reports work done must leave something
a later session can read (#1122).** A releaser reported `cohort-24
frozen at 37`; the label still carried the generic default description
every cohort is created with, while the previous cohort carried a dated,
tag-specific one written at its own freeze. A triage sweep in the same
session read that difference and concluded the opposite. Both readings
cannot hold, and the honest state is that nothing on the repository
recorded either. The contradiction was luck; a single agent reading only
the handback would have carried `frozen at 37` forward as fact.
