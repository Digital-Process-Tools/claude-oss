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
