---
description: Diagnose this repo's oss setup — config, dependencies, clone, worktree root, state file.
allowed-tools: Bash
---

Run the diagnostic and relay its output verbatim:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh"
```

Add `--root <path>` to point it at a repo other than the one you are standing in. The flag wins over
`CLAUDE_PROJECT_DIR`, and when the two disagree the run says so and names the tree it did **not**
look at — that disagreement is how a well-formed answer about the wrong repository reaches someone.
A `--root` that is not a directory is a `FAIL` line, not a crash: the run continues and every
config-dependent check below reports itself unmeasured.

Do not summarise away any line. Each is one of three states:

- `OK` — checked, and fine.
- `WARN` — the check ran and could not answer, or found a gap that is not fatal.
- `FAIL` — checked, and broken.

A `WARN` is not a pass. If the output ends in `VERDICT: could not run`, the diagnostic itself did not
execute — say that plainly rather than reporting the repo as healthy, because nothing was measured.

**`not checked` is the third state, and it is not a clean result.** A line reading
`clone: not checked -- .oss.json was not found` means that check never ran. Five of them say it:
`clone`, `worktree_root`, `state_file`, `CI enforcement` and `owned files`. Relay them as gaps in
the measurement, not as findings about the repo — the config they would have been measured against
was absent, so nothing below them is evidence either way. `clone` and `worktree_root` are paths on
one person's disk and live in the untracked `.oss.local.json`, not in the committed `.oss.json`, so
that is the file to look in when one of them is wrong.

If `.oss.json` is missing, the fix is `/oss:setup`. Offer it; do not run it unasked — **unless** the
report also says `the enclosing clone was not searched`. That line means the run was pointed at a
tree it was not standing in, so the clone was never consulted and a worktree's config could be
sitting there untouched. Re-run from inside the tree before offering to write anything.

If instead the report says `.oss.json read from the enclosing clone`, nothing is wrong: you are
standing in a worktree and the config lives in the clone, which is where it belongs. Do not write a
second one.

Two of the warnings are about CI rather than about setup, and neither is cosmetic:

- **A `test_command` that no workflow runs.** Green then means the changelog was checked
  and the tests were not run — an absence that reads exactly like a pass on the merge
  screen. The fix is a workflow you write; the doctor will not write one.
- **`ci.required_checks` at 0 beside workflow files.** The merge gate has no count to
  hold a pull request against. Measure it from
  `gh api repos/OWNER/NAME/commits/<sha>/check-runs` — which sees organisation-level and
  app checks that counting workflow jobs structurally cannot — and set it by hand.
