---
title: "An issue whose own comments say it needs a maintainer decision is not dispatchable as a diff"
description: "When an issue body or a maintainer comment states in as many words that a design-shape decision is outstanding ('not decided here', 'needs a maintainer decision on X before it is dispatchable'), a developer lane has no authority to pick a shape unilaterally -- report it undispatchable rather than forcing a mechanical fix onto an open design question."
match: (^|/)(skills/manager/phases/dispatch\.md|agents/tick-dispatch\.md|agents/recon\.md)$
---

Issue #1044 (2026-09-15): the issue's own body and the maintainer's own comment both said, in as
many words, that the remaining scope ("rank-then-hunt" selection order) was "a genuine design
question, not a mechanical bug, and needs a maintainer decision on the selection algorithm's shape
before it is dispatchable as a diff." A developer lane spawned against it would have had no
authority to make that shape call, and picking one unilaterally is exactly the unbriefed design
call the developer brief already tells a lane to push back on rather than take.

**Before dispatching an issue, check its body and comment thread for an explicit "not decided
here" / "needs a maintainer decision" statement.** One recon pass plus one issue read is enough to
catch this -- cheap, but only if it happens before a lane is spawned rather than after one discovers
it mid-lane and burns the same cost finding what a pre-dispatch read would have shown for free.
An issue in this shape is not `no-adjacent` or `stale`; it is genuinely undispatchable until the
maintainer states the shape decision, and dispatch should report it that way rather than silently
skipping it or forcing a lane onto it.

Routed via /oss:curate from
`trap.d/1044.rank-then-hunt-half-is-an-undecided-design-question-not-a-diff.md`.
