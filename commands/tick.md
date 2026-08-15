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
   `--migrate` converts in place while keeping the original beside it. **A `FAIL` here stops the
   tick** — settle it, then start over at this step. `no entries yet` means a first tick and
   nothing else.

2. **Read the board.** The three ops every repo has, batched into one call:

   ```bash
   supertool 'gh-prs' 'gh-issues' 'gh-branch'
   ```

   Those three are the tracker. **Two more surfaces are part of this same board read**, because
   steps 3 and 5 decide from both — and neither is universally available, so each is ordered with
   the reading that tells you whether it applies. They belong here rather than in a step of their
   own: this is one question — what is true right now — and a board split across two steps is a
   board you can believe you finished before you reached the second half.

   **The watcher fleet — probe first, then run.** `radar` lives behind a preset and refuses when no
   tiers are registered, so do not reach for it blind. `radar:--state` is the read-only probe: it
   spawns nothing, reaps nothing and calls no API.

   ```bash
   supertool 'radar:--state'
   ```

   It has three answers and the third is not the first. **The preset is not enabled here, or no
   tier is registered** — there is no fleet to read, and the tick says so rather than passing over
   it. **Tiers are registered** — run bare `radar` and read its delivery tally. **The probe itself
   did not answer** — that is `unknown`, and it is reported, not skipped past.

   Read the tally, not the fact that the call succeeded: **forwarded is not delivered**. A poller
   that is down and a poller with nothing to say produce the same silence, so a channel nobody
   probed is **not a quiet channel** — it is a channel with no reading, and reporting it as calm is
   this loop's own defect class landing on the loop's own instrumentation.

   Bare `radar` heals and forks pollers. That is a write, not a read, which is the reason the probe
   is ordered separately rather than folded into it — you run the repair deliberately, having seen
   what needs repairing.

   **The worktrees — wherever `worktree_root` is set.** That key lives in `.oss.local.json`, the
   machine-local half, and never in the committed project config; a repo whose local half sets none
   has no worktree board to read, and that is a reading too.

   ```bash
   supertool 'git-worktrees'
   ```

   Which trees exist, who holds them and what merged is an input to step 3, not a step-5 cleanup
   detail. **Read both of its columns in three states, and never round the third one up.**
   `cannot tell` is not `idle`, and `merge unknown` is not `merged` — neither is permission: not to
   brief a second agent into that tree, not to reap it. The skill's cleanup gate carries the rest,
   including why the shell exit cannot be branched on.

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
