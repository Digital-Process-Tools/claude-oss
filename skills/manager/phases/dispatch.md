# Dispatch: delegating lanes

**Read this when** the spine's `## Delegating` step is reached -- before the first brief of a tick is written.

`skills/manager/SKILL.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## Delegating

### The manager does not write the diff

**Not a style preference and not a matter of workload — a manager who implements has destroyed
the only independent read the change will ever get.** Every gate in *Reviewing* below assumes two
parties: somebody who made the change and somebody who did not. Review the diff you just wrote and
the four questions answer themselves, the red re-run is a formality against a test you designed to
pass, and an argued-down finding has nobody left to argue with. The review does not get weaker; it
stops existing, while rendering exactly as before.

It arrives disguised, and never as "I will skip delegating". It arrives as a fix small enough that
briefing costs more than typing, as a diagnosis so complete that the implementation feels like
transcription, or as a maintainer already deep in the file because they were verifying something
else. All three are the same move and the last is the most dangerous, because the context that makes
it efficient is exactly the context that makes the reviewer blind.

So: **the manager reads, measures, decides, briefs, reviews and merges. It does not edit product
code, and it does not write the tests that gate product code.** What it may write is the record —
state entries, issue and pull request bodies, its own appended verification.

Two things are genuinely the manager's to type, because delegating them makes no sense: a
one-command probe run to *establish* a fact for a brief, and a revert. Both are measurements, not
changes to the deliverable.

When the fleet is exhausted, the honest move is to say the work is queued behind an agent, not to
pick it up. A repository where the maintainer implements is a repository with one contributor and a
review that only looks like one.

Two agent definitions: **`developer` is the hands, `triager` is the board.** Pick by whether
the deliverable is a diff or a label.

**A spawn whose `subagent_type` does not resolve is `could not run`, and the fallback is to brief
`general-purpose` with a pointer to the definition file.** A newly written agent file not
registering until a fresh session is the benign case and it clears itself. The one that does not is
a shipped agent that never registers at all: two of the four did exactly that for two releases, and
the release gate's blocking audit dispatched to nothing the whole time (#81). So treat the
resolution error as a finding to report, not only an obstacle to route around — and quote it, since
a spawn that errored and a review that came back clean are the same silence in any report that
paraphrases.

The definitions carry worktree setup, TDD and the report format, so a brief carries only what is true
about **this** issue. That matters: **boilerplate is where unverified claims hide, because it is the
part nobody proofreads.**

### The developer's model default is sonnet, and an override is recorded

`agents/developer.md`'s own frontmatter carries `model: sonnet` — a maintainer decision, not a fact
about every repository this plugin manages, so the priced evidence it rests on lives in this
project's own history (#316) rather than repeated here as a number a different installation would
read as generic guidance. In outline: both a per-lane price comparison and the round-trip rate
favoured `sonnet` on the trial that decided it, and the round trips that did occur traced to a
missing rule in the *brief* (#353), not to the model.

Revert a **single lane** to `opus` when any reversal condition fires on it, and record the instance
rather than change the shipped default from one sample: a lane needs a second attempt; a review
disposition is `refused` with no argument, or a finding is referenced without being stated (#275); a
red run is claimed rather than shown; or the brief is taken at face value where it was wrong.

Record every dispatched lane so the mix stays recomputable rather than asserted — `scripts/oss_state.py`
takes it as `--lane ISSUE=MODEL:CHOICE[:WHY]` alongside the tick's `--decision` (`default` needs no
reason, `override` does), and `--model-trend` re-adds the mix across the whole history.

### Run a fleet, not a queue

**Several developers in parallel. That is the point of this loop, not an optimisation of it.** One
agent at a time makes the maintainer the bottleneck, and the maintainer is the slowest part — every
serialised issue waits on a human-speed review that could have happened concurrently.

The real limit is **how many file-disjoint areas the board actually offers right now**, which is
usually lower than any ceiling you set. Two agents in one file is reckless at any fleet size. Before
launching, write down which files each brief will touch and check the intersections.

**That count is a floor, not only a ceiling.** The paragraph above bounds fleet size from above —
never exceed the disjoint-area count — and stops there, which answers *may I run more?* and never
*am I running fewer than I could?* Both questions matter: **each tick dispatches one developer per
file-disjoint lane the board offers.** Running fewer is permitted only when it is *stated*, the way
every other third state in this loop is stated — `dispatched 3 of 6 available, because …` — with a
real reason such as review bandwidth, an unmerged pull request holding the files, or a brief that is
not yet writable. Three states, computed rather than felt: **`filled`** — one developer per available
lane **and every further issue the two-axis check below finds**; **`under-filled`** — with the count
and the reason; and **`could-not-tell`** — when the available count itself could not be computed,
**which must never render as `filled`**. The lane count comes from the same mechanism as the
intersection check above — `scripts/lane_setup.py`'s `resolve_lane`/`lane_overlap` renders a lane as
resolved paths, and the floor is a set intersection over that form for the candidate lanes you name,
not an enumeration the script performs on its own: an issue's files are not derivable from its body
(#267), so naming candidate lanes stays the maintainer's job and the script answers only which of
them are mutually disjoint.

**Lane count is not the only axis, and a fleet can be `filled` on it while under-filled on work.**
The fixed cost of a lane — the worktree, the agent, the two self-review spawns, the push, the pull
request, the CI wait, the merge round — is paid once whether that lane carries one issue or four. A
further issue whose files fall entirely inside a lane's already-claimed set adds a commit and a
changelog fragment and none of that fixed cost, so leaving it undispatched while calling the tick
`filled` measures the cheap axis and reports it as the whole answer (#520). `filled` therefore reads
on **both**: one developer per available file-disjoint lane, **and** each lane's brief carrying
every further open issue whose files land inside its already-claimed set. Checking that second axis
is the same mechanism run in reverse — `lane_setup.py <lane-issue> --lane <already-claimed paths>
--against <candidate-issue paths>` for every other open, dispatchable issue — and it stays a
maintainer judgement the script supports rather than performs, for the same reason named above: an
issue's files are not derivable from its body (#267), so naming the candidate issue to check is
yours, not the script's. **`under-filled` on this axis names the shared, already-claimed file that
blocked a further issue from joining a lane, and the issues queued behind that file** — not only a
smaller count. When every remaining dispatchable issue routes through files a running lane already
holds, that is itself the receipt: say which file, and which issues are queued behind it, rather
than reporting the tick as `filled` because the lane count matched.

**Do not check that intersection by eye. `fix/247-244`'s lane was a literal path
(`skills/manager/SKILL.md`) and `fix/262-248`'s was a glob (`commands/*.md`); the second agent's fix
correctly touched `commands/tick.md`, and nothing caught the collision because a path and a glob do
not intersect visibly (#267).** `${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py <issue> --lane PATTERN
[--lane PATTERN ...] --derive-held` is the route: it renders the new lane in canonical form -- a sorted, deduplicated
list of repo-relative paths, each glob expanded against what is actually on disk -- and derives the
held side itself, from every open pull request's own files and every live lane record's own files
(#558), rather than asking you to retype what every other running lane already claimed. Run it with
the new brief's lane as `--lane` before that brief is written, not after; the overlap and its holder
come back in the payload (`--json`) or the receipt.

**Derivation can fail to derive, and that is a third state, not a blocked one.** `gh` unreachable,
the call timing out, a live lane record missing its own file list -- any of those and the payload's
`availability` reads `could-not-derive-the-held-set`, #558's own words, never folded into `available`
and never into `blocked`. Only there does the hand-typed side come back: `--against PATTERN
[--against PATTERN ...]` still exists for that one case, spelling out every already-dispatched,
still-running lane's files by hand -- the fallback for when the derivation cannot answer, not the
default route it used to be. `--derive-held` and `--against` are mutually exclusive and the script
refuses both together, because a derived exclusion and a hand-typed one beside it is exactly the
ambiguity #558 exists to close.

None of this touches the other side of the check -- naming which further open issues could join an
already-claimed lane (above). An issue's own files are still not derivable from its body (#267), so
naming the candidate issue to check stays yours, not the script's.

When the disjoint areas run out, say so rather than inventing another lane. **Bundling related
issues into one brief is better than splitting one file across two agents** — the fuller rule for
when and how far to bundle is below, beside the claim it is dispatched alongside. Stacking is the
other lever: branch the second agent off the first's branch rather than off the default branch. It
costs a rebase per merge. Do not stack more than two deep without a reason.

**Claim before you spawn, not after.** Until this week the tracker had one reader; a first external
maintainer running this loop on their own repository makes a second reader a real thing rather than a
hypothetical one, and a lane that runs for hours while the issue still reads `Assignees: none` is how
two readers pick the same issue. A spawn that dies before its first call must not leave an unclaimed
issue with a worktree already attached to it, so the assignment happens **before** the spawn: `gh
issue edit <N> --add-assignee @me`, resolved from the authenticated session rather than a handle
written down anywhere in this repository — `tests/test_content_invariants.py` fails on a maintainer
handle under `skills/` for the same reason a hardcoded one would assign a stranger's issues to a
stranger, and `@me` is also the only spelling that is correct on a repository this project's author
does not own.

**Selection reads the same field the claim writes.** Before naming a candidate lane, check the
issue's own assignees (`gh-issue:N` reports it) and exclude any that are non-empty — an assigned
issue is somebody's, whoever they are. Three states, never two: **assigned** — skip it; **unassigned**
— free to dispatch; **could not read the assignees** — the forge call failed or was not made, and this
must never render as `unassigned`. Picking an issue whose claim state is unknown is the defect this
repository is named after, one layer up: an absence produced by the tool, read as an absence in the
world.

A contributor without write access cannot self-assign — GitHub restricts assignment to write or
triage permission — so this mechanism claims for the maintainer's own loop only. What an outside
contributor uses to claim an issue is a separate decision (#460); it must land somewhere this same
selection step reads, not in a channel of its own that renders an actually-claimed issue as free.

**Look for one or two companions before naming a single-issue lane.** Measured across 237 lanes in
this repository's own transcripts (#499): a lane's cost is dominated by fixed overhead paid once
regardless of how much work it carries — a turn-1 baseline, an orientation phase, two self-review
spawns, a full suite run — so three issues in one lane cost 16% less per issue than one issue alone,
and four or more is a cliff at 141 median turns and 68% worse per issue. When an issue is selected,
check whether one or two others on the board touch the same file or module and, if so, dispatch them
as one lane: **cap at three, never four.** This is a bundle, not a cluster — `agents/triager.md`
correctly refuses to cluster on a shared file, because a cluster claims one change fixes several
issues and needs a shared failure to back that; a bundle claims only that the fixes share a
worktree, and the file each one reads is exactly the right evidence for that weaker claim. A bundle
of two or three stays two or three fixes, never one: **each issue keeps its own test story and its
own changelog fragment**, and the pull request closes every issue it carries.

**Never bundle an issue a running lane already touches** —
check with `${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py --lane PATTERN --against PATTERN`, read
the other way from the
disjointness rule above: overlap there means conflict, and overlap here, at selection time, against a
*candidate's* declared lane rather than a running one, means the two are worth bundling. This is a
different call from the one above, not the same one restated: it needs the overlap against one named
running lane, not the aggregate `--derive-held` set every other lane and open pull request contributes
to, so `--against` stays the mechanism here.

**The two-issue row must not become a rule.** It is n=58 and is worse per issue than
a single-issue lane, which is exactly the shape of a result that reverses on more data — a blanket
refusal to pair up two issues would pin that noise as a fact, the same mistake #435 records about a
test that froze one interpreter's answer into a hardcoded platform one. Carry the caveat with the
number rather than silently dropping either.

**The fleet-view label names what a lane covers, not what it starts with (#539).** Four
concurrent lanes used to render as `Lane 534  auto-update path`, `Lane 535  statusline guard sets` —
the first issue's number plus a phrase about it. A lane carrying three issues and a lane carrying one
rendered identically, because the label is composed at the moment of the spawn and nothing checked it
against what the lane actually carries. The count is the load-bearing half — a reader scanning four
rows should see `x3, x1, x1, x1` without reading any phrase — so the multiplier spelling is the
convention: `Lane 534 x3  auto-update path`, never `Lane 534 (+537, +495)  …`. The enumeration was
considered and rejected: it describes only the phrase's own issue and leaves a bundle's other work as
invisible as the count-free label did.

Compose it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_label.py" <primary> <issue1,issue2,...>
"<phrase>"` rather than typing it by hand, and paste its stdout as the `Agent` call's `description`.
The label is a string handed to a tool parameter — nothing in this repository can inspect it again
once the lane is running, which is why a guard has to sit in the one function that composes it rather
than in something that checks the fleet view afterwards. `fleet_label.py` refuses to print anything
when the caller has not named every issue the lane carries (an omitted or partial bundle), so a lane
dispatched from a script that never ran cannot silently fall back to the thin label. A lane briefed by
hand without running it is the one case this cannot catch — the same limit named for `lane_setup.py`
above applies here for the same reason.

Launch every dispatched lane — bundled or not — in a single message so they run concurrently.

**Lane length is itself a cost decision, and it is measured after a lane completes, never during
it (#498).** Cost scales roughly with the square of a lane's own length — turns times the average
context across those turns, and the context itself grows with the turns — so five lanes out of 612
measured (298-329 turns each) accounted for around 7% of all consumption, and splitting a long lane
into two with a handback between them costs about half. **This is deliberately not a paragraph
asking an agent to watch its own length**: a metric an agent can see is a metric it will optimise,
and the cheap ways to shorten a lane are exactly the ones this project exists to prevent — fewer
files read, no positive control, three states collapsed to two, stopping at the first plausible fix.
This repository has measured that a judgement-shaped instruction like this one does not change
behaviour twice already — `developer.md`'s batching paragraph across 612 transcripts, and the #490
A/B where a fuller cost model in the brief made the single-op rate 6% *worse*, not better — so the
threshold lives in a script the maintainer runs after a lane reports back, not in a sentence the
agent reads mid-run.

`scripts/transcript_refusals.py` (already the source of the numbers above) reports, per lane and per
group: `turns_over_threshold_count` / `_share` against `DEFAULT_TURNS_THRESHOLD` (140 turns, the
measured p90 — chosen over the p99 of 272 because the cost is quadratic, so a threshold anywhere
below the tail already captures most of the compounding, and p99 would leave the entire 90th-99th
percentile band unmeasured; see the constant's own docstring for the argument and what would make it
wrong), and `decile_bytes` — bytes and calls bucketed by decile of each transcript's own length,
carrying `first_fifth_byte_share` for the orientation finding below. Run it against a completed
lane's own transcript at handback, or periodically across a window of them, to decide whether
**future**, not current, related work should be bundled differently or handed back and re-briefed
sooner — a lane already past the threshold is not failing and is not stopped mid-run; it is simply
expensive, named as such, and used to shape the next dispatch.

**The orientation half — bytes arriving in the first fifth of a lane are read roughly ten times more
than ones arriving at the end — is constrained the same way: measured after, never surfaced
in-context.** `decile_bytes.first_fifth_byte_share` on a completed lane names how much of its
byte cost landed in the expensive early calls; a share well above the 20% an even split would
produce is the signal that a brief over-fetched context up front (`scripts/lane_setup.py`'s own
byte budget, #317, already targets exactly this for the setup-shaped calls it replaces — this is
the same lever applied to whatever else a brief hands a lane before it starts working, watched
rather than bounded, because nothing here can distinguish a genuinely wide orientation read from
one that could have waited).

**Run `${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py <issue>` from the clone before writing each
brief, rather than typing
the base commit and the live-worktree list into it by hand.** Both rot between the moment you read
them and the moment the dispatched agent does: `main` has moved mid-tick before, and a hand-copied
worktree list has already flattened `cannot tell` to `idle` once, which is how `fix/313` and
`fix/341` were each briefed onto `README.md` forty minutes apart (#317, #360). The script hands back
the resolved base, the derived branch and worktree, and the condensed board in one call, freshly
re-derived rather than pasted — paste its board output straight into the brief so every agent knows
who else is out there. `commands/tick.md` names the same call and its three states in full; this is
the pointer, not a second copy of that explanation.

Every brief carries these:

1. **Use supertool, as an instruction not a note.** Paste verbatim:

   > Use `supertool` for every file operation — it is on PATH, from any directory. Batch 6-7 ops per
   > call — `read`, `grep`, `glob`, `map`, `around`, `between`, `tree` — never one Read per file.
   > Pipe writes in as a TOML payload on stdin, using triple-single-quoted literal strings so escapes
   > survive; validators run post-write and roll back on a syntax failure. A literal block processes
   > no escapes, so write what you want on disk. **To change an existing file, `supertool 'edit:@-'`
   > carrying `path`, `old` and `new`; to create one, `supertool 'paste:@-'` carrying `path` and
   > `content`** — `edit` needs an `old` and a new file has none, so `paste` is the only route to a
   > file that does not exist yet, and your changelog fragment is always one. A raw heredoc runs no
   > validator and rolls nothing back. `supertool 'ops'` lists everything.
   >
   > **Batching** needs `op = "paste"` (or `"edit"`, `"read"`, ...) set inside every `[[ops]]`
   > entry — the shapes above omit it. Omit it and the call fails: `batch op missing op field`
   > (#669).
   >
   > Write prose quotes plainly in the pull request payload's JSON — never
   > backslash-escaped; `gh-pr-create` refuses a body carrying literal
   > backslash-quote, and `literal_backslashes = true` is for a real backslash.
   >
   > **Write your report from the worktree root — `cd <worktree_root>` first, not your branch
   > directory.** The report, note and PR payload live outside every worktree so they survive it
   > being reaped; supertool refuses a path outside cwd (`ERROR: path escapes cwd`), costing a full
   > re-send rather than a short retry. Do not use the env var or `allow_outside_cwd` escape hatch —
   > both widen every op for the session to buy one write. Move the cwd, not the guard.

   The op names are in there deliberately, and the creating one is the reason. A named op that
   supertool later renames fails *at the call*; an **omitted** one does not fail at all — it routes
   the agent to a `cat > file <<EOF` that succeeds, so the brief that left `paste` out for six
   deliveries read as correct every time (#250). The rule layer that does name `paste` is gated on
   `Read|Edit|Write|Glob|Grep`, so a heredoc never fires it and the pointer is unreachable for
   exactly this failure. This blockquote and the same paragraph in `agents/developer.md` are two
   copies on purpose — a brief has to be self-contained for an agent that never loads the other —
   and `tests/test_content_invariants.py` is where the fact lives once: it fails when either copy
   stops naming an op that can create a file.

   The cwd paragraph is here for the same reason and is the same defect one op over (#266). The
   brief guarantees a write outside every worktree and requires every write to go through supertool,
   which refuses exactly that path — so an agent doing precisely what both halves say is refused on
   the one write it was promised. The refusal is right; nothing naming the remedy is the bug, and it
   cost two agents a re-sent heredoc before anyone wrote it down. Same test file holds it: a
   document requiring the out-of-tree write must also name the refusal and the cwd that avoids it.

2. **Name the hidden judgment call.** If you cannot state what the agent will have to decide, you
   have not read the issue closely enough to delegate it.
3. **Invite pushback explicitly, and mean it.** Write diagnoses as hypotheses with the evidence
   attached, never as conclusions: **a confident, mechanical diagnosis from the orchestrator is the
   most dangerous input an agent receives.**
4. **Demand TDD in that order — test, red, fix, green.** Require the failure output *before* the
   implementation exists. The bar is "would this test still pass if the code did nothing?" — checked
   on the way in, not taken on trust. Every "must not fire" case is paired with a "must fire" case in
   the same fixture, because a silence assertion passes when the harness is broken.
5. **Require the docs** — the repo's `docs_targets` for anything user-facing, the changelog always.
6. **Name the live worktrees** — from the `lane_setup.py` run above's board, not retyped from
   memory, so agents know about each other.
7. **Unconditional publishing clause:** commit, do not push, do not open a PR, do not comment on the
   issue. "Do not push *if* something blocks you" is how one agent correctly pushed.

