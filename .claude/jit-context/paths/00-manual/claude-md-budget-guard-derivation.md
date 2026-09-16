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
- **`test_baseline_matches_disk_1014.py` and `test_claude_md_budget_table_709.py` /
  `test_claude_md_phase_budget_table_725.py` check two different things, and passing one says
  nothing about the other.** 1014 compares the budget **dicts** (`agent_budgets.py`,
  `skill_phases.py`, `command_budgets.py`, `claude_md_budget.py`) against **bytes on disk**; 709 and
  725 compare **CLAUDE.md's own markdown tables** against those same dicts. A merge can bring
  through a dict that is perfectly correct while the table row it should match stays silently
  stale -- git merges a table row that was edited on only one side without conflicting, so a locally
  clean run (1014, 491, `skill_phase_split`, 1556, all passing) can still be red in CI on 709/725
  alone. Measured: four rows survived a merge this way in one pull request, all four caught only by
  CI. **Run the guards that read the file you actually edited, not only the guards that read the
  thing you were reasoning about** -- a cheap heuristic that would have caught it here:
  `grep -rl "CLAUDE.md" tests/` against the touched path, then run what comes back, rather than
  selecting tests by subject. Also worth knowing before it surprises you: if any of the stale rows'
  own byte counts had changed digit width, fixing them would have shifted CLAUDE.md's own total byte
  count and invalidated its self-referential row too, needing a second iteration to converge --
  nothing warns about that case.

Routed via /oss:curate from
`trap.d/1583.budget-guards-split-across-two-axes-and-only-one-runs-locally.md`.
