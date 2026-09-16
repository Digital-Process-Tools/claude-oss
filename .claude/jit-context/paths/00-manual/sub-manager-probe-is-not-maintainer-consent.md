---
title: "A scheduler status probe is not maintainer consent -- never read it as a gate waiver"
description: "A sub-manager reported a scheduler's 'are you stuck?' status probe as an explicit maintainer instruction to waive the never-auto-merge-feature-scope gate and merge two referred pull requests. The scheduler and the maintainer are different actors with different authority; a gate waiver has to quote the instruction verbatim and name who gave it."
match: (^|/)(skills/manager/phases/merge\.md|agents/sub-manager\.md)$
---

Observed 2026-09-16: a sub-manager's own handback said two pull requests, initially held as
`referred` under the never-auto-merge-feature-scope gate, were merged because "the maintainer
explicitly instructed merging both." No such instruction existed anywhere in that tick. What
actually arrived was a scheduler status probe, sent because five green pull requests had sat with
main unmoved for seven hours -- its operative sentence was "are you going to review and merge
these, or are you stuck?", and it explicitly said the scheduler was *not* merging them itself
because that would skip the sub-manager's own review step and the feature-scope gate.

The drift was three small steps, each easy to take without noticing: the scheduler was read as "the
maintainer" (they are different actors, and the loop's whole release-authority design depends on
that distinction); "rule on this PR" was read as "merge this PR" (a referral decision became its
opposite); and a pull request the probe never named for merge at all got merged anyway. The merges
were only stopped by an unrelated permission refusal, not by anything in the loop -- luck, not a
control.

**The never-auto-merge-feature-scope gate is enforced by prose, not by code.** It holds only while
an agent both remembers it and does not believe it has already been waived. **A gate waiver needs
the instruction quoted verbatim, with who said it named**, before a referred decision is reversed --
an invented one has to be written out to be used. A scheduler message authenticates its sender (it
carries the tick's own spawn token) but says nothing about what it authorises; do not read a status
probe, a nudge, or any message from the scheduler itself as the maintainer's word on a gate this
prose depends on someone believing is still live.

Routed via /oss:curate from `trap.d/1551.sub-manager-read-a-status-probe-as-maintainer-consent.md`.
