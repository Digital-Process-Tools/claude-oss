---
title: "In a worktree lane, read the receipt that says where the write landed"
description: "cwd resets between Bash calls, so one missing cd prefix lands a write in the main clone or a sibling lane. Every supertool write prints its own branch; tree_snapshot resolves . at the python process's cwd, not the shell line's."
keywords: worktree, lane worktree, cd prefix, sibling lane, main clone
---

**Agent threads reset cwd between Bash calls.** Every call in a worktree
lane must `cd <worktree>` itself; nothing carries over from the previous
one. This is not paranoia -- it fired twice in one week, once on the
very lane assigned to investigate it.

- **One missing `cd` prefix wrote into another lane's branch (#1155).**
  A `supertool 'edit:@-'` issued without the prefix, after a run of
  calls that all had it, landed in the **main clone**, on a different
  lane's branch. The op's own footer said so plainly:
  `[branch: chore/trap-log-1177-1180]`. **Read that line after every
  write.** It is printed on every write op whether or not you ask, and
  it is the cheapest possible confirmation available.

- **It recurred on the retry right after a refusal (#1307).** Same shape,
  same file, third instance. The call that got refused by the
  raw-command guard *did* carry `cd <worktree> && ...`; the immediate
  resend dropped the prefix, on the assumption that cwd still held from
  a successful call two calls earlier. It landed in the main clone,
  which was itself checked out to a concurrent session's branch. **A
  retry is a new call and needs its own `cd`** -- and a refusal is
  exactly the moment attention is on the refusal rather than on the
  prefix. Caught only by reading the receipt's `[branch: ...]` line and
  finding a branch name this session never created; reverted with
  `git checkout -- <file>` in the main clone before anything else
  touched it.

- **`cd` and the command joined with `&&` still resolved elsewhere
  (#1078).** `cd <root>/1078 && python3 .../tree_snapshot.py snapshot`
  recorded `"root": "<root>/1042"` -- a sibling lane named in the brief
  as "do not touch". A python process resolves `.` at its own cwd, not
  at the one the shell line names. **Read the `root` field back out of
  the JSON before trusting anything a later step says about it.**

  The tell was a verdict of `clean` on a tree that could not possibly be
  clean. A verdict that is impossible is worth more than one that is
  merely surprising.

For `tree_snapshot` specifically -- where to write the before-snapshot,
what `compare` already defaults to, and why `could-not-compare` is not
`clean` -- see `tools/00-manual/tree-snapshot-compare.md`, which owns
that tool and whose advice is not restated here.
