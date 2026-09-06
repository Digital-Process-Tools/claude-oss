---
title: "A loop markdown file is an operator's manual: rules to follow, not why the rule exists"
description: "Every byte here is re-read on every turn of every lane. State the rule, the call, and how to read the result. The measurement that justified it belongs beside the constant; the incident belongs in its own issue."
match: (^|/)(agents/([^/]+\.md|[^/]+/[^/]+\.md)|skills/manager/([^/]+\.md|phases/[^/]+\.md)|commands/[^/]+\.md)$
---

**These files are loaded whole and re-read on every turn of every lane that runs them.** A paragraph
explaining *why* a rule was adopted is paid on every one of those turns, forever, and changes no
decision — the reader is being told what to do, not being asked to re-litigate it.

So when you write here, write the rule:

- **The rule itself**, stated once, in the imperative.
- **The call to make**, verbatim and runnable.
- **How to read what comes back** — every state, and especially the third one that means the check
  could not run.
- **What the caller must supply**, when the tool answers a narrower question without it.

And keep out:

- **The measurement that justified a constant.** It belongs beside the constant, in the module that
  declares it, where it is paid only by someone reading the code. `_GROUP_TARGET = 3` carries the
  cost curve; `dispatch.md` says the tool fills to three.
- **The incident that produced the rule.** It is already recorded in its own issue, permanently and
  in full. Cite the number if the rule needs provenance; do not retell the story.
- **The history of the file itself** — "before #NNNN this paragraph only described the script" is
  archaeology, and a reader acting on the current text needs none of it.
- **A rejected alternative**, unless a reader would otherwise re-propose it this week.

**The counter-argument, and where it actually binds.** This repository's history is largely expensive
lessons written down so they are not paid twice, and a trim that deletes a still-live trap costs a
whole extra review round. That argument is about the lesson surviving *somewhere*, not about it
surviving *here*: a cut that moves reasoning to the module or leaves it in its issue keeps the lesson
and stops paying for it every turn. A cut that deletes it outright does not. **Move it, then cut it.**

**Where the rule inverts: `trap.d/`.** A fragment there is prose, unjudged, and deliberately so — the
whole point is to log the finding before knowing whether it matters. Do not apply this rule to a trap
fragment, and do not apply it to `CLAUDE.md`, which is curated by hand and governed by its own rules.

**#1136 is the worked example.** `dispatch.md`'s selection band still explained how to drive four
scripts by hand after `select_issues.py` composed them (#970, #1068, #1129). 14,240 B became 6,441 B
— a 54% cut — with every directive, payload field, state and closed-set reason word kept, and the
narratives behind them left in their own issues.
