---
title: "Before a curate pass deletes anything in trap.d/, git add the whole directory"
description: "A curate pass deletes every fragment it resolves. An untracked fragment deleted that way is gone from disk, the reflog and every git object -- no porcelain entry, nothing recoverable. git add trap.d/ first makes every deletion a staged-but-uncommitted change, recoverable with git checkout -- or git show :<path>, at zero cost."
match: (^|/)trap\.d/
---

Observed 2026-09-14 (#1425), watching a live `/oss:curate` pass: it emptied `trap.d/` of 30
fragments in one step. 21 were tracked and showed as ` D` in `git status --porcelain`, recoverable.
The other 9 were untracked -- `trap.d/` is the sanctioned place to write a fragment directly on the
default branch, so "untracked" is the ordinary state, not carelessness -- and their deletion left no
record anywhere: not in porcelain, not in the reflog, not in any object. One of the nine had been
written three minutes before the pass deleted it and was never read by that pass at all; its content
survived only because the session that wrote it still held the text in context and could paste it
back by hand.

**`git add trap.d/` before deleting anything, every time.** It costs one call and turns every
subsequent deletion into a staged-but-uncommitted change -- recoverable with `git checkout --
<path>` or `git show :<path>` right up until the pass's own commit, at zero cost to a pass that goes
on to delete the file as designed either way.

**Delete by the list this pass actually read, never by a glob over the directory.** A glob deletion
sweeps up anything that landed after the pass took its inventory -- including a fragment written by
a concurrent session mid-pass -- and it is indistinguishable afterward from a fragment the pass
opened and declined. Reading the whole backlog first, then working from that fixed list, is what
`commands/run/curate.md` already asks for ("read every fragment first, then decide"); deleting from
the same list closes the gap between what was decided and what disappears.
