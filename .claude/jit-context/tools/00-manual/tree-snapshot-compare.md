---
title: "tree_snapshot.py: a before-snapshot written in-worktree can be gone by the time compare runs"
description: "A snapshot at <worktree>/_snapshot.json vanished across a ~6-minute concurrent self-review spawn round, with no confirmed cause; compare returned could-not-compare, which is not clean."
tool: Bash
match: ~tree_snapshot\.py
mode: once
---

**Observed, root cause unconfirmed (#1544).** `tree_snapshot.py snapshot` wrote
`<worktree_root>/1544/_snapshot.json` immediately before spawning two concurrent self-review agents
(`Explore` and `oss:auditor`). By the time both returned, roughly six minutes later, the file was
gone: `compare --before -` reported `could-not-compare`, and a plain directory listing found
nothing at that path either. Neither spawn's own report claimed to have written or deleted
anything there, and both were told not to mutate the tree.

**`could-not-compare` is not `clean`.** A verdict this tool did not produce and a verdict of
"nothing changed" render identically to a reader skimming for the word `clean` -- read the actual
state field, and fall back to `git status` cross-checked against what you know your own lane wrote
(here: two files dirty, both self-review fixes, nothing else) when the tool's own receipt is
missing rather than treating the absence as the answer.

**Do not trust an in-worktree snapshot file to survive a long concurrent spawn round unread.**
Candidates considered, none confirmed: something in this environment sweeping dot- or
underscore-prefixed scratch files at a worktree root; a reviewer spawn's own broad cleanup command
catching the file without naming it in its own report; or a several-million-ms-long spawn's own
tool use (a full `pytest` run in the same worktree) touching the root in a way its final report did
not surface.

**Mitigation, independent of the cause:** take the before-snapshot immediately before spawning, and
read it back to confirm bytes-on-disk right when the `compare` call actually runs, rather than
trusting a write from several turns earlier to still be there. If this recurs with a second,
independent instance, that is the point to pin the cause rather than keep guessing from one.
