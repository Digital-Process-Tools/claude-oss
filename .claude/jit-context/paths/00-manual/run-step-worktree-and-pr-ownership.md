---
title: "An /oss:run step needs a worktree of its own, and its pull request needs an owner"
description: "commands/run/*.md and agents/scheduler-step.md have no equivalent of the developer lane's worktree rule -- a step run in the primary clone strands it on a feature branch -- and no equivalent of a tick's own review-and-merge obligation, so a green step-opened pull request can sit unowned while a running tick merges underneath it."
match: (^|/)(commands/run/.*\.md|agents/scheduler-step\.md|commands/run\.md)$
---

Observed 2026-09-15/16 on the curate step of an `/oss:run` (PR #1575), and recurred 2026-09-18
(#1670): a tick running concurrently in the same clone observed curate's own writes -- a trap.d/
fragment promoted into a jit-context rule and deleted as part of that promotion -- as an
unexplained mutation via `tree_snapshot.py`'s before/after compare, because the clone was checked
out on curate's own branch mid-tick.

**Work in a worktree, never the primary clone.** A developer lane gets a worktree precisely so
the clone stays on the default branch; nothing in `commands/run/*.md` said where an `/oss:run`
step should work, and the curate spawn did its work directly in the primary clone. It could not
safely be returned to `main` while a tick was running (a branch switch under a live sub-manager
is the same destructive-concurrency shape the loop warns about elsewhere), so the clone stayed on
`curate/<timestamp>` for the whole tick, then could not be cleaned up when the PR merged:
`gh-pr-merge`'s own cleanup refused both the worktree ("occupied") and the branch delete ("used by
worktree"), parking the clone on a branch that no longer existed upstream. Recovery
(`git checkout main && git pull --ff-only` then `git branch -D`) is cheap but nothing prompts it.

**The worktree half is fixed for curate specifically, as of #1670**: `commands/run/curate.md` now
states, in the same explicit shape `agents/developer.md` uses, that it must cut and work inside its
own worktree before reading anything, and never work in the primary clone. The five sibling
procedures (`setup`, `scaffold`, `install-audit`, `triage`, `changelog`) were not touched by that
fix and may share the same gap -- this rule's own `match` still fires on all six, on purpose, until
each is checked. The PR-ownership half below is unchanged and still open.

**A pull request a step opens has nobody whose job it is to merge it.** `commands/run.md` gives
the scheduler no merge step -- it spawns a step, reads the report, and moves on. A running tick
reviews and merges only what its own dispatch opened, so a step-opened PR is invisible to it too.
`next_action.py`'s `inbound` source filters to outside authors, so a loop-authored step PR does not
even rank as pending work. The result: a green PR can sit unowned for however long it takes another
tick's own merges to collide with it. Measured: #1575 went green at 21:20Z and sat while three
unrelated tick PRs merged underneath it, reporting `conflicts_appeared` at 22:33Z -- a trivial,
purely additive conflict whose entire cost was the delay, not a real disagreement. Whoever runs a
step that opens a pull request should wait on it and merge it before reporting back, or the
scheduler needs an explicit "merge what my own steps opened" obligation -- do not assume a step's
own green PR will be picked up by anything else in the loop.

Routed via /oss:curate from `trap.d/1389.run-step-in-the-main-clone-strands-it-on-a-feature-branch.md`
and `trap.d/1389.run-step-pull-requests-have-no-owner-in-the-merge-path.md`.
