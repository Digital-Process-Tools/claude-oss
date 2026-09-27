---
title: "lane_setup.py --claim can hand back a worktree whose branch is already merged"
description: "--claim reuses an existing branch/worktree by name with no check that the branch is already merged -- a squash merge leaves no ancestry, so continuing there ships a diff full of already-shipped changes."
match: (^|/)scripts/lane_setup\.py$
mode: remind
---

`--claim` reuses an existing branch/worktree by name with no check of whether that branch's tip
is already merged into the base it resolved. A squash merge leaves no ancestry, so
`git merge-base --is-ancestor` cannot see it either -- only the branch's own closed/merged PR
tells you. Continuing work in a reused-but-already-merged tree produces a diff full of
already-shipped changes.

Before trusting a claimed worktree, check the branch's own PR state
(`gh pr list --head <branch> --state all`), not just `--claim`'s own "cannot tell" occupancy note.

If it is stale: create a fresh worktree non-destructively instead of reusing it --
`git worktree add -b <branch>-take2 <path> origin/<default_branch>` -- rather than trying to
force-clean the stale one. A stale worktree/branch's own `git worktree remove --force` /
`git reset --hard` is Git-destructive and the harness's own classifier denies it under multiple
different reasons (Git Destructive, Interfere With Workloads, Irreversible Local Destruction);
per the classifier-denial retry rule, a second denial on the identical call is not retried a
third time, so leave the stale tree in place and name it in the tick's own report rather than
burning further turns on it.

Confirmed live (#1757): a claimed worktree's branch had already been squash-merged hours earlier;
three denied attempts (two commands, two retries each) never removed it.
