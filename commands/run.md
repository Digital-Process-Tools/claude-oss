---
description: Run the repo. Sets it up on first use, then triages, builds, reviews, merges on green and releases -- on a loop, no human in the merge path.
argument-hint: "[setup|scaffold|install-audit|triage|curate|changelog|release|dispatch]"
allowed-tools: Bash, Agent
---

Type this once. `/oss:run` asks one question -- **what does this repo need now?** -- and answers it
from state and config, never from an argument. `/oss:doctor` is the only other verb; everything else
below is a step this command reaches on its own, or a forcing override, never a menu entry (#1389).

## An argument forces a step, and every forced step is a defect report

`$ARGUMENTS` names one of `setup`, `scaffold`, `install-audit`, `triage`, `curate`, `changelog`,
`release`, `dispatch`. When one is given, skip straight to that step's own procedure below --
**Every argument someone has to type is a trigger that is missing.** `/oss:run triage` forcing a
sweep right now, rather than when due, means the triage trigger in step 2 did not fire on its own;
say so rather than treating the override as ordinary use.

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

Four states, and the fourth is the one that stops the loop:

- **`unsafe`** -- no config and the probe itself could not run, or a `default_branch` that does not
  resolve to a real ref. Stop. Report `reason` and `remedy` plainly -- "the loop refused to start"
  must never be a dead end with nothing attached to clear it.
- **`due`** -- `next` names the single most urgent step: `setup`, `release`, `curate` or `triage`.
  Take it, below, then return to this step once it completes -- `setup` in particular changes what
  every other check reads, so the honest next answer is a fresh call, not an assumption.
- **`could-not-decide`** -- a higher-precedence check could not be evaluated, so a clean answer from
  a lower one is not trustworthy. Report `blocked_on` and `reason` loudly, then fall through to
  **dispatch** below anyway: dispatching board work is never unsafe, it is only possibly not the
  most urgent thing, and that is worth saying rather than silently trusting a `nothing-due` this
  call never actually returned.
- **`nothing-due`** -- every check ran, resolved cleanly, and none fired. Proceed to **dispatch**.

## setup

No `.oss.json`, and `next_action.py` has already confirmed a probe is safe to attempt. Read
and follow `commands/run/setup.md` from here -- it measures the repo and writes the config; do
not guess values by hand.

## scaffold / install-audit / triage / curate / changelog / release

Each keeps its own procedure, unchanged, at its own file -- `commands/run/scaffold.md`,
`commands/run/install-audit.md`, `commands/run/triage.md`, `commands/run/curate.md`,
`commands/run/changelog.md`, `commands/release.md`. The first five moved out of `commands/`
(#1389): the plugin harness discovers slash commands from top-level `commands/*.md` only, never
recursively, so a file one directory down is not a picker entry at all -- reachable here, and by
the forcing override above, never by typing `/oss:setup` and so on directly any more.
`commands/release.md` stays where it is; see the picker note below for why. Read and follow the
one step 2 named (or the one `$ARGUMENTS` forced), then return to step 2 to ask again what is
needed now.

## dispatch

The ordinary cadence: read the board, decide what to build, delegate, review, merge on green. This
is `commands/tick.md`'s own procedure, unchanged. Read and follow it from here.

