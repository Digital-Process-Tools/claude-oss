---
title: "Editing an agent definition or a manager phase file: parity and runnable cells"
description: "Two copies agreeing proves nothing about whether either is right -- pin the measured string. A table's command cells are run verbatim: quote the plugin root and check the exec bit."
match: (^|/)(agents/[^/]+\.md|skills/manager/([^/]+\.md|phases/[^/]+\.md))$
---

- **Two copies of a brief agreeing with each other proves nothing about whether either is right.**
  `agents/developer.md` and `skills/manager/phases/dispatch.md` both told an agent an `[[ops]]` entry
  missing its `op` field fails with `batch op missing op field`. The real string, measured by tripping
  the failure, is `batch op missing 'op' field`. Both content checks asserted each copy against a
  floor and never against each other, so drifting into agreement on a wrong string was invisible.
  **Pin the measured tool output**, not the parity — parity alone passes this case.
- **A table's command cells are commands a session runs verbatim.** Two found by a release audit, not
  by any test: a cell invoking `scripts/fleet_label.py` directly, which is committed mode 100644 with
  no shebang and exits 126 (`scripts/lane_setup.py` two rows up is 100755, so the exec bit does
  survive packaging); and `${CLAUDE_PLUGIN_ROOT}` unquoted in all four cells, which word-splits on a
  plugin root containing a space — the ordinary shape of a Windows home directory built from a
  two-word account name.
- **Byte budgets bind here.** `scripts/agent_budgets.py` and `scripts/skill_phases.py` declare them;
  a file is re-read on every turn of every lane that runs it. **Replace, don't append** — pay for a
  new paragraph by cutting one, or raise the number in the same diff with a sentence saying what was
  weighed.

- **A new Bash-granted file under `agents/` needs a fifth guard beyond the three above.**
  `tests/test_delegated_test_run_877.py` requires every Bash-granted `agents/*.md` file to declare,
  in its own name-lookup tables, whether it may run the test suite (`ALREADY_COVERED_ELSEWHERE`,
  `NO_TEST_CONCERN`, or `REQUIRED_MARKER`) -- a new agent file is unaccounted for the moment it
  exists, and this guard refuses to guess which bucket it belongs in. Run it alongside
  `test_agent_definition_budget_491.py`, `test_claude_md_budget_table_709.py`,
  `test_baseline_matches_disk_1014.py` and `test_agent_grant_is_total.py` whenever adding a new file
  under `agents/` (#1414).
- **A content guard can go red on layout, not on content, and the correct fix is to re-wrap.**
  `tests/test_command_references.py` matches **per line**, not across the document. A deletion pass
  that reflows a paragraph can split an asserted phrase across a newline without changing a word:
  `only line that asks the forge` in `commands/setup.md` and `deferring to the next tick is not a
  decision` in `SKILL.md`, twice in one pass, in different files, found by different agents (#1136).
  This inverts the usual reading -- normally a red content guard means you deleted something
  load-bearing. **Check whether the asserted phrase spans a line break before concluding you cut too
  much.**
- **Add `--no-cov` when running a small subset.** `pyproject.toml`'s `addopts` carries
  `--cov-fail-under=85`, so a perfectly green 3-file run prints `FAIL Required test coverage of 85%
  not reached. Total coverage: 3.62%` -- a line that names no test and no file and reads as a failure
  when nothing failed.
