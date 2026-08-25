---
description: Audit a fresh install — plugin, declared dependencies, and what the human still has to do — before there is an issue, a pull request or an .oss.json to read. Not a diagnosis of this repo; see /oss:doctor for that.
allowed-tools: Bash
---

Run the audit and relay its output verbatim:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh" --install-audit --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

Add `--root <path>` to point it at a repo other than the one you are standing in.

**This is not `/oss:doctor` with a flag flipped, and it does not run doctor's normal check
sequence.** `/oss:doctor` answers *is this repo's oss setup healthy*, and on a repo that has never
run `/oss:setup` five of its checks correctly degrade to `not checked -- .oss.json was not found` —
honest, and also most of what a fresh installer would read back. This command's subject is
different: the plugin, its declared dependencies, and what the human still has to do, not this
repository — so every question below is answerable with no `.oss.json` in hand, and none of them
is silently skipped for lack of one.

Every line is one of the same three states doctor uses:

- `OK` — checked, and satisfied.
- `WARN` — the check ran and found a gap, with a named remedy, or could not answer at all. Both
  render as `WARN`; the text says which. **`could not tell` is not a pass.** A line reading
  `label vocabulary: could not tell -- gh is not on PATH` means the question was never answered —
  relay it as a gap in the measurement, not as a clean board.
- `FAIL` — reserved for an argument or environment problem this run itself hit (a bad flag,
  `scripts/oss_config.py` failing to import). Nothing about the *state* of a fresh install is ever
  a `FAIL` here: a repo with no `.oss.json`, no dependencies active and no labels yet is exactly
  the case this command exists for, and reporting that as broken would make the single most
  expected outcome read as one.

## What it checks

- **`.oss.json` present, valid, and committed** — three separate facts on three lines. Present and
  valid say nothing about whether a clone of this repo would ever see the file; only
  `.oss.json committed: ...` answers that, off `git ls-files`, and `NOT tracked by git` there is a
  real gap even when the file loads cleanly from disk.
- **Declared dependencies** — read from this plugin's own manifest (`declared_dependencies()`),
  never hardcoded. Each one is `resolves` (active, and its own manifest is readable — the two
  together are what makes its version comparable), `contract-unknown` (active, but its manifest
  could not be read — the cache-versus-tree skew a stale answer here can hide), or `missing` (not
  active at all).
- **`./supertool` entry point** and the **`oss-workspace` launcher** — the same two checks
  `/oss:doctor` already runs, reused rather than re-derived.
- **`identity.md`**, at whichever location the install layout actually reads — same check as
  `/oss:doctor`'s memory line.
- **The label vocabulary the triager needs** — read off the forge directly (`gh label list`, or
  `.oss.json`'s own `repo` key when one is loaded), classified with the same pattern the triager and
  `/oss:setup` both use. No `priority-*` label on the repo is a named gap, not a silent pass: the
  triager correctly refuses to invent one rather than guessing.
- **Owned files**, and whether re-scaffolding would change them — only when `.oss.json` was found,
  because rendering what the plugin would write needs the config it renders from. Without one, this
  says so rather than skipping silently: `owned files: not checked -- .oss.json was not found`.
- **The rule layer**, reachable and not merely indexed — the same check `/oss:doctor` runs.

If `.oss.json` is missing or does not validate, offer `/oss:setup`; do not run it unasked.

## What this comment folds in — and what it leaves open (#286)

#287's own tracker comment folds a separate finding (#286) into this issue as a second checklist
line: four install gaps hit by hand in two days, kept as evidence independent of this remedy. Two
of those four are covered by the checks above — no priority labels on a fresh repo, and a
cache-versus-tree dependency skew. **The other two are not implemented here and are not silently
dropped**: whether `${CLAUDE_PLUGIN_ROOT}` goes stale across a tick is a fact about a running
*session*, not about a repo on disk, and nothing this command reads answers it from outside one.
That gap is reported to the maintainer rather than assumed closed.
