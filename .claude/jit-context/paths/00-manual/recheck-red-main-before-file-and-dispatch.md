---
title: "Re-check a red-main sighting before filing and dispatching on it -- the board read is already stale"
description: "A tick filed and dispatched a lane for a defect the maintainer had already fixed on main moments earlier, because the failure was acted on within the same turn it was observed rather than re-checked. The lane found nothing to do -- a wasted ~70k-token spawn and a filed-then-closed issue."
match: (^|/)(skills/manager/phases/dispatch\.md|agents/tick-dispatch\.md|agents/sub-manager\.md)$
---

**Before filing an issue and dispatching a lane for a red-main defect, re-check that main is still
red.** `git-branch` (or `git fetch && git pull --ff-only`) again, immediately before the file+dispatch
call -- do not act on a board read that is already several tool-calls old. A red-main sighting is
exactly the urgent-feeling event that tempts skipping the re-check, and the maintainer loop's own
scheduler can push a direct fix to main in the minutes between your last fetch and your dispatch.

Cost when missed: one wasted lane-spawn (the lane itself correctly reports zero commits, no wasted
diff) plus a filed-then-closed issue. Cheaper fix: the re-check, one call, before the dispatch that
cannot be cheaply undone.
