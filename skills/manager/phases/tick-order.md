# Tick order of operations: steps 1-6, and how a tick closes

**Read this when** a sub-manager's tick begins, right after `Skill(manager)` loads -- before step 1
of the tick, and again as the tick closes for "What ends a tick" below.

`commands/tick.md` stays the file `/oss:tick` documents and is what the scheduler itself is injected
with. It carries the spawn of `oss:sub-manager`, the seven-state handback classification and step
7 (arming the next wakeup) -- the three things the scheduler itself executes. This file carries the
whole of a sub-manager's own order of operations, split out for #1037: the scheduler used to load
steps 1 through 6 in full on every tick, ~13k tokens of a ~52k-byte file, for content only a
sub-manager's own context ever runs -- the same shape #695 already measured and split for the
manager skill, one file over. Nothing about *how* a tick runs changed; only which file carries it,
and `agents/sub-manager.md` points here directly rather than at `commands/tick.md` for these steps.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## Order of operations

**Steps 1 through 6 below, and "What ends a tick", are yours -- the sub-manager's, in your own
context.** Step 7 is not: it belongs to whichever session persists long enough to receive the next
wakeup, and that is `commands/tick.md`'s own scheduler, never you -- you have no `ScheduleWakeup`
tool, and you are gone by the time step 7 would run.

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

   **If a wait is still pending, test it before anything else in this tick (#337).** A wait's
   lifetime is not one entry -- `--pending-wait` finds the most recently recorded wait even behind
   entries that landed after it (a cohort freeze, a lane record, a plain intake), so this is not
   only about the tick's very last entry (#436).
   *Blocked on audit completion* is unfalsifiable prose and once outlived the audit it named by
   ninety minutes with nothing re-reading it — three hours ten minutes with a green default branch,
   an empty pull request board and four unstarted issues. Check for one directly:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --pending-wait
   ```

   `no pending wait` means proceed as normal. A record means test its `observable` against the
   repo or the tracker — whatever it names — right now, then record what you found before doing
   anything else this tick:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --decision "…" --at "<ISO timestamp>" \
     --check-wait cleared --wait-cleared-by "<what was actually observed>"
   # or: --check-wait holds          (tested, not yet observed)
   # or: --check-wait could-not-evaluate --wait-why "<why the observable could not be tested>"
   ```

   **`could-not-evaluate` is not `holds`.** `holds` is a measurement that came back negative;
   `could-not-evaluate` is no measurement at all, and rendering the two alike is the defect this
   field exists to close. Only record a fresh wait (`--wait-dispatch`/`--wait-observable` on step
   6's `--decision` call) when this tick itself becomes blocked on something new.

   **Compare this tick's plugin identity against the last one recorded (#477, #677).** A version
   change under a working loop invalidates every environmental fact the previous tick established,
   and nothing notices it unless this is asked directly. `${CLAUDE_PLUGIN_ROOT}` is a
   version-pinned path substituted once when this command was injected — asking THAT copy for its
   own version can only ever answer with the version it was pinned to, and will report `unchanged`
   straight through a real update (#677, observed: a real 0.14.0 → 0.15.0 update ten minutes
   earlier reported `unchanged`, because the check was structurally asking the 0.14.0 copy what
   version it is). Resolve the copy actually recorded as installed for this project instead, and
   fall back to the pinned path only when that resolution fails — naming which route was used,
   because the two are not the same measurement and comparing across them is #677's own second,
   independently observed failure mode:

   ```bash
   RESOLVED_ROOT="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_update.py" \
     --print-resolved-root --root . 2>/dev/null)"
   if [ -n "$RESOLVED_ROOT" ] && [ -d "$RESOLVED_ROOT" ]; then
     DOCTOR_ROOT="$RESOLVED_ROOT"
     ROUTE="resolved-install"
   else
     DOCTOR_ROOT="${CLAUDE_PLUGIN_ROOT}"
     ROUTE="pinned-root"
   fi
   DOCTOR_OUTPUT="$(python3 "$DOCTOR_ROOT/scripts/doctor.py" --root . 2>&1)"
   IDENTITY="$(printf '%s\n' "$DOCTOR_OUTPUT" | sed -n 's/^OK oss plugin version //p')"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --check-plugin-identity "$IDENTITY" --plugin-identity-route "$ROUTE"
   ```

   **#942: the same run already answers "is the installed copy behind the repository I am
   standing in", when that question can even be asked — read its line instead of discarding
   it.** The tick-to-tick comparison above answers "did this move since the last tick"; it
   cannot see a maintainer running an install that has never caught up with their own repo,
   because it only ever compares one tick's identity to another's. That is a different
   question from "is this the version of the repository I am standing in", and it only has an
   answer at all when the managed repo IS this plugin — every other repo has no such notion of
   being "behind". `doctor.py`'s own `check_plugin_copy` already asks exactly that question on
   every run — the SAME `$DOCTOR_OUTPUT` above already carries it — by comparing the checkout
   at `--root .` against the installed copy it ran from, byte for byte, and naming both
   manifests' versions the instant they disagree. Nothing needs to run twice; the line was
   simply thrown away by the `sed` above, which keeps only the `OK oss plugin version` line.
   Pull it out and say so before doing anything else this tick:

   ```bash
   PLUGIN_COPY="$(printf '%s\n' "$DOCTOR_OUTPUT" \
     | sed -nE 's/^(OK|WARN) plugin copy: //p' | head -n1)"
   ```

   `-E` rather than `\(OK\|WARN\)`: BSD `sed` (macOS, the platform this plugin is developed
   on) does not implement `\|` alternation in a basic regular expression at all — it is a GNU
   extension — so that spelling would silently match nothing on every macOS machine and every
   `sed -n` invocation above would need the same audit. `-E` is POSIX extended-regex mode and
   both BSD and GNU `sed` implement it.

   Five shapes, and only the first is worth a line in the tick record — the other four are
   this check correctly declining to say anything is wrong, exactly as narrow as #942 itself
   says the whole question is:

   - **`SKEW …`** — the checkout and the installed copy differ, and the sentence at its end
     names both manifests' declared versions. Report this prominently before anything else
     this tick, the same as `changed` above — prose this tick reads (`agents/*.md`,
     `skills/manager/**`, `commands/*.md`) may be a whole release older than the checkout that
     diagnosed it.
   - **`the copy that answered … and the checkout being diagnosed … are identical`** — nothing
     to report; the install is current with the repo it is managing.
   - **`doctor.py answered from the checkout being diagnosed …, so there is no installed-copy/
     clone split to report here`** — also nothing to report, and also clean, not
     could-not-tell: this is what a maintainer developing this plugin against its own working
     tree looks like (`$DOCTOR_ROOT` resolved to the same directory `--root .` names), the
     literal scenario #942's own motivation describes. A self-review on this same change caught
     an earlier draft of this list treating this exact shape as `could not be determined`,
     which would have reported a spurious ambiguity on the ticks #942 cares about most.
   - **`… is not a checkout of this plugin …`** — not applicable. The repo being ticked is not
     this plugin itself, so "behind the repo it manages" has no meaning here; say nothing
     further.
   - anything else (`could not be determined`, an empty `$PLUGIN_COPY`, doctor.py's own output
     not carrying the line at all) — could-not-tell, not clean. Say so rather than reading
     silence as one of the four states above.

   Four answers, not three. `unchanged` — proceed, say nothing further. `changed` — report it
   prominently before anything else this tick; whether to re-run the rest of doctor's diagnostic
   over it is a judgement call for this tick to make and name, not an automatic re-run. `could-not-
   tell` — no prior tick ever recorded one (a first tick after this shipped, commonly) — say so once
   rather than letting it read as `unchanged`. `route-mismatch` — the prior tick's reading was taken
   by a different route than this one (every repo hits this exactly once, on the tick this fix
   itself ships: the prior was recorded via the old pinned-root route). Treat it like `could-not-
   tell` for this tick — there is nothing comparable yet — and say so, rather than letting a route
   change silently read as `changed` (the exact shape #677's own comment warned a naive fix would
   produce for every repository on its first tick). Record this tick's own identity AND route on
   step 6's `--decision` call regardless of which of the four it found (`--plugin-identity
   "$IDENTITY" --plugin-identity-route "$ROUTE"`), so the next tick has a comparable prior.

   **Also snapshot `${CLAUDE_PLUGIN_ROOT}` itself, for a check within THIS tick (#565).** The
   comparison above is cross-tick, against the *previous* tick's recording. #565 asks a narrower,
   separate question: does the value this tick keeps substituting into every command move out from
   under it before this SAME tick ends — an update landing mid-session, which `plugin-currency.md`
   already says is not itself a fault. Snapshot it now; step 6 checks it once more just before the
   tick closes.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --record-plugin-root "${CLAUDE_PLUGIN_ROOT}"
   ```

2. **Read the board**, batched into one call:

   ```bash
   supertool 'gh-prs' 'gh-issues:per=100' 'gh-branch' 'git-worktrees'
   ```

   `gh-issues` bare caps at `--limit 50`, silently — a repo with 88 open issues reads as
   50, and the tick proceeds on a board that is short by 38 without anything saying so
   (#593). `per=100` raises the cap; it does not remove it, and a bigger repo hits the
   new ceiling the same way. **Read the footer, not just the rows**: `gh-issues` names
   its own population in three states — uncapped (every open issue is on screen),
   `capped at --limit N — more may exist, raise with per=N` (the fetch stopped short;
   read the count as "at least N", never as "the whole backlog"), or genuinely empty. A
   capped footer this tick is a fact to report and act on — raise `per=` again, or say
   in plain terms that the board was partial — never a silent floor for what "nothing
   left" means in step 7.

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

   **A wait is not an act, and it does not outrank dispatch (#820).** The three examples above are
   all work — verifying a merge, fixing a red branch, finishing an agent's uncommitted work. Watching
   CI go green is not: the run concludes at the same moment whether or not anybody is looking at it.
   Dispatch every lane that is ready to run before starting any wait — a lane runs concurrently with
   CI and with every other lane, so one started before the wait is free and one started after it pays
   the wait's whole duration on top of its own. Prefer polling (`gh-pr:N:status`, `gh-branch`) over a
   blocking `gh run watch`, which spends the whole turn watching and leaves nothing free to act on a
   handback that lands mid-run — sharper still given #818: a sub-manager cannot receive channel
   events, so the gaps between polls are the only responsiveness it has.

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

   **#302 asked whether the *merged* case above could skip the heal when nothing is left bare, gated
   on a cheap read instead of the event category — measured, not reasoned, before that rule was
   kept unchanged.** `radar:--state` looks like that cheap read. It is not one: it renders the tier, the
   filter and the pollers, and says outright that live coverage is "not resolved here, that would be
   a call" — it cannot answer *N watched* against *N open*. The only op that answers that is the bare
   `radar` heal itself. Timed back to back in this clone with nothing between the two calls (observed,
   2026-08-20): `radar:--state` returned in 2.31s without touching coverage; `radar` returned in
   11.46s and only then printed `1 open | 1 green | 1 watched`. A gate reading coverage before
   deciding to heal would pay the heal's own cost to decide whether to pay it, so there is no cheaper
   read to gate on — this route is not implementable as a saving, only as extra bookkeeping around a
   call already made. The issue's other route, gating the merge case on `gh-pr-merge`'s own receipt,
   needs that op to state whether a stacked follow-up exists; it does not today, so that is a filing
   against supertool's own tracker and not a diff here. The rule stays *board membership changed*,
   unconditionally, for both reasons at once — and it still errs toward running more than less, per
   the paragraph above.

5. **Decide, delegate, review, merge** — the skill governs each of these, and the gates in it are not
   optional. In particular: the check states must sum to the leg count, cleanup runs via the merge
   op's own `|cleanup` token gated on its `MERGED` read-back rather than a second raw call, a fleet
   holding more than one idle tree gets `skipped: reason` on the worktree half of that token and
   reaps the rest separately, and the default branch's own run gets checked after the squash.

   **Select in the dispatch order, and carry 1 to 3 issues per lane, never 4 (#798, #799).** The
   order is two axes — author before priority within a band, so a human ask outranks loop work of
   the same or lower band while a blocking-class defect the loop found still outranks an ordinary
   ask. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_rank.py"` is the one place that table
   lives; the spine's *Deciding what to build* states it and `skills/manager/phases/dispatch.md`
   says how a lane is filled from it.

   **Run `scripts/select_issues.py` (#970, #1036) as the dispatch-selection call itself, not
   `dispatch_rank.py` and the staleness/collision/claim reads joined by hand.** It composes
   `dispatch_rank.py`'s own ranking table — `dispatch_rank.py` stays the one place that table
   lives, and is what this call composes internally, not a separate call to run first — with the
   staleness (`preflight_check.py`) and lane-collision (`lane_setup.py`) checks and the assignee
   read (`issue_claim.py`) into one call, board in, ranked claimable candidates out. Three states,
   and the third must never render as the second: `candidates` (at least one issue survived, with
   the reason every dropped one was dropped), `none-available` (every input was read cleanly and
   nothing survived — a real, established absence), `could-not-select` (at least one input could
   not be read — never `none-available`, which is exactly the fold #970 exists to close). A tick
   that finds nothing ready and a tick whose claim or staleness read failed must not close
   identically as `nothing left`; this call is what tells them apart. It does not replace `--claim`
   below — reading who is claimable and writing a claim stay separate calls — and it does not
   invent a preflight or lane pattern for an issue that named neither (#267). Three issues is the
   default rather than the ceiling, and a
   lane dispatched with fewer says why in one of `board-exhausted`, `no-adjacent`,
   `did-not-search` or `could-not-tell` — and it fills a lane with the companion search (each
   candidate's declared lane against the top issue's, over the open board), never with `--against`
   between lanes already picked, which is the conflict check answering a different question (#918). A short lane with no reason is a defect in the tick -- and now one this loop
   can detect rather than only state: record every dispatched lane's fill with `--lane-fill
   PRIMARY:COUNT[:REASON]` on the same `oss_state.py --decision` call (#852), which refuses the
   whole call outright when a short lane arrives with no reason, the same way `--tick-cost-first`
   already refuses rather than writing a false value. `--lane-fill-trend` re-adds the reason
   distribution across the whole history, so a run of `could-not-tell` becomes a visible number.

   **This step is this tick's one dispatch, not the first of however many rounds a red lane takes
   (#880).** One fan-out here, filled per the rules above, and the tick then sees those lanes
   through to merge. A lane that comes back red, or whose base moves under it, is resumed via
   `SendMessage` to its own agent -- never re-dispatched fresh at the same issue -- unless that
   agent is genuinely gone (context died, or resumed and silent twice), which is its own named
   state, `agent-unreachable`, and not a silent excuse to spawn again. The full argument, the cost
   comparison and the exact state names are in `skills/manager/phases/dispatch.md`; a re-dispatch
   with neither an attempted resume nor an `agent-unreachable` finding behind it is the defect this
   note exists to stop. **Record it, at step 6's own `--decision` call, with `--lane-dispatch-state
   ISSUE=STATE[:WHY]`** -- it refuses the whole call outright rather than only being read.

   **When delegating a new issue, name `scripts/lane_setup.py` in the brief instead of typing the base
   commit and the worktree list into it by hand.** Both rot between the moment this tick reads them and
   the moment the dispatched agent does — `main` has moved mid-tick before, and a hand-copied worktree
   list has already flattened `cannot tell` to `idle` once (#317). The brief names the script and the
   issue number; the dispatched agent runs it as its own first call and gets the resolved base, the
   derived branch and worktree, and the condensed board back, freshly re-derived rather than pasted:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --claim --lane <pattern> [--lane <pattern> ...]
   ```

   Run from the clone, before `git worktree add` — that is where `.oss.local.json` is present and
   `worktree_root` resolves. Three states apply throughout, same as everywhere else in this file:
   `resolved-stale` is not `resolved`, `could-not-resolve` blocks (exit 3) rather than guessing a base,
   and a `worktree_root` absent from this tree (as it always is inside a worktree this loop already
   cut) reads `unknown`, never a guessed path.

   **`--claim` registers this lane in the worktree-root registry (#705); omit it for any earlier
   disjointness probe on a candidate that might not be dispatched** — a probe that carries `--claim`
   leaves a phantom record behind that can block a later `--derive-held` call for hours.

   **`--claim` refuses without `--lane` (#788)** — a fileless claim used to poison every later
   `--derive-held` call this tick, for every other candidate probed after it, because the held set
   could no longer be trusted complete while a lane with no known files was live. Pass the same
   `--lane` patterns this candidate was already probed with.

   **The merge call needs `|force`, and that is not a bypass.** `gh-pr-merge:N:squash` with no
   suffix previews its gate and merges nothing; `|force` is the confirmation, and every refusal the
   op makes still applies. Settle this before the first tick rather than at the merge step, where
   the review is already spent — see *Before the first tick* in `skills/manager/phases/merge.md`.

   **Compose each spawn's `description` with `scripts/fleet_label.py`, not by hand (#539).** A lane
   carrying three issues and a lane carrying one used to render identically in the fleet view — the
   label named only the first issue. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_label.py" <primary>
   <every issue this lane carries, comma-separated> "<phrase>"` prints `Lane <primary> x<N>  <phrase>`
   and refuses to print anything when the bundle is incomplete — *Run a fleet, not a queue* in
   `skills/manager/phases/dispatch.md` has the full convention. Paste its stdout as the `Agent`
   call's `description`.

6. **Write one state entry, and record the intake ratio with it.** The decision and the one reason
   for it. Reasoning that only matters to a pull request belongs in that pull request.

   **First, check the root snapshot step 1 recorded, before it is overwritten by the next tick's own
   recording (#565).** `changed` means `${CLAUDE_PLUGIN_ROOT}` moved out from under this very tick —
   report it, the same as step 1's `changed` for the cross-tick comparison. `unchanged` — say
   nothing further. `could-not-read` — step 1's snapshot was never taken (or something already
   consumed it) — say so once rather than letting it read as `unchanged`.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --check-plugin-root "${CLAUDE_PLUGIN_ROOT}"
   ```

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --decision "…" --at "<ISO timestamp>" \
     --filings <issues carrying labels.filed_by_loop, opened since the last tick> \
     --merged-prs <PRs merged> \
     --window "since the last tick" \
     --plugin-identity "$IDENTITY" --plugin-identity-route "$ROUTE" \
     --tick-cost-session "$CLAUDE_CODE_SESSION_ID" --tick-cost-window "this tick" \
     --tick-cost-start-ctx unknown --tick-cost-calls unknown --tick-cost-context-carried unknown \
     --tick-cost-why "no live token-usage read available to this tick"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --trend
   ```

   `--plugin-identity "$IDENTITY" --plugin-identity-route "$ROUTE"` is step 1's own reading and its
   route (#477, #677), carried onto this entry so the next tick has a *comparable* prior — see step
   1 for what the four-state comparison means, and why the route travels with the identity rather
   than being assumed to match.

   Pass `unknown` for a count you could not take, with `--intake-why` — **`could-not-count` is not
   zero**, and a metric that renders the two alike is worse than none. The denominator, the
   authorship rule, the label that makes the numerator derivable rather than recalled (#762), and why
   no target ratio is claimed are in the skill under *Intake: filings per merged pull request*.

   **Record what this tick cost to *carry*, in the same call (#694).** A tick's own dollar cost
   points at the wrong ticks — ranking 48 ticks by cost said twelve were expensive; ranking the same
   ticks by context inherited at their start explained why, and it was not that they did more work.
   `--tick-cost-session "$CLAUDE_CODE_SESSION_ID"` is a real, observable value — Claude Code sets it
   in the environment, so it costs nothing to read and nothing to invent. Pass `--tick-cost-first`
   only on the very first `--decision` this running session writes: that tick's own `start_ctx`
   becomes the session's floor, and every later tick in the same session finds it automatically by
   scanning the state file for an earlier entry carrying the same session id. **If you are not certain
   this is genuinely the session's first tick — a resumed session, for instance — omit
   `--tick-cost-first` rather than guess**; the CLI refuses it outright if this session already has an
   earlier entry, resolved floor or not, rather than silently writing a false one — and a false floor,
   once written, would never be corrected by anything later. The block above is deliberately the
   *later*-tick shape; on the one call this session ever makes as its own first tick, append the flag:

   ```bash
     … --tick-cost-why "no live token-usage read available to this tick" \
     --tick-cost-first
   ```

   **`start_ctx`, `calls` and `context_carried` are not reliably readable from inside a running tick
   today.** Nothing in this loop currently hands the ticking agent a live token count. Pass `unknown`
   for all three with `--tick-cost-why "no live token-usage read available to this tick"` — **do not
   estimate a number**, the same rule `--filings unknown` already follows; a guessed figure sitting in
   the history is worse than an honest `could-not-measure`, because nothing downstream knows to
   distrust it. If your environment genuinely exposes a usage read, pass the real numbers instead —
   the CLI does not care where they came from, only that they were measured rather than guessed.

   **If this tick is closing blocked (#337), attach the wait to the same `--decision` call** rather
   than leaving it in the `reason` string alone:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
     --decision "blocked on the gate 3 audit" --at "<ISO timestamp>" \
     --wait-dispatch "<what was set in motion>" --wait-observable "<what clears it>"
   ```

   Step 1 of the *next* tick is what tests this, via `--pending-wait` and `--check-wait` — see
   above. Recording a wait here without step 1 testing it next time is the same failure with the
   test simply never run.

## What ends a tick

**This is the sub-manager's own declaration**, made in the `TICK-ENDS:` field of the `TICK:
completed` handback above (#773) — the scheduler reads it there rather than re-deriving it or
parsing the paragraph for it. Not the wakeup. The wakeup is a safety net, and the tell that this
went wrong is a closing line describing the schedule instead of the next action. Waiting on CI is
not a reason to stop working.

**And only one of three states is an end.** Say which one, in as many words, as the tick closes
(#244):

- **Work started** — something was delegated in this tick. Name what and where it is running. The
  tick continues; do not arm a wakeup and wait on it.
- **Blocked** — every remaining open item named individually, each with what it waits on and who
  owns that. **A count is not a naming**, and neither is *the rest are blocked*: if you cannot write
  the list, you are not in this state. Still not an end.
- **Nothing left** — `gh-issues` and `gh-prs` both answered, and both came back empty. **Your own
  backlog was never somebody else's work**, so an open issue this loop filed is not this state. It
  ends the tick; step 7 — the scheduler's own job, reading this declaration back from the handback —
  is what arms the long wakeup and says this does not stop the loop.

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
