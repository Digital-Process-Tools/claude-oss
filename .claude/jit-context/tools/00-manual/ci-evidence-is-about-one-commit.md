---
title: "A CI reading is about the commit it ran on, and nothing else"
description: "A check that passed on a tree without your change renders identically to one that passed because of it. Name the sha beside any 'CI confirms X' claim, and remember a rerun re-runs the merge-ref it already had."
tool: Bash
match: ~gh-run|gh-branch|gh-pr:[0-9]+:status
mode: remind
---

Three incidents, one shape: **a green reading was taken from a commit that did not contain the
change it was being offered as evidence for.** Green renders identically either way; the tell is
never in the result, it is in which sha the reading came from.

- **Evidence about a tree without the change (#761/PR #1038).** A handback called `main`'s clean
  CodeQL leg on `387d8cc` "independent confirmation that lane 761's fix resolved the false
  positive". `387d8cc` was a *different* PR's squash — the fix was still unmerged on `fix/761`.
  Settled afterwards from `code-scanning/analyses`: the alert existed only under
  `refs/pull/1038/head`, going 3 results to 0 across the lane's own commits, and `main` read `0` at
  every scan because it never contained the code. The fix was sound; the argument for it was not,
  and nothing in the loop would have caught it. **Name the sha in the claim** — a claim that names
  its commit is falsifiable in one call, one that does not is prose.

- **A rerun re-runs the merge-ref it already had (#1004).** `tests.yml` triggers on plain
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
