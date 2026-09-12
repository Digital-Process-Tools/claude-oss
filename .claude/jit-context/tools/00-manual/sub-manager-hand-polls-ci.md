---
title: "A second status read on the same PR inside a tick is hand-polling"
description: "One sub-manager spent a 5h18m tick and 109M context tokens re-reading gh-pr status by hand. The two sanctioned shapes are one pr_green.py --wait call or a TICK: paused handback with WAIT-DISPATCH/WAIT-OBSERVABLE."
tool: Bash
match: ~gh-pr:[0-9]+:status|gh-branch|gh-job:
mode: remind
---

**Inside a tick, the first `gh-pr:N:status` is a reading. The second one on the same PR is
hand-polling**, and so is every `gh-branch`, `gh-job:` or `radar` call made to find out whether CI
has moved since the last look. Each of those calls is a turn, and a turn re-sends the whole
sub-manager context -- which never shrinks.

Measured (#1499): one sub-manager spent a **5h18m tick** and **109M context tokens** doing exactly
this -- 413 assistant turns, context climbing to 497k, most of them status reads on PRs the tick had
already dispatched, waiting for checks a tool could have waited for. Two more sub-managers in the
same night reached 415k and 407k the same way. Sub-managers were 19% of that night's spend, and the
per-tick price is the position of the call in the transcript, not the work the call did.

There are exactly two sanctioned shapes for a CI wait, and both are in
`skills/manager/phases/ci-green.md`:

- **One `pr_green.py --wait` call.** It polls inside a single turn and returns `green` / `red` /
  `pending` once, so the context is paid once for the whole wait rather than once per look. Read
  its state field, never a substring of its output (#1086).
- **A `TICK: paused` handback** with `WAIT-DISPATCH:` (what this tick set in motion) and
  `WAIT-OBSERVABLE:` (what clears it -- checks green, a leg failing). The scheduler resumes a fresh
  sub-manager at the observable; this one dies with its context, which is the point.

Before either, re-select: a lane freed by a merge may have a next issue ready to dispatch, and
that is a better use of the turn than a wait (#1190). What is not on the list is a third status
read. If you are about to run one, you are choosing between the two shapes above and have not
chosen yet.
