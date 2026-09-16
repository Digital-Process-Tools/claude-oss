---
title: "Merged-but-still-open: check for a deliberate reopen before reporting it as a finding"
description: "A merged PR linked to a still-open issue looks identical whether the issue was forgotten or was closed once, then deliberately reopened with a comment explaining why. The triager reports rather than closes either way, but the finding itself needs a reopen-history check or it reads as an instruction to close an issue a human explicitly kept open."
match: (^|/)agents/triager\.md$
---

Observed 2026-09-15/16: a triage sweep reported `Merged-but-still-open: #383 -- PR #1371 is merged
(10/10 green) but #383 is still open.` Read as written, that reads as an instruction to close #383.
Closing it would have been wrong: #383 is a class issue, closed once already on a merge with no real
`Closes` line (bound only by `fix/383`-style branch naming), and reopened the same day by the
maintainer with a comment citing three separate prior occasions it was deliberately kept open.

**"A merged PR is linked, and the issue is open" is true of a deliberately reopened issue and of a
forgotten one, identically** -- the state that tells them apart (a closure followed by a reopen,
with a comment explaining it) exists in the tracker and this check does not read it on its own. The
triager already never closes an issue itself (agents/triager.md's own rule), so the immediate risk
is contained; the real cost is downstream, in whoever reads `merged-but-still-open` as a to-do
without checking the issue's own history first, which is exactly the failure mode #383's own
2026-09-09 reopen comment was written to stop from recurring.

**Before treating merged-but-still-open as a finding, check whether the issue has ever been
reopened after a closure.** If so, report it as `reopened-deliberately` (carrying the reopen
timestamp and comment) rather than as a plain finding -- a third state, not a suppressed one, so the
next reader can tell "nobody has looked" from "someone looked and said no."

Routed via /oss:curate from
`trap.d/1550.merged-but-still-open-check-cannot-see-a-deliberate-reopen.md`.
