---
title: "A freshly cut lane branch tracks origin/main, so the first git-push refuses"
description: "git worktree add -b <branch> <path> origin/main inherits tracking from the remote-tracking start-point. Use git-push:set-upstream on a lane's first push."
tool: Bash
match: ~git-push
mode: remind
---

**Observed 3 of 3 lanes in one tick** (`fix/1014`, `fix/1015`, `fix/1017`): a plain
`supertool 'git-push'` refused twice with *"upstream is origin/main, a different branch"*, and once
had no upstream configured at all.

    supertool 'git-push:set-upstream'

retargets it in one call. Cheap once you know the shape, one refused push plus a retry per lane to
rediscover cold.

**Cause, reasoned rather than confirmed:** `lane_setup.py` resolves each lane's base as
`origin/main` — a remote-tracking ref — and `git worktree add -b <branch> <path> <base>`, which the
dispatched developer runs as its own setup step, inherits tracking from a remote-tracking
start-point by default (`branch.autoSetupMerge`). The new branch ends up tracking `origin/main`,
which it was never meant to push to.

**Worth settling rather than living with:** whether `--no-track` on that `git worktree add -b`
removes the inherited tracking at the source. Nobody has checked; today the fix is at push time.
