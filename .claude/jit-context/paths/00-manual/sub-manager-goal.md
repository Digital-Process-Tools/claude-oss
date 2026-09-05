---
title: "The sub-manager exists to be thrown away: one tick, then its context dies"
description: "Not an organisational layer -- a measured fix for quadratic context cost. It holds full tick authority except tagging and publishing, re-derives the board itself, and must end on work started or blocked, never on 'nothing pending'."
match: (^|/)(agents/sub-manager\.md|commands/tick\.md|skills/manager/phases/tick-order\.md)$
---

**Why it exists at all, and it is a measurement rather than a structure.** #695: a session running
ticks back to back pays cache-read on every earlier tick's transcript, on every call, for the rest
of the session -- median **+31k tokens per tick, quadratic** in the number of ticks. The sub-manager
is `/clear` between ticks, fired with no human at the keyboard. So the deliverable of the design is
the **discard**: one tick, report, context gone. A sub-manager that persists, or runs a second tick,
has removed the only thing it was built for.

**The scheduler stays flat because it never holds a tick's payload.** It spawns, reads one handback,
and that is all it ever does -- it hands over nothing, not even a board summary. Re-deriving the
board in full is the sub-manager's own step 1, deliberately, so a stale summary can never be
inherited.

**Authority: everything a tick covers, except tagging and publishing.** Those stay with the
scheduler, which may spawn `agents/releaser.md` for them (#696), and `scripts/agent_role.py` is the
code-level half of withholding them. A sub-manager that finds a release trigger reports it; it does
not act on it.

**It ends on one of the states `scripts/tick_handback.py` classifies** -- and validates its own
draft against that script before sending, rather than trusting memory under narrative pressure
(#1048: three handbacks in one session promised the sub-manager's own resumption, and being told
the correct format twice held for exactly one turn).

**A tick ends on work started, or on items blocked and named -- never on "nothing is pending".** A
green board is a step, not a stopping point. And a tick that spends its context on loop bookkeeping
and dispatches nothing has done no work: the developer lane is the product, and the cost that
matters is tokens per issue resolved, summed across manager, sub-manager and lane.

**Judgement, not measurement, and worth knowing before trusting it:** the frontmatter pins
`model: sonnet` on cost alone. Nothing has measured whether Sonnet suffices for reviewing diffs,
judging audit findings and handling untrusted text -- a harder seat than the developer lane, where
a spec and a suite catch a weaker model's mistakes. Reasoned, not observed.
