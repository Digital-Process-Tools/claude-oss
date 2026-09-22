---
title: "CLAUDE.md's own re-baseline narrative drifts from its enforced table -- twice now"
description: "The last 'Re-baselined at the v0.40.0 release' sentence claimed 69,200/69,500 B; the real committed table row was 68,784/69,000 B. A later lane trusted the sentence's ending number instead of the table and had to be corrected mid-edit."
match: (^|/)(CLAUDE\.md|scripts/claude_md_budget\.py)$
---

**Before writing a new "Re-baselined for #NNNN" paragraph in CLAUDE.md's own budget section, read
the real numbers rather than the previous paragraph's claimed ending figure.** Two confirmed
instances: #1682's self-review found the v0.40.0-release paragraph's stated "66,796 B became
69,200 B... Ceiling moves to 69,500 B" did not match `git show <that commit>:CLAUDE.md | wc -c`
(really 68,784 B) or `scripts/claude_md_budget.py`'s own `BUDGETS["CLAUDE.md"]` tuple at that
commit (really `(68784, 69000)`); #1689 independently found the table's declared baseline
(72,547 B) did not match `scripts/claude_md_budget.py`'s own inline history comment (71,848 B) at
measurement time. Both lanes logged the drift and moved on rather than reconciling it -- fixing the
historical chain is a separate, larger edit than the two issues either lane was scoped to.

**Cross-check before you extend the chain, not after:** run `wc -c CLAUDE.md` and read
`scripts/claude_md_budget.py`'s `BUDGETS` tuple for `CLAUDE.md` yourself, and start your own
paragraph from those two numbers -- never from what the prior paragraph merely claims it left
behind. If they disagree with each other or with the prior paragraph, that disagreement is itself
worth one sentence in your own paragraph rather than silently picking one.
