---
description: Diagnose this repo's oss setup — config, dependencies, clone, worktree root, state file.
allowed-tools: Bash
---

Run the diagnostic and relay its output verbatim:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh"
```

Do not summarise away any line. Each is one of three states:

- `OK` — checked, and fine.
- `WARN` — the check ran and could not answer, or found a gap that is not fatal.
- `FAIL` — checked, and broken.

A `WARN` is not a pass. If the output ends in `VERDICT: could not run`, the diagnostic itself did not
execute — say that plainly rather than reporting the repo as healthy, because nothing was measured.

If `.oss.json` is missing, the fix is `/oss:setup`. Offer it; do not run it unasked.

Two of the warnings are about CI rather than about setup, and neither is cosmetic:

- **A `test_command` that no workflow runs.** Green then means the changelog was checked
  and the tests were not run — an absence that reads exactly like a pass on the merge
  screen. The fix is a workflow you write; the doctor will not write one.
- **`ci.required_checks` at 0 beside workflow files.** The merge gate has no count to
  hold a pull request against. Measure it from
  `gh api repos/OWNER/NAME/commits/<sha>/check-runs` — which sees organisation-level and
  app checks that counting workflow jobs structurally cannot — and set it by hand.
