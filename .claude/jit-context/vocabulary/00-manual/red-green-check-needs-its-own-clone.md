---
title: "A red/green check must never revert tracked files in place, even in a scratchpad copy"
description: "A spawned Explore reviewer said it reverted two files in a scratchpad copy to replay red/green; the effect landed in the real shared worktree's git index, reported as a mutation by a concurrent auditor's tree_snapshot.py compare."
keywords: self-review, red/green, red-green check, scratchpad copy, review spawn
mode: remind
---

**Confirmed real (#1693):** a spawned reviewer briefed not to mutate the shared worktree wanted to
replay a red/green check, described its own method as "copied the worktree into scratchpad,
reverted only the two changed files to the parent commit, and reran the tests" -- and the effect
landed in the real worktree's git INDEX, not a copy: staged content matching the pre-fix commit,
while the working tree still held the post-fix bytes. A concurrent `oss:auditor`'s
`tree_snapshot.py compare` caught it as `mutated`; nothing was lost (never committed), but the
developer lane had to diff-inspect and `git reset` to clear the stale index before proceeding.

**Never run `git checkout <sha> -- <path>`, `git reset --hard`, or `git stash` against tracked
files in the worktree you were handed, even to "revert and restore" for a check.** If a red/green
replay is wanted, use a genuinely separate `git worktree add` or `git clone` for it -- never a
revert-and-restage cycle against the real tree, whatever you intend to call it in your own report.
