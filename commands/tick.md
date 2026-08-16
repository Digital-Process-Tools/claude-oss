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

2. **Read the board**, batched into one call:

   ```bash
   supertool 'gh-prs' 'gh-issues' 'gh-branch' 'git-worktrees'
   ```

   The fourth op is the one this step used to be missing, and it is not conditional:
   `git-worktrees` is available wherever supertool is, and it boards every tree of this repo
   whether or not anything configured a root for them. `worktree_root` in `.oss.local.json` names
   where this loop puts its own — but **the board is not gated on that key**, because a tree nobody
   configured is still a tree, and skipping the call in a repo that sets no root reproduces exactly
   the absence this step exists to close: a worktree board nobody read renders as no worktrees.

   Which trees exist, who holds them and what merged is an input to step 3, not a step-5 cleanup
   detail. **Read both of its columns in three states, and never round the third one up.**
   `cannot tell` is not `idle`, and `merge unknown` is not `merged` — neither is permission: not to
   brief a second agent into that tree, not to reap it. The skill's cleanup gate carries the rest,
   including why the shell exit cannot be branched on.

   **Then the watcher fleet, which is conditional — probe first, then run.** It gets its own call
   for two reasons, not one: `radar` lives behind a preset and refuses when no tiers are
   registered, so reaching for it blind is a refusal rather than a reading; and the bare call is a
   write. `radar:--state` is the read-only probe — it spawns nothing, reaps nothing and calls no
   API.

   ```bash
   supertool 'radar:--state'
   ```

   It has three answers and the third is not the first. **The preset is not enabled here, or no
   tier is registered** — there is no fleet to read, and the tick says so rather than passing over
   it. **Tiers are registered** — run the heal below. **The probe itself did not answer** — that is
   `unknown`, and it is reported, not skipped past.

   **A tier that resolved over `pollers : none` is the second answer, not the first.** That is the
   case the heal exists for, and it is the one that reads like the absence of a fleet: a repo which
   registered a board and has never spawned a poller prints an empty list, exactly as a repo with
   no board would. What settles which answer you are in is whether the probe resolved a tier module,
   never how long its poller list is. Read it the other way and the board stays unraised across
   every tick that repo ever runs, with nothing anywhere reporting a fault.

   ```bash
   supertool 'radar'
   ```

   Bare `radar` heals and forks pollers. That is a write, not a read, which is why the probe is a
   separate call rather than folded into it — you run the repair deliberately, having seen what
   needs repairing. It respawns watchers for open pull requests with no live poller and puts the
   default branch on the board as a member, which is the red-default-branch case no pull request
   covers. `radar:--state` buys none of that: it spawns nothing and reaps nothing, so a tick that
   only probes has reported a fleet it also declined to bring up.

   **The heal has its own three outcomes, and they are not the probe's.** *Raised* — the tiers
   resolved and the board printed; report its counts. *Not configured* — no tier is registered, so
   the op refuses by design and names the fix. That is the correct state for a repo that never opted
   in, it is where most managed repos are, and it **must not be reported as a failure**. *Could not
   raise* — it is registered and it still did not run, and the step says which: the `watch` preset
   is absent from `presets`, which `/oss:doctor` reports as `no-route` — not its `route-unknown`,
   which is the different answer for a `presets` key that could not be read at all — or the spawn
   itself errored. A heal that errored and a heal that found nothing to repair both end with no new
   watcher, so `could not raise` is reported as itself or it is indistinguishable from a fleet that
   was already up.

   **This is not the tick's only heal, and it is the one that covers the least.** Radar has no
   discovery feed — its own board footer says `discovery: radar ticks only` — so this run arms
   pollers for what is open *at the moment it runs* and for nothing opened after. Step 4 states the
   rule that governs every later one, and *What ends a tick* is where it gets measured.

   **Relay the probe's channel line rather than swallowing it.** When `.supertool.json` declares no
   `watch_name` in any op block, the channel name came from the environment, and the probe says so
   in as many words: this socket and these poller slots **may be another project's fleet**. The heal
   is a write into whatever that name resolves to, so a tick that forks pollers without repeating
   the line has reported a repair it cannot attribute — and an attribution nobody can check is worth
   less than one nobody claimed.

   Read the tally, not the fact that the call succeeded: **forwarded is not delivered**. A poller
   that is down and a poller with nothing to say produce the same silence, so a channel nobody
   probed is **not a quiet channel** — it is a channel with no reading, and reporting it as calm is
   this loop's own defect class landing on the loop's own instrumentation.

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

   **Then heal the board again, because you have just changed what is open.**

   ```bash
   supertool 'radar'
   ```

   **The rule is *board membership changed*, and it is deliberately not a list of places to heal.**
   A list is easier to follow, and this file already had one: #187 added the probe and #208 added
   the heal, and both landed in step 2 because that is where the board read was. So the pull request
   the tick itself opened had no poller for its entire CI run, and the loop fell back to polling
   `gh-pr:N:status` in a shell without ever noticing why it had to (#242). A list is complete until
   somebody adds a step, and then it is wrong silently — the failure it produces is a missing
   poller, and a missing poller is a silence.

   Three cases the rule covers, and **one of them has nothing to heal at all**, which is the fact
   that decides this rather than a preference for rules over lists:

   - **A pull request was opened.** It has no poller, radar cannot discover it, and the heal is the
     only thing that arms one.
   - **A pull request merged or closed.** Its poller is correctly reaped, and a stacked follow-up
     needs its own. Note that `No active watchers` is the **expected** state right after a merge and
     the **defect** state right after an open — the same words for both, so the board's open count
     is what tells them apart, never the watcher list on its own.
   - **The default branch went red under a squash** — and here there is **no poller to heal**.
     Radar carries the default branch as a *member row*, answered by composing `gh-branch`'s own
     `GREEN` / `NOT GREEN` / `NO RUN` / `UNKNOWN`, and `N watched` never counts it. Nothing can be
     armed for it; it is re-answered on each radar run. So this case is fixed by reading the board
     again and by nothing else, and no list of heal sites could ever have contained it.

   It cannot double-arm — a slot already alive is neither healed nor respawned — which is why the
   rule errs toward running it more often rather than less. **What it is not is free**, and "one op"
   understates it: each bare `radar` is a board read, so it lists the pull requests, reconciles the
   check legs of each and re-answers the default branch. Following this rule takes a tick from one
   such read to three. That is the price of the fix and it is deliberate: the alternative is a
   poller that was never armed, and a missing poller reports as a quiet board.

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
   If nothing is outstanding but somebody else's work — a review, a CI run, an upstream fix, and
   **never your own backlog** — stop the loop with `stop: true` **and say so out loud**: a loop that
   stops silently is indistinguishable from one that was never armed. Which of the three states
   below you are in decides whether that sentence applies at all.

## What ends a tick

Not the wakeup. The wakeup is a safety net, and the tell that this went wrong is a closing line
describing the schedule instead of the next action. Waiting on CI is not a reason to stop working.

**And only one of three states is an end.** Say which one, in as many words, as the tick closes
(#244):

- **Work started** — something was delegated in this tick. Name what and where it is running. The
  tick continues; do not arm a wakeup and wait on it.
- **Blocked** — every remaining open item named individually, each with what it waits on and who
  owns that. **A count is not a naming**, and neither is *the rest are blocked*: if you cannot write
  the list, you are not in this state. Still not an end.
- **Nothing left** — `gh-issues` and `gh-prs` both answered, and both came back empty.

**An unread board is not an empty one.** If either call did not answer, that is `unknown`, it is not
the third state, and the tick says which call failed and what went unread instead. A tick that
stopped because there was nothing to do and a tick that stopped because it did not look otherwise
close on the same line. A release is a step in this list too — the tag is when merged work becomes
reachable by the running loop, so the tick after one has more to do, not less (#235).

**And not while the board says something is unwatched.** Step 4's rule is easier to skip than a
list would be — that is the one thing a list is better at — so the anchor is a *measurement* taken
at the end, not a reminder placed at the top. Read the board once more before the tick closes:

```bash
supertool 'radar'
```

Read radar's own tokens, not the fact that the call succeeded. It already renders all three states,
so nothing here computes anything:

- **Covered** — the summary carries `N watched` with the same `N` as `N open`, and no row carries
  `[unwatched]`. Read the two tokens, not their adjacency: `N failing`, `N running`, `N green` and
  `N unchecked` are printed between them whenever they are non-zero, so `N open | N watched` is what
  a quiet board happens to look like rather than the shape to match on. `0 open | 0 watched` is this
  state and not a gap; there is nothing to watch.
- **A gap** — a row marked `[unwatched]`, or `N unwatched` in the summary line. Name the pull
  request. The heal in step 4 is what clears it, and a tick that ends here says which one is bare
  and that the fleet cannot find it by itself.
- **`watch coverage UNKNOWN`** — the board is about a repo whose PR numbers cannot be told from this
  clone's, so nothing was healed and nothing *could* be. That is the third state, it is not the
  first, and reporting it as a covered board is this loop's own defect class landing on the loop.

A terminal condition rather than a sixth entry on a list, so a step added later cannot escape it.

## If `.oss.json` is missing

Stop and say so. `/oss:setup` writes it. Do not proceed against guessed values — a guessed default
branch merges into the wrong place, and it does it confidently.
