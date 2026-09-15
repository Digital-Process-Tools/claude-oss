---
title: "Moving CLAUDE.md's own budget row: a guard lane_setup.py will not name for you"
description: "test_baseline_matches_disk_1014.py checks CLAUDE.md's single declared total-size baseline against disk -- coarser than the per-row agent/skill tables -- and it is not in lane_setup.py's derived guard set even when CLAUDE.md is a named lane file. A raised-ceiling paragraph's own numbers have to match the real per-commit history too."
match: (^|/)(CLAUDE\.md|scripts/lane_setup\.py|scripts/claude_md_budget\.py)$
---

- **`lane_setup.py --lane CLAUDE.md --lane scripts/claude_md_budget.py
  ...` does not name `tests/test_baseline_matches_disk_1014.py` as a
  guard**, even with `scripts/claude_md_budget.py` explicitly passed as
  a lane file. That test checks CLAUDE.md's own single declared
  total-size baseline against the file's real byte count on disk --
  coarser than, and separate from, the per-row budget tables
  `agent_budgets.py`/`skill_phases.py` cover. CLAUDE.md's own
  governance rule requires updating both whenever a lane moves a
  budgeted file's row. Cost, measured: a pull request pushed clean by
  every locally-run guard and failed 4 of 7 CI legs on exactly this
  check (`declared 34266, actual 34985`), caught only because the
  review return read the pushed PR's checks rather than trusting the
  local run. **Run `test_baseline_matches_disk_1014.py` by hand
  whenever `CLAUDE.md` itself is a named lane file**, independent of
  which other script also changed, until `lane_setup.py`'s own guard
  derivation adds it.
- **A raised-ceiling paragraph's own before/after numbers have to
  match the real per-commit history**, not just look plausible next to
  the previous paragraph. Traced through `agent_budgets.py`'s history
  across three real commits, one intermediate ceiling CLAUDE.md's own
  prose named was never the real value on disk at any commit -- the
  real sequence skipped straight from the first raise to the second.
  `test_baseline_matches_disk_1014.py` compares the table's two
  columns against disk and cannot see a wrong number sitting in prose
  between two correct ones. Check the intermediate number against
  `agent_budgets.py`'s own git history before writing a "went from X
  to Y" sentence spanning more than one commit.
