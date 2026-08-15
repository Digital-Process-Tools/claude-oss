---
description: Run one maintainer tick — read the board, decide, delegate, review, merge on green.
allowed-tools: Bash, Agent, Skill
---

One pass of the maintainer loop over the repo named in `.oss.json`.

Load the loop itself first — it carries the judgment this command only sequences:

```
Skill(manager)
```

## Order of operations

1. **Read the state file** named by `state_file`, then **`git fetch && git pull --ff-only`**. The
   state file records what was *believed* when it was written. The repo is what is true.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --last
   ```

   **Actually run it, here, before any work.** This step used to print `--help`, which reads the
   CLI and not the file — so the first thing that touched the state file was step 6, and a repo
   whose file the script cannot use spent a whole tick before finding out (#149). A `FAIL` on this
   line names what is wrong and what to run; the common one is a state file written by a
   pre-plugin maintainer loop, an object keyed `tick_<ISO>` rather than a list of entries, which
   `--migrate` converts in place while keeping the original beside it. Do that first. `no entries
   yet` means a first tick and nothing else.

2. **Read the board**, batched into one call:

   ```bash
   supertool 'gh-prs' 'gh-issues' 'gh-branch'
   ```

3. **Act on what is open before starting anything new.** A merged-but-unverified PR, a red default
   branch, or an agent whose work is sitting uncommitted all outrank the next issue. Finishing beats
   starting.

4. **Take the handback, then push and open the pull request.** An agent replies with a path. Push its
   branch, read the report's fields as you need them, **read the pull request body it wrote**, then
   hand that path over — one call, no body of your own:

   ```bash
   supertool 'gh-pr-create:@<pr_body.path from the report>'
   ```

   **That line is the `written` case only.** Reading `pr_body` has three answers — `written`,
   `not-written`, and a path that is named but could not be read — and the third is not "no pull
   request to open". Check the state before you type this; the skill's *Opening the pull request*
   says what each one costs you.

   Both halves are in the skill under *What comes back is a file, not a document* and *Opening the
   pull request*, including why the op rather than `gh pr create`, why reading the body is what
   makes this a saving rather than a trick, and which of `head` and `base` the validator actually
   checks — neither is yours to retype.

5. **Decide, delegate, review, merge** — the skill governs each of these, and the gates in it are not
   optional. In particular: the check states must sum to the leg count, cleanup is a separate call
   gated on the verified merge result, and the default branch's own run gets checked after the squash.

   **The merge call needs `|force`, and that is not a bypass.** `gh-pr-merge:N:squash` with no
   suffix previews its gate and merges nothing; `|force` is the confirmation, and every refusal the
   op makes still applies. Settle this before the first tick rather than at the merge step, where
   the review is already spent — see *Before the first tick* in the manager skill.

6. **Write one state entry, and record the intake ratio with it.** The decision and the one reason
   for it. Reasoning that only matters to a pull request belongs in that pull request.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --decision "…" --at "<ISO timestamp>" \
     --filings <issues the loop filed> --merged-prs <PRs merged> \
     --window "since the last tick"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --trend
   ```

   Pass `unknown` for a count you could not take, with `--intake-why` — **`could-not-count` is not
   zero**, and a metric that renders the two alike is worse than none. The denominator, the
   authorship rule and why no target ratio is claimed are in the skill under *Intake: filings per
   merged pull request*.

7. **Arm the next tick, and keep working in this one.**

   ```
   ScheduleWakeup(delaySeconds=…, prompt="/oss:tick", reason="<what specifically is outstanding>")
   ```

   Agent completions notify for free — never poll for them. CI is the only thing that needs a timer.
   If nothing is outstanding but somebody else's work, stop the loop with `stop: true` **and say so
   out loud**: a loop that stops silently is indistinguishable from one that was never armed.

## What ends a tick

Not the wakeup. The wakeup is a safety net, and the tell that this went wrong is a closing line
describing the schedule instead of the next action. Waiting on CI is not a reason to stop working.

## If `.oss.json` is missing

Stop and say so. `/oss:setup` writes it. Do not proceed against guessed values — a guessed default
branch merges into the wrong place, and it does it confidently.
