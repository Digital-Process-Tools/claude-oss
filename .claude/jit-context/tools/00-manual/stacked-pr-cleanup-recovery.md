---
title: "|cleanup closes any pull request stacked on the branch it deletes"
description: "GitHub does not retarget a stacked PR when its base branch is deleted -- it closes it, into a state where reopen and retarget each refuse because of the other. Recovery order below."
tool: Bash
match: ~gh-pr-merge
mode: remind
---

**Observed merging #959 (`fix/958` -> `main`) with `squash|force|cleanup` while #961
(`fix/960` -> `fix/958`) was open.** The merge succeeded, cleanup deleted `fix/958`, and GitHub
**closed** #961 rather than retargeting it. `gh-pr:961:status` then read
`state: CLOSED | mergeable: CONFLICTING`.

**Both obvious remedies refuse, in a cycle:**

    gh pr edit 961 --base main   ->  Cannot change the base branch of a closed pull request.
    gh pr reopen 961             ->  Could not open the pull request.

Reopening needs the base branch to exist; retargeting needs the PR to be open. Neither is reachable
from the state cleanup leaves.

**Recovery, in this order:**

1. `git fetch origin refs/pull/<merged-pr>/head:recoverN` then
   `git push origin recoverN:refs/heads/<deleted-branch>` — the merge op's own cleanup line already
   says the deleted branch is recoverable from `refs/pull/N/head`, which is what makes this cheap.
2. `gh pr reopen <stacked-pr>` — now that its base exists.
3. `gh pr edit <stacked-pr> --base main`.
4. Delete the restored branch again; harmless once the base has moved.
5. `git rebase --onto main <old-base-head> <branch>` — the parent commits are in `main` only as one
   squashed commit and are not ancestors of it.

**The reporting order is the trap.** `gh-pr-merge` *does* detect this — its output carries a
`## Stacked follow-up` section naming the PR and saying it "needs a poller" — but that section
prints **after** the merge and cleanup have both run, so it reads as an advisory about what to watch
next rather than a warning about what the call just closed.

**Second, smaller trap in the same recovery:** the first `git rebase --onto main` conflicted on all
three shared files with the `HEAD` side showing *pre-merge* byte counts, because local `main` was
never fetched after the merge landed on the remote. A conflict whose `HEAD` side shows values you
know were replaced is the tell — `git fetch && git reset --hard origin/main` before rebasing onto
it, rather than reading the conflict as a real disagreement.
