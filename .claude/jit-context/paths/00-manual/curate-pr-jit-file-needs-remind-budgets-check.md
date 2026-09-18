---
title: "A curate PR that edits a jit-context file must check remind_budgets.py first"
description: "A curate pull request grew a budgeted jit-context file past its declared budget with nothing catching it before the push -- CI caught it three legs later, costing a full needs-fix review round."
match: (^|/)\.claude/jit-context/.*\.md$
---

**Before committing any edit to a file under `.claude/jit-context/`, run
`python3 scripts/remind_budgets.py --check`.** PR #1638 grew
`.claude/jit-context/tools/00-manual/supertool-payload-forms.md` from 2126 B to 3269 B with nothing
in the curate pass checking the declared row in `scripts/remind_budgets.py` first -- both
`tests/test_baseline_matches_disk_1014.py` and `tests/test_remind_budgets_1584.py` went red on
every CI leg, deterministically, caught only after a full review round.

**Update the row (baseline, and budget if it grew past the ceiling) in the same commit that grows
the file**, the same replace-don't-append discipline `CLAUDE.md`'s own budget tables use for
themselves. Running the check before pushing is strictly cheaper than a red PR three legs later.
