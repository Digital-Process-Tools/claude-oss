---
description: Run the repo. Sets it up on first use, then triages, builds, reviews, merges on green and releases -- on a loop, no human in the merge path.
argument-hint: "[setup|scaffold|install-audit|triage|curate|changelog|release|dispatch]"
allowed-tools: Bash, Agent
---

Type this once. `/oss:run` asks one question -- **what does this repo need now?** -- and answers it
from state and config, never from an argument. `/oss:doctor` is the only other verb; everything else
below is a step this command reaches on its own, or a forcing override, never a menu entry (#1389).

**This session is the scheduler, and the scheduler calls scripts and spawns agents -- it never
reads a procedure document itself (#1414).** Every file this session opens stays in its context for
the rest of what may be an hours-long, many-tick run; the discipline #695 built `oss:sub-manager`
for applies here with the same force, one layer up. A script call (`next_action.py`, `doctor.sh`)
costs its output, not its work, and stays in this session; a procedure -- `commands/run/*.md`,
`commands/release.md`, `commands/tick.md`'s own tick -- is read only inside a spawn whose context
is discarded the moment it reports back.

## An argument forces a step, and every forced step is a defect report

`$ARGUMENTS` names one of `setup`, `scaffold`, `install-audit`, `triage`, `curate`, `changelog`,
`release`, `dispatch`. When one is given, skip straight to that step's own spawn below --
**Every argument someone has to type is a trigger that is missing.** `/oss:run triage` forcing a
sweep right now, rather than when due, means the triage source in step 2 did not rank first on its
own; say so rather than treating the override as ordinary use.

No argument: run every step below in order.

## Step 1 -- diagnose and repair, never stop except for a named unsafe gap (#1390)

Run the same diagnostic `/oss:doctor` runs:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh" --root . --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

Relay every `WARN` and `FAIL` line, then act on each:

- **Ours to repair** -- an owned file that is missing or stale (`scripts/scaffold.py --apply`), a
  config gap `oss_config.py --probe`/`--build` can re-derive (folded into step 2's `setup` branch
  below, since a missing `.oss.json` is exactly that gap), a rule layer that is indexed but not
  installed. Repair it and say what changed.
- **Not ours** -- a missing binary, a permission this session lacks, a repository setting nobody
  here can flip. Report it, mark that capability unavailable for the rest of this run, and carry on.
  A gap makes *some* work impossible; it does not make all work impossible.

**This step never stops the session by itself.** The one thing that can stop `/oss:run` is step 2
reporting `unsafe`, immediately below -- so an unrepairable gap is named once, at the point that
actually has to act on it, not diagnosed twice in two different steps.

## Step 2 -- decide

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/next_action.py" --root . --json
```

`next_action.py`'s `rank()` (#1405) composes four sources every call and returns them ordered,
never arbitrating one verdict:

- **`unsafe`** -- no config and the probe itself could not run, or a `default_branch` that does not
  resolve to a real ref. A refusal, not a candidate. Stop. Report `reason` and `remedy` plainly --
  "the loop refused to start" must never be a dead end with nothing attached to clear it.
- **`due`** -- only ever `next: "setup"`: no `.oss.json` at all, and a probe is confirmed safe.
  Spawn it below, then return to step 2 once it completes -- `setup` changes what every other check
  reads, so the honest next answer is a fresh call, not an assumption.
- **`ranked`** -- `candidates`, ordered, each carrying its own `source`/`state`/`reason`/`evidence`.
  Take `candidates[0]` by default. If its `state` is `could-not-tell`, report `reason` loudly and
  fall through to **dispatch** -- an unresolved top candidate might have been the real answer, so a
  `due` entry ranked below it is not trusted automatically. Taking a lower-ranked `due` entry
  instead of an unresolved or a `due` `candidates[0]` is this session's call to make, not a rule to
  follow blindly (#1405's own point: the script measures, the agent decides) -- when you do, record
  it first, or a loop skipping the same top candidate for ticks running is indistinguishable from
  one that never had a top candidate:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/next_action.py" --root . --record-skip <source> --reason "<why>"
  ```

  **Reading `rank()`'s answer never commits to it.** `next_action.py --json` is a plain read, and a
  session that calls it many times over a long run must see the identical answer every time until
  something actually changes -- curate and triage's own repeat-suppression receipt is armed only by
  an explicit commitment, never by rank() being asked. Before spawning the procedure below for
  whichever `source` you are actually taking (`candidates[0]`, ordinarily), say so:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/next_action.py" --root . --take <source>
  ```

  This is a no-op for `inbound`/`release` (neither carries a receipt of this kind) and refuses if
  `<source>` is not `candidates[0]` -- use `--record-skip` instead for a deliberate deviation, which
  arms `<source>`'s own receipt itself once the skip is recorded. `source` is `inbound`, `release`,
  `curate` or `triage`. `inbound` has no dedicated spawn of its own below -- `skills/manager/phases/
  inbound.md` is read inside dispatch's own tick, so an `inbound` `candidates[0]` proceeds straight
  to **dispatch** rather than pointing anywhere new (and needs no `--take` call either).
- **`nothing-due`** -- every source resolved cleanly and none fired. Proceed to **dispatch**.

## setup

No `.oss.json`, and `next_action.py` has already confirmed a probe is safe to attempt.

```
Agent(subagent_type: "oss:scheduler-step", prompt: "Read and follow commands/run/setup.md from here.")
```

It measures the repo and writes the config; do not guess values by hand. Read its report, then
return to step 2 -- `setup` changes what every other check reads.

## scaffold / install-audit / triage / curate / changelog

Each keeps its own procedure, unchanged, at its own file -- moved out of `commands/` by #1389 (the
plugin harness discovers slash commands from top-level `commands/*.md` only, never recursively),
reachable here or by the forcing override above, never by typing `/oss:scaffold` and so on
directly. Spawn the one step 2 named (or the one `$ARGUMENTS` forced) -- one literal call per file,
never a `<name>` filled in by hand, so a session cannot follow the wrong one:

```
Agent(subagent_type: "oss:scheduler-step", prompt: "Read and follow commands/run/scaffold.md from here.")
Agent(subagent_type: "oss:scheduler-step", prompt: "Read and follow commands/run/install-audit.md from here.")
Agent(subagent_type: "oss:scheduler-step", prompt: "Read and follow commands/run/triage.md from here.")
Agent(subagent_type: "oss:scheduler-step", prompt: "Read and follow commands/run/curate.md from here.")
Agent(subagent_type: "oss:scheduler-step", prompt: "Read and follow commands/run/changelog.md from here.")
```

Read its report, then return to step 2 to ask again what is needed now.

## release

`commands/release.md` stays where it is in the picker (see #1389's own note on why). Spawn the
dedicated release agent directly rather than reading that file yourself -- it already reads its own
procedure inside its own discarded context:

```
Agent(subagent_type: "oss:releaser")
```

Classify what comes back with `scripts/release_handback.py`, then return to step 2.

## dispatch

The ordinary cadence: read the board, decide what to build, delegate, review, merge on green. This
is `commands/tick.md`'s own procedure, unchanged -- it is a thin spawn wrapper, not a document to
follow, so reading it here does not repeat #1414's own mistake. Read and follow it from here.
