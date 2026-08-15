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

## The `owned files` lines, and what to do about them

Owned files — `.oss/README.md`, `.oss/assemble_changelog.py`,
`.github/workflows/oss-changelog.yml` — are replaced wholesale by `/oss:scaffold`, so a fix
shipped here reaches a repo only when somebody re-runs that command there. These lines are
the only thing that tells a maintainer the re-run is worth doing, so read them as an answer
to that one question rather than as a tidiness report. Seven things they can say:

- **Nothing** — the copies match what the plugin ships today. There is no `owned files` line
  to relay.
- **`not in this repo. Run /oss:scaffold.`** — a gap. The repo was scaffolded before these
  files existed, or never scaffolded at all, and re-running writes them.
- **`absent on purpose`**, at `OK` rather than `WARN` — this repo already runs a changelog
  gate under another name, so `/oss:scaffold` declines the trio and will decline it again.
  Do **not** relay this as something to fix: the remedy for an ordinary gap is the command
  that produced this state, and a warning naming it would appear on every run of a correctly
  configured repo forever (#126). `/oss:scaffold --force-owned` is the only thing that
  changes it, and only a maintainer who checked the match by hand should pass it.
- **`would change what it does -- <names>`** — re-running changes behaviour, and the names
  are the regions: a YAML key path like `on.pull_request.types`, a Python definition, a
  Markdown heading. This is the one to act on. A repo scaffolded before the current release
  can have a changelog gate that is satisfied by *deleting* somebody's pending fragment, and
  this is the line that says so. Offer `/oss:scaffold --apply`.
- **`would change comments and prose only -- nothing it does changes`** — a real difference
  with no behavioural consequence. Worth mentioning; not worth interrupting anything for.
- **`could not be read` / `no comparison was made`** — the third state. Either the plugin's
  own copy was unreachable or theirs was, so **nothing was compared**. Never relay this as
  up to date. `/oss:doctor` can run under a plugin version different from the one that
  scaffolded the repo, and a check that cannot see our copy must not vouch for theirs.
- **`whether /oss:scaffold would write it could not be determined`** — the same third state,
  one question earlier. The file is absent and the gate check could not answer whether that
  is a gap or a decision, so it is reported as neither. This is not `absent on purpose`:
  scaffold also declines when it could not look, and a decline nobody took must never be
  relayed as a choice somebody made.

Two things the line deliberately does **not** say, because neither is measurable from inside
a managed repo: whether their copy is *older* than ours, and whether somebody *edited* it.
Nothing in the repo records which plugin version wrote the file, so those two are the same
observation and guessing between them means telling a maintainer to discard their own work.
The line describes the **effect of re-running**, which is true either way — and carries the
caveat that a deliberate edit goes with the re-run, because owned files are replaced
wholesale and the maintainer is the only one who knows whether they made one.

Two of the warnings are about CI rather than about setup, and neither is cosmetic:

- **A `test_command` that no workflow runs.** Green then means the changelog was checked
  and the tests were not run — an absence that reads exactly like a pass on the merge
  screen. The fix is a workflow you write; the doctor will not write one.
- **A leftover `ci` block in `.oss.json`.** `ci.required_checks` was deleted in #113 and
  nothing reads it. The config still validates with it — a key going away must not break
  a repo that did nothing — but the number is dead, and a dead measurement on disk reads
  exactly like a live one. Delete the block. The leg count is read off the pull request
  it applies to, with `gh pr checks`, because nothing offline can produce it: a build
  matrix expands one job declaration into many, a reusable workflow declares nothing
  locally, an organisation- or app-level check never appears in `.github/workflows/` at
  all, and a run that has not happened declares nothing either.
