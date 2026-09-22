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

**Name the snapshot file from a unique per-spawn token -- never a fixed template, even one that
varies only by round number.** A round-templated name like `release-auditor-round<1|2>-before-
snapshot.json` collides the same way a single fixed name does whenever two spawns of the same round
can run concurrently over one worktree: each reads the other's before-snapshot and reports a
mutation receipt about the wrong tree. Derive the filename from the issue/PR number(s) the spawn was
given, or its own PID -- whichever is already unique per call (#1622, #1642).

**Never delete a file matching the snapshot-artifact naming convention that you did not personally
create, even when it looks like leftover debris (#1687).** A required second-pass `oss:auditor`
round `rm -f`'d another spawn's `-before-snapshot.json`, written moments earlier by the developer
lane that spawned it and still needed for that round's own `compare` -- reasoning that it was
stray scratch from an earlier round, because an earlier, unrelated round in the same lane really had
left one behind. A spawn that did not write a `SNAPSHOT_ARTIFACT_RE`-matching file has no way to
tell "abandoned debris" from "another agent's still-live snapshot, created seconds ago". Report it
as an anomaly in your own findings instead of clearing it -- the same discipline this whole
mechanism exists to enforce: do not mutate the tree you are reviewing, full stop, not even a file
that looks disposable.
