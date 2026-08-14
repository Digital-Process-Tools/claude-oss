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
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" --help
   ```

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

   Both halves are in the skill under *What comes back is a file, not a document* and *Opening the
   pull request*, including why the op rather than `gh pr create` and why reading the body is what
   makes this a saving rather than a trick.

5. **Decide, delegate, review, merge** — the skill governs each of these, and the gates in it are not
   optional. In particular: the check states must sum to the leg count, cleanup is a separate call
   gated on the verified merge result, and the default branch's own run gets checked after the squash.

   **The merge call needs `|force`, and that is not a bypass.** `gh-pr-merge:N:squash` with no
   suffix previews its gate and merges nothing; `|force` is the confirmation, and every refusal the
   op makes still applies. Settle this before the first tick rather than at the merge step, where
   the review is already spent — see *Before the first tick* in the manager skill.

6. **Write one state entry.** The decision and the one reason for it. Reasoning that only matters to
   a pull request belongs in that pull request.

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
