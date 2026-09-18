---
title: "Fetch before trusting next_action.py / a tracker-state read -- the clone is behind by construction"
description: "Every merge the loop makes goes through the tracker (gh pr merge), never through the clone, so the clone's own main falls behind origin after every ordinary tick. A ranking or count read against an unfetched tree reports the wrong number with no third state to say it might be."
match: (^|/)(commands/run\.md|agents/scheduler-step\.md|scripts/next_action\.py)$
---

Observed three times in one `/oss:run` window (2026-09-18), same cause each time: **the clone's
`main` was behind `origin/main` when a ranking or count read ran.**

- `release` ranked `could-not-tell` on a stale `HEAD`; after `git pull --ff-only`, the same call
  ranked `due`, `merged_prs` 10/10 -- the trigger had already fired and the first read could not see
  it.
- `release` `could-not-tell` again, AND `curate` ranked `due` with "19 fragment(s)" **eight minutes
  after** the curate PR draining those fragments had already merged -- `trap.d/` on `origin/main`
  held 5. A pull turned both into `not-due`.

**`release`'s own source at least says `could-not-evaluate` with the reason.** `next_action.py`'s
`curate` source has no such state: it counts `trap.d/` on the working tree and reports a number that
is simply wrong when the tree is stale, rendering identically to a correct count of a smaller
backlog. This repo's own defect class (an absence produced by the tool, read as an absence in the
world) applies here to a *count*, not just a missing check.

**`git fetch && git pull --ff-only` before any `next_action.py` read that will be acted on** --
before step 2 of `/oss:run`, before a scheduler-step spawn ranks or counts anything. Cheap: one
network call. The alternative cost, once seen: a rebase-and-reread mid-run, or a second curate pass
spawned over fragments that no longer exist.

Not established: whether the stale `curate` count has ever actually caused a duplicate spawn -- here
it was caught by reading the number against what had just merged, not by anything in `next_action.py`
itself. Two structural fixes were named but not chosen: fetch-and-measure-against-`origin/<default_
branch>` inside `next_action.py` itself, or a `behind-upstream` state the way `release` half-has,
refusing to count `trap.d/` in that state. Either way, the caller of `next_action.py` should not
have to remember to fetch first -- until one of those lands, the caller does.

Routed via /oss:curate from `trap.d/1405.next-action-reads-stale-after-every-tracker-side-merge.md`.
