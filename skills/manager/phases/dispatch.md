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

**Recon is the lane's own spawn (#1535), not yours.** The lane spawns `oss:recon` over its own
issues and keeps the summary in the one context that uses it. Returning it here and writing it back
into a brief paid for it twice and left the second copy in your context for the rest of the tick.
Measured on one lane (three issues): the recon cost 0.7M context tokens and the lane 65.8M against
134.4M for the comparable lane without one (#1499) -- the saving is the orientation reads being paid
once in a context that dies, and that holds wherever the spawn is made.

**One dispatcher-side use survives, and #1532 made it optional rather than required.** This said
`--claim` needs `--lane` patterns before the lane exists; it no longer does (#788's rule protected
the lane record, now retired). What is left is worth having and nothing forces it: `--lane` makes
`lane_setup.py` report the cross-cutting guard tests those files trip, and `--suggest-companions`
still requires it. For either, when you cannot name the patterns yourself, spawn one recon for that
section alone:

    Agent(subagent_type: "oss:recon", model: "sonnet", run_in_background: false, prompt: "<the issue numbers, the repo root, and: locate, do not design>")

Read its `## Lane file set` and its `RECON-COST:` line, which goes beside the lane's own `cost` in
the handback. **Discard the rest rather than pasting it** -- pasting it is the double payment above.
Issue #1535 predicted that after #1532 nothing here would need a recon; that is true of *needs*,
and whether to drop the optional use too is the maintainer's call, not this change's.

**Spawn with the literal string, not the definition's name** -- `commands/tick.md` spells its own
`oss:sub-manager` spawn out in full, and this step must do the same for the two it composes:

    Agent(subagent_type: "oss:developer", model: "sonnet", run_in_background: false)
    Agent(subagent_type: "oss:triager", run_in_background: false)

The only other place `agents/` demonstrates the `subagent_type: "..."` form is
`agents/developer.md`'s own review spawns -- inside the file a sub-manager never reads -- so
leaving the string to inference here is how #862 dispatched a lane as `general-purpose` and lost
every rule written into `agents/developer.md`.

**This paragraph alone did not hold: #989 is the same failure recurring** -- a tick reported,
unprompted, that all three of its `Agent()` calls omitted `subagent_type: "oss:developer"` and ran
as `general-purpose`, caught only because the tick happened to notice. Prose read once at the top of
a phase file is not present at the moment a call is typed by hand, turn after turn, so the fix is not
a stronger sentence here -- it is not composing the call by hand at all. `--claim` renders the whole
`Agent(...)` call from the issues it just claimed (#539, #989, #1143), so the label's multiplier is
what was actually assigned rather than what was retyped:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" 534 --claim \
        --claim-also 537 --claim-also 495 --phrase "auto-update path" \
        --subagent-type oss:developer --model sonnet --brief <brief-file>
    -> Agent(subagent_type: "oss:developer", model: "sonnet", run_in_background: false, description: "Lane 534 x3  auto-update path", prompt: "<brief>")

Paste that line and fill in `prompt` with the brief -- the one part only the caller can write. An
issue that did not come back `claimed` is not in the label: a lane whose third issue failed renders
`x2`. It refuses to render at all on a structural brief finding, on a `subagent_type` outside
`KNOWN_AGENT_TYPES`, and when the primary issue is not held.
Give it no fourth argument and it prints the description alone, unchanged from before. An omitted
`subagent_type` is a Python `TypeError` at the call site if you call `agent_call` directly, or a CLI
usage refusal; a misspelled one (`general-purpose` included, the historical failure's own value)
refuses against `KNOWN_AGENT_TYPES` rather than rendering a call that quietly spawns the wrong
agent. This does not prevent a call typed by hand anyway -- nothing in this repository can intercept
the real `Agent(...)` call before it runs, the same limit the model-choice recording above already
states -- it makes the correct call cheaper to produce than a wrong one typed from memory.

**Fallback mode, for a lane composed some other way: `--label`.** When the issues were claimed
outside this call -- an already-running lane relabelled, a bundle assembled by hand -- the label is
rendered on its own from a primary and an explicit list, with no claim and no `Agent(...)` line:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" 534 --label 534,537,495 "auto-update path"
    -> Lane 534 x3  auto-update path

It takes the list on trust, which is exactly what `--claim` above removes, so prefer `--claim`
whenever this call is the one doing the claiming.

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
reason, `override` does), and `--model-trend` re-adds the mix across the whole history. Record which
agent type it actually spawned, not only the model -- `--lane-agent-type ISSUE=TYPE` beside
`--lane`, closed against `oss:developer`/`oss:triager` (#862); anything else renders in the mix as
a finding, never a silent pass. It is typed after the spawn, exactly like the model choice above, so
it makes a wrong dispatch observable rather than preventing one -- nothing in this repository can
intercept the real `Agent(...)` call before it runs.

### A pending default branch is not a red one

`gh-branch` reports `NOT GREEN` both when a leg has failed and when legs have not concluded yet.
Those call for opposite behaviour, and collapsing them is this repository's own named defect class
-- an absence produced by the tool, read as an absence in the world. Four cases (#1084), and only
two of them justify holding:

- **Default branch pending, dispatching a new lane** -- do not wait. The lane branches off that
  commit and its own pull request runs the full matrix against the merge result; waiting buys
  nothing the lane's own CI does not answer more directly.
- **Default branch pending, merging an already-green pull request** -- do not wait. The merge gate
  reads the pull request's own checks, and a pending default branch right after a squash is the
  expected state -- `skills/manager/phases/merge.md`'s own step 3 is a read, not a hold.
- **Default branch red, dispatching** -- do not dispatch. Fix the default branch first: a lane cut
  from a red base inherits the breakage and cannot tell its own failure from the inherited one.
- **Default branch not green, tagging a release** -- wait. Already the rule at
  `skills/manager/phases/release.md`, and it is about the exact commit, at leg level.

**A fifth case sits beside these, and it is not a wait between dispatches -- it is a wait at the
tick's own edge.** Watch the last merge of a tick to conclusion before the tick closes. #968
recorded a merge train that outpaced the default branch's own run across four merges in one tick,
never once observing it GREEN between them -- tolerable only because each pull request merged on
its own concluded run against its own rebased head. Where a rebase is skipped on file-disjointness
grounds, or skipped altogether under `merge.md`'s own #1085 policy, the default branch's own `push`
run is the *only* backstop for the combined content, so a tick that merges on green and dies before
that run concludes has removed the pre-merge check without keeping the post-merge one.
`skills/manager/phases/tick-order.md`'s *What ends a tick* is where this is enforced -- a tick does
not close while radar's board says something is unwatched, and the default branch is carried there
as a member row, per that same file's own step 4 -- not a sixth case pasted in beside these five.

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
stays a maintainer judgement `select_issues.py`'s own companion search supports rather than
performs, for the same reason named above: an issue's files are not derivable from its body (#267),
so naming the candidate issue to check is yours, not the script's. (#1532 retired `--against`, which
used to be the direct two-lane form of this check; the companion search in `select_issues.py` and
`lane_setup.py --suggest-companions` are what remain.) **`under-filled` on this axis names the
shared file that blocked a further issue from joining a lane, and the issues queued behind that
file** — not only a smaller count.

**A declined dispatch cites the call that established it, made this tick, or it is not a reason
(#866).** `under-filled`'s reason -- on either axis, and whether it parks a whole issue or shrinks a
lane's count -- names the op or script invocation run this tick: `gh-issue:844` showing a non-empty
assignee, `gh-prs` showing the PR holding the files. Checkable by shape, not by trusting the prose:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --check-decline-reason "TEXT"`
reports `CITED` when the text carries a backtick-quoted call and `UNCITED` otherwise. An inherited or
freehand reason with no such citation is not a reason, even a true one -- dispatch the issue instead
of parking it on a stale handoff. **This check is advisory, not enforced** -- unlike `--lane-fill`,
which refuses `--decision` outright on an unreasoned short lane, there is nothing for an issue that
was never dispatched to attach a refusal to. Run it and put `UNCITED` in the tick's own report;
nothing currently blocks the call the way a short lane is blocked.

**Do not check that intersection by eye. `fix/247-244`'s lane was a literal path
(`skills/manager/SKILL.md`) and `fix/262-248`'s was a glob (`commands/*.md`); the second agent's fix
correctly touched `commands/tick.md`, and nothing caught the collision because a path and a glob do
not intersect visibly (#267).** `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --lane PATTERN
[--lane PATTERN ...]` renders the new lane in canonical form -- a sorted, deduplicated list of
repo-relative paths, each glob expanded against what is actually on disk -- so two lanes can be
compared as file lists rather than as the strings somebody typed.

**#1532 retired the automatic comparison that used to sit on top of that.** `--derive-held` built
the other side from every open pull request's own files plus every live lane record's own files
(#558), and `--against PATTERN` was the hand-typed fallback when the derivation failed. The chain
they fed ended at a per-candidate `availability` verdict -- `available`, `blocked`,
`could-not-check` (#774), `resolved-to-nothing` (#809), `could-not-derive-the-held-set` --
and #1528 had already stopped that verdict dropping a candidate, so what remained was a `gh pr list`
round trip and a registry walk per probe whose answer nothing acted on. Both flags are gone and
`lane_setup.py` refuses them as unknown arguments rather than accepting and ignoring them, so a call
pasted from a stale runbook fails loudly.

**What answers the question now.** git reports a real collision at merge, which is where it has
always genuinely been resolved. `supertool git-worktrees` reports which lanes are live, read from
the filesystem, and is the single source of truth -- the registry was a second copy of that fact
with a 240-minute TTL and no housekeeping, and a board read during this issue's own investigation
showed 15 worktrees of which 11 were `idle, merged, clean`. Two lanes that do collide is a textual
conflict somebody resolves once, not a silent wrong answer.

**A lane that resolves to nothing has not been confirmed free (#809, #837).** Every member
individually well-formed and checked, and the whole lane still naming zero files on disk -- a glob
that matched nothing, a directory with nothing under it -- is not the same fact as a lane that
really does touch nothing else. It reads `glob-no-match` on the pattern's own state in the `lane`
side of the receipt. #1532 removed the `availability` verdict and the `overlap` line that used to
carry this distinction on the comparison, but the underlying reading survives where it is still
computed: `select_issues.py` reports a candidate whose lane resolved to no files on disk as a dark
input rather than as a clean one, which is the same refusal to fold. When it shows up in a tick's
own counting, it belongs under `could-not-tell`, folded in rather than counted, and never under
`filled`.

None of this touches the other side of the check -- naming which further open issues could join an
already-claimed lane (above). An issue's own files are still not derivable from its body (#267), so
naming the candidate issue to check stays yours, not the script's.

When the disjoint areas run out, say so rather than inventing another lane. **Bundling related
issues into one brief is better than splitting one file across two agents** — the fuller rule for
when and how far to bundle is below, beside the claim it is dispatched alongside. Stacking is the
other lever: branch the second agent off the first's branch rather than off the default branch. It
costs a rebase per merge. Do not stack more than two deep without a reason.

**Claim before you spawn, not after** — writing the primary issue's brief with `--claim`
(#1069, #1532) writes every issue's own GitHub assignee:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <primary> --claim [--claim-also <N> ...]

Dispatch only what comes back `claimed`. There are exactly three states, and the other two are
`already-claimed` (somebody else holds at least one of the issues — nothing was written) and
`could-not-claim-assignee` (the read/write itself did not complete for at least one). Those two are
different facts and the second is never folded into the first: `could-not-read` is never
`unassigned`. See `lane_setup_claim.claim_issues`'s own docstring. #1532 retired the two rollback
states that used to sit beside them (`assignee-rolled-back`,
`rollback-failed-assignee-still-set`) — they existed because the call also wrote a local lane
record, and there is no second write left to fail.

**Run `scripts/select_issues.py` (#970, #1036) as the dispatch-selection call itself — this is the
directive, not a description.** Board in, ranked claimable candidates out. It composes ranking,
staleness, lane-collision and the claim read into one call, and returns three states —
`candidates` / `none-available` / `could-not-select`, the last never rendering as the second — plus a
per-issue disposition (`eligible` / `assigned` / `assignee-unreadable` / `stale` / `unrankable` /
`lane-collision`). It does not replace `--claim` above: reading who is claimable and writing a claim
stay separate calls.

**It takes no input (#1145).** No stdin payload, no `--fetch` mode. It fetches the board and reads
`.oss.json` itself, so `board_read_ok` / `board_read_why` / `board_capped` / `board_cap_detail` are
facts it observed, and a failed read is `could-not-select`. (#1532 removed the `lanes_read_ok` /
`lanes_read_why` pair beside them, which reported on the held-set derivation.) It still never
invents `lane_patterns` or `preflight_pattern` for an issue that declares neither (#267).

**Read `lanes`, one entry per declared lane label, and dispatch its group (#1146, #1530).** The
fleet is the lane labels `.oss.json` declares, `labels.lane_other` included. Each lane returns
**one** group: the best-ranked eligible issue as lead plus up to two companions sharing that same
lane label, whatever their own rank. **Cap at three, never four** (#799, #499). A lane's other
eligible issues stay in its `candidates` list. A group is a suggestion, never a dispatch — weigh it
against topic and judgement.

Each lane carries its own third state (`candidates` / `none` / `could-not-tell`) and, when short, one
of `board-exhausted` / `no-adjacent` / `did-not-search` / `could-not-tell`. A lane with no eligible
work returns a stated absence, not a missing key. `lane-other` keeps its solo rule (#1130): one
issue, never a companion, never offered as one.

**An issue carrying no `lane-*` label is not selected (#1146).** No lane, no group, no body. It
appears in the top-level `dropped` list with the disposition `no-lane-label`. `/oss:triage` gives an
issue its lane.

**Every group carries its issues' bodies (#1147)**, each wrapped in a per-body random nonce and
labelled data, not instructions. A capped body reports `body_truncated` and its full `body_length`.
Read those rather than re-fetching issue by issue.

**`labels.reserved` in `.oss.json` is how the maintainer holds an issue open (#844).** An empty
assignee field means only "no maintainer lane holds this" — never "nobody wants it". A reservation
made off the tracker is invisible to a sub-manager spawned fresh with nothing, so it goes on the
tracker: `select_issues_rank.reserved` reads the declared spelling back and prints `[RESERVED]`
beside every issue carrying it. A repo declaring no spelling reads every issue as unreserved, never
as `could-not-tell`. Note that a contributor without write access cannot self-assign at all, so this
mechanism claims for the maintainer's own loop only (#460).

**A lane dispatched with fewer than three says why, in the handback, in one of four words.**
`board-exhausted` — fewer than three file-disjoint candidates remain. `no-adjacent` — the search ran
and nothing shares a file or module with the top issue. `did-not-search` — it did not run.
`could-not-tell` — it ran and could not be computed. **A short lane with no reason is a defect in the
tick**, and the four are a closed set: a free-text reason is unreadable by anything but a person
(#773). A board never measured, one whose measurement failed, and one measured and found empty are
three different facts.

**Get the word from `--group-state`, not by retyping it (#1198).** `lane_setup.py --claim`'s
`--group-state STATE` takes `select_issues.py`'s own group `state` field unchanged and derives the
REASON word mechanically for three of the four states -- `none` to `no-adjacent`, `could-not-tell`
to `could-not-tell`, `lane-other` to `did-not-search` -- via `group_short_reason()`, so paste the
state select_issues.py already printed rather than translating it by hand. `--short-reason` stays
the explicit override: it is the only route for the fourth state, `candidates` (some companions
found, still short), which is deliberately left unmapped because `board-exhausted` is a claim about
the whole board's remaining disjoint candidate count that one group's own state never establishes --
and it wins outright when both flags are given, for a lane composed some other way than
`select_issues.py`'s own grouping.

**Two of the four carry a count that can refute them (#871, #918).**
`--lane-fill PRIMARY:COUNT:board-exhausted:CANDIDATES` takes the file-disjoint candidate count;
`oss_state.py --decision` refuses the call when it is three or more.
`--lane-fill PRIMARY:COUNT:no-adjacent:CANDIDATES` takes the count of candidates *adjacent to the top
issue*, and its threshold is stricter — `no-adjacent` means zero, so **one adjacent candidate refuses
it**. `did-not-search` and `could-not-tell` take **no** count, and `oss_state.py` refuses one supplied
anyway: a count refutes a claim, and neither of those two makes one. Attach the count whenever the
search ran; a refusal without one is unfalsifiable.

**A bundle is not a cluster.** A cluster claims one change fixes several issues and needs a shared
failure to back it; a bundle claims only that the fixes share a worktree. A bundle of two or three
stays two or three fixes: **each issue keeps its own test story and its own changelog fragment**, and
the pull request closes every issue it carries.

**Prefer not to bundle an issue a running lane already touches** — overlap against a *running* lane
means a conflict somebody resolves by hand; overlap against a *candidate's* declared lane means the
two are worth bundling. Since #1528 an overlap no longer drops a candidate, and since #1532 nothing
computes it for you: read the running lanes off `git-worktrees` and judge it. A textual conflict at
merge is the backstop, and it is a loud one.

**The two-issue row must not become a rule (#586).** The cap's own measurement puts a two-issue lane
worse per issue than a single-issue one at n=58, which is the size of result that reverses on more
data — carry that caveat with the number, and never turn it into a refusal to pair two issues.

**The fleet-view label names what a lane covers, not what it starts with (#539).** The count is the
load-bearing half — a reader scanning four rows should see `x3, x1, x1, x1` without reading any
phrase — so the multiplier spelling is the convention: `Lane 534 x3  auto-update path`, never
`Lane 534 (+537, +495)  …`. `--claim` composes it from the issues it just claimed (#1143), so the
count is derived from what was assigned rather than from a list retyped into a second call, and an
issue that failed to claim is not in it. A lane briefed by hand without running `--claim` is the one
case this cannot catch.

Launch every dispatched lane — bundled or not — in a single message so they run concurrently.

### One fan-out, then the lane is resumed, never re-dispatched

**A tick performs exactly one dispatch (#880).** One fan-out, filled per the axes above, then the
tick sees those lanes through to merge -- a second fan-out is a second tick inside the first, and
the receipt lies for it (three lanes, one re-dispatched twice, reads as five).

**A red lane, or one whose base moved, is resumed via `SendMessage` to its own agent rather than
re-dispatched fresh at the same issue.** The agent that wrote the diff knows why; a fresh spawn
re-derives everything from nothing, paying #695's saving back as a cost (`commands/tick.md` step 7,
#818, already resumes a paused sub-manager this way; a resumed lane costs the message against a
fresh developer spawn's measured 150k-290k tokens).

**That prices one side of the ledger; the other was measured on 2026-09-15 (#1567).** The 150k-290k
above is a fresh spawn's total over its whole life. A resume's cost is the lane's context re-sent on
every turn after it, never costed. One resumed lane: 38 records, 15,558,821 sent, max 421,672 -- an
average call-time context of 409,443, within 3% of its own maximum, because a lane already at its
ceiling pays the ceiling on every later turn.

**So a red lane whose context has grown large may be re-spawned fresh instead, recorded
`respawned-for-cost` with the context figure as its `why`.** The re-derivation argument is weakest
here: a red leg names its own site in the failing log, and `oss:recon` (#1542) re-orients a fresh
lane for one read-only spawn. It stays strongest for a review return spanning a whole diff, which
this does not cover. The threshold is a judgement the tick states, not a constant -- one reading is
one reading, and a lane resumed at 80k is still the cheaper resume. It is a fourth state, never a
softer spelling of its neighbours: `oss_state.py` requires the `why` for that reason, and the #880
refusal exempts it by counting only `dispatched`. A fresh spawn recorded `resumed`, or a cost
respawn recorded `agent-unreachable`, is this repository's own defect one level down.

**A lane's own agent can genuinely be gone -- context died, or resumed and silent twice, the bar
`agents/developer.md` sets its own review spawns -- and that is its own named state,
`agent-unreachable`, distinct from `resumed`.** A re-dispatch with neither an attempted resume nor
that finding is the defect this section stops; state which one applied in the handback.

**A task-notification whose `result` is a single present-tense sentence with no report path is a
lane that stopped, not one that finished (#1518).** Observed: a lane hit the harness's own
auto-mode Bash classifier going down mid-call and ended its turn on "Waiting for the classifier to
recover" -- the notification carried only that sentence, indistinguishable at a glance from a lane
genuinely still working. Every task-notification names an `output-file` path in its own metadata --
the full JSONL transcript of that spawn -- and this is what settles the ambiguity; a report path in
`result` is the normal case and needs none of this.

**Do not open that file whole.** The harness's own instruction on receiving a task-notification
says not to Read or tail it -- it is a full subagent JSONL transcript and can be large enough to
overflow the very context trying to answer one narrow question. Grep it instead, for
the harness's own classifier-refusal wording -- `grep:auto mode cannot determine the safety:
<output-file path>` -- rather than reading it end to end. A hit there is transient and per-call, not
the lane being gone, and the right response is the same `SendMessage` resume `agent-unreachable`
above already uses -- the lane in question finished normally once resumed, after about two minutes
down. No hit, or the file cannot be read at all, is not evidence either way on its own; fall back to
`agent-unreachable`'s own two-strikes rule (a resumed lane silent twice) rather than guessing from
absence.

**#978: `agents/sub-manager.md`'s frontmatter grants `SendMessage`, and some harness versions are
documented as still refusing it as gated behind an opt-in feature even so.** Two live sub-manager
spawns hit exactly this before the grant existed at all -- reporting no `SendMessage` tool -- and
fell back to a fresh spawn recorded as `resumed`, because the honest answer had nowhere else to go.
If the resume call itself refuses, naming the tool absent or disabled rather than the lane's own
agent being unreachable, that is `agent-unreachable` too -- quote the refusal verbatim as
`dispatch_state_why`, never a silent fresh spawn recorded as `resumed`. This is a different failure
from the target agent being gone, and the same remedy covers it: neither one is a licence to
re-dispatch without recording which happened.

**This is enforced, not only stated (#880), in `oss_state.py` itself** -- its own
`--lane-dispatch-state ISSUE=STATE[:WHY]` help and refusal carry the argument now, so it is not
retyped here: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file>
--lane-dispatch-state ISSUE=STATE[:WHY]` (repeatable, matched to `--lane` by issue). `resumed`
needs no reason; `agent-unreachable` requires one. Omit the flag for an ordinary single dispatch.

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

**Run `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --claim` from the clone before
writing each brief, rather than typing
the base commit and the live-worktree list into it by hand.** Both rot between the moment you read
them and the moment the dispatched agent does: `main` has moved mid-tick before, and a hand-copied
worktree list has already flattened `cannot tell` to `idle` once, which is how `fix/313` and
`fix/341` were each briefed onto `README.md` forty minutes apart (#317, #360). The script hands back
the resolved base, the derived branch and worktree, and the condensed board in one call, freshly
re-derived rather than pasted — paste its board output straight into the brief so every agent knows
who else is out there. `skills/manager/phases/tick-order.md` names the same call and its three
states in full (#1037: this content moved out of `commands/tick.md` into that phase file); this is
the pointer, not a second copy of that explanation.

**`--claim` belongs only here, never on a probe above** (#705). The probe forms above are read-only;
only `--claim` writes, and what it writes is the issue's GitHub assignee. Claiming on a probe takes
an issue nobody is going to work.

**#1532 removed two refusals that went with the registry.** `--claim` no longer requires `--lane`
(#788 -- a claim with no files wrote a fileless lane record that poisoned every later
`--derive-held`; there is no record and no `--derive-held`), and it no longer refuses a claim made
from inside a worktree rather than the clone (#865 -- standing in a worktree derived `worktree_root`
from that worktree's own path and wrote into a registry sibling to it, invisible to every other
lane). An assignee write reads no local path at all: it is a forge call against the issue number, so
it is correct from any directory. Running `--claim` from the clone is still the better habit,
because the same call's worktree and branch derivation does read `.oss.local.json`, and that file is
git-excluded from every worktree this loop cuts.

**`--stack-on BRANCH` (#1006) is the narrow escape from a `cannot tell` this loop caused itself,
never a general substitute for the ordinary dispatch path above.** The incident it was built for:
the manager merges and pushes into a live lane's own branch (to pull in a just-landed fix, say), and
sixty seconds later wants to dispatch a second, related lane stacked on that same branch's tip --
and `git-worktrees` reads that tree as `cannot tell`, citing the manager's own index write as the
reason, with no way to tell that write apart from a live agent's. Passed to `lane_setup.py`, `base`
is resolved straight out of the shared object database (`refs/heads/<BRANCH>`, falling back to
`refs/remotes/<remote>/<BRANCH>`) rather than through any worktree's checked-out files, so cutting
the new lane's branch from it never touches the tree that read `cannot tell` at all -- there is
nothing left to collide with. Reach for it when **both** hold: the lane you are about to dispatch
is meant to stack on a specific sibling branch rather than on `default_branch`, and that branch's own
worktree is the one reading `cannot tell` (or is plainly occupied by a live lane you do not want to
touch). It is not a way to dispatch past a `cannot tell` on `default_branch` itself -- ordinary
dispatch already reads `main`'s worktree only to fetch and rev-parse, never through the worktree's
own files, so that collision does not arise there in the first place. `resolved-remote` (found only
as a remote-tracking ref) is flagged, not silent: it can be stale if nobody has fetched since that
branch last moved, and the brief should say so rather than treat it as equivalent to a local
`resolved`. **This is a different moment from #1007's `cannot tell` in `merge.md` above**, which
gates *removing* a worktree that already merged; `--stack-on` gates *creating* one, and the two
never substitute for each other -- a lane briefed with a stacked base still goes through the same
worktree-removal read at cleanup time, unchanged.

**The spawn payload for a developer lane is two facts: the issue numbers and its worktree** (#1535).
Nothing else. `agents/developer.md` is that lane's system prompt and is re-sent on every turn —
supertool, the TDD order, the docs duty, the publishing clause, pushback and untrusted input are all
in it already, and a brief restating them paid ~7,900 B per spawn to tell the reader what it was
already holding. What a lane still needs and does not have, it fetches: the issue text with
`gh-issue:N:full`, the live worktrees with `git-worktrees`, its guard tests with `lane_setup.py
--lane`.

`--claim --phrase P --subagent-type oss:developer` composes that prompt itself, from the issues the
claim actually holds and the worktree it derived, and prints the whole `Agent(...)` line. Paste it.
The prompt it renders, and the whole of it:

    Issues 1526 and 1528. Your worktree is <worktree_root>/1526.

`scripts/lane_setup_brief_schema.py` checks that composed prompt before the
`Agent(...)` line is rendered — `issues`, `worktree`, `placeholder`, all three
structural: `ok` / a row per finding / `could-not-read`, and **any** finding
refuses the render. A worktree that could not be derived is one of them, so a
lane is never dispatched to cut its own. It is a module, not a command (#1143);
`scripts/report_schema.py` is its symmetric half on the return path.

**`--brief PATH` is optional extra per-lane context**, appended to the composed prompt — a recon
summary is the case it exists for. Never a substitute for the two facts, and never a place to restate
`agents/developer.md`.

**Recon is the lane's own call now (#1535).** It spawns `oss:recon` over its own issues and keeps the
summary in the one context that uses it. Returning that summary to you and writing it back into a
brief paid for it twice and left the second copy in your context for the rest of the tick.

**Re-read anything you compose by hand for a leftover `{{...}}` marker before the `Agent()` call, not
after.** There is no templating step between writing the text and it being sent — whatever string is
typed is what the agent receives verbatim — and `SendMessage` is unavailable once the call has
returned (#1022). The schema flags it in anything reaching `--brief`; a prompt typed straight into an
`Agent()` call is only reachable by eye.

### Briefing a spawn that is not a developer lane

An agent whose own definition does not carry the write route — a `general-purpose` fallback, per the
unresolvable-spawn rule above — needs it pasted. Verbatim:

   > Use `supertool` for every write, commit included — it is on PATH, from any directory. Batch
   > 6-7 ops per call — `read`, `grep`, `glob`, `map`, `around`, `between`, `tree` — never one Read
   > per file. Pipe writes in as a TOML payload on stdin, using triple-single-quoted literal strings
   > so escapes survive; validators run post-write and roll back on a syntax failure. A literal block
   > processes no escapes, so write what you want on disk. **To change an existing file, `supertool
   > 'edit:@-'` carrying `path`, `old` and `new`; to create one, `supertool 'paste:@-'` carrying
   > `path` and `content`** — `edit` needs an `old` and a new file has none, so `paste` is the only
   > route to a file that does not exist yet, and your changelog fragment is always one. A raw
   > heredoc runs no validator and rolls nothing back. `supertool 'ops'` lists everything.
   >
   > **Commit through `supertool 'git-commit:@-'`, never a raw `git commit -m`** — the guard refuses
   > that on sight and names this op as the remedy, on the one write every lane makes unconditionally
   > (#729). Its own reach is wider than file writes; `supertool 'ops'` above is the live list, not
   > the three named here.
   >
   > **Batching** needs `op = "paste"` (or `"edit"`, `"read"`, ...) set inside every `[[ops]]`
   > entry — the shapes above omit it. Omit it and the call fails: `batch op missing 'op' field`
   > (#669).
   >
   > Write prose quotes plainly in the pull request payload's JSON — never
   > backslash-escaped; `gh-pr-create` refuses a body carrying literal
   > backslash-quote, and `literal_backslashes = true` is for a real backslash.
   > A doubled `\n` is the same reflex and opens as one line; refused too (#685).
   >
   > **`cd <worktree_root>` on every write call leaving your branch directory, not once.** A shell
   > cwd does not persist between calls, so a later bare `supertool` writes into the clone (#685).
   > The report, note and PR payload live outside every worktree so they survive it being reaped;
   > supertool refuses a path outside cwd (`ERROR: path escapes cwd`), costing a full re-send
   > rather than a short retry. Do not use the env var or `allow_outside_cwd` escape hatch — both
   > widen every op for the session to buy one write. Move the cwd, not the guard. A moved cwd
   > reads like a vanished file: read the validator's `at:` line.

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
   each write it was promised. The refusal is right; nothing naming the remedy is the bug, and it
   cost two agents a re-sent heredoc; naming it *once* then cost two more (#685). Same test file
   holds the refusal and remedy, `test_write_receipt_685.py` the per-call half.

   **The blockquote is wrong, as written, inside a worktree of a managed repo that is supertool's
   own checkout** (#1409): the bare `supertool` name resolves to whichever clone the SessionStart
   hook last linked, ordinarily that project's own live checkout at its trunk branch, and running it
   from a *worktree* of that same repository runs the trunk's core against the worktree's own
   branch-local presets -- silently wrong for a read, refused outright for a write. Which repo, if
   any, this applies to is never named here -- see the rule against a fact about one repository
   living in shared code -- so consult `scripts/doctor.py`'s own `supertool_invocation(project_dir)`
   against the target repo rather than assuming; it reuses the same `_own_supertool_tree` walk
   `check_supertool_entry_point` already uses for the `own-tree` diagnostic state, so a repo is never
   checked two ways. When it answers `own-tree*`, append one line after the verbatim blockquote
   naming the tree's own core (`python3 supertool.py`, not the bare name) rather than editing the
   blockquote itself, which stays byte-identical for every other managed repo. `lane_setup.py`'s own
   board-line read already routes through the same function, so its `COULD NOT RUN -- mixed
   supertool trees` receipt is fixed independently of whether this note is added to a given brief.

Everything the eight numbered items here used to demand of a developer brief —
the judgment call, pushback, the TDD order, the docs duty, the live-worktree
list, the unconditional publishing clause, the recon paste — is retired (#1535).
`agents/developer.md` carries each of them as a rule the lane already holds, and
demanding a brief restate them is what made the spawn payload 7,900 B long.

---

## Deciding what to build: what to select, and checking it is still open

- **Judge as the tool's primary user.** "Is this useful when I actually run it?" beats "is the issue
  well-written."
- **Refusing is a first-class outcome**, and cheaper than any build.
- **Pre-flight before delegating.** Reproduce the behaviour. Read the body *and* the comments
  (`gh-issue:N:full`) — a comment amendment redefines the deliverable often enough that briefing from
  the body alone is a known way to burn a whole agent run.
- **Re-derive the issue's own claims.** A body goes stale while its comments accumulate. Grep for the
  *concept*, not the issue's spelling of it.
- **The issue can go stale against the code, and neither bullet above catches that axis.** Both of
  the two above are about the body going stale against its own comments — nothing yet asks whether
  the whole issue, comments included, has gone stale against what actually shipped. A lane was
  dispatched for part 3 of #81 after the fix had already landed and shipped: the body and every
  comment were read exactly as asked, and the brief was still written for finished work (#457). Before
  writing a brief, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/select_issues.py" --preflight
  PATTERN --path FILE_OR_DIR` against the
  code path the issue names — for #81 that was one grep for `could not run` in `commands/release.md`
  — and read its `state` in three, never two: **`matched`**, **`not-matched`**, or
  **`could-not-search`**, which must never be read as `not-matched`. Whether a match means
  **already-shipped** or **still-open** depends on what the pattern names — a contract that should
  exist, or a symptom that should not — and that direction is the maintainer's own judgement to record
  alongside the call, never the script's to guess. `could-not-search` becomes **`could-not-tell`** at
  the dispatch decision and must never render as **`still-open`** either — the issue names no code
  path precise enough to check is the honest reading, not a nudge to dispatch anyway.
  **For a multi-part issue, run it once per part.** A whole-issue verdict hides exactly the case
  #457 records: #81 had three parts in three different states (one filed elsewhere, one shipped, one
  genuinely open), and a single check over the whole issue would have called it open and dispatched
  it again. **The same check belongs where a bundle is assembled, not only where a single issue is
  chosen** — a stale member wastes a share of the whole bundle's brief in proportion to the bundle's
  size, and a bundle reads exactly as healthy at dispatch whether or not one of its members has
  already shipped. Run it for every candidate before it is added to a bundle, not only for the one
  issue a single-issue lane would have picked.
  **Quote the probe's scope verbatim in the brief, never a summary of it (#727).** `not-matched`
  over one file and `not-matched` over the whole tree render identically once retyped as prose — a
  brief that wrote *"a pre-flight returned not-matched — nothing does this today"* about a probe
  scoped to one file (`scripts/doctor.py`) sent a lane to build a second mechanism beside one that
  already existed (`tests/test_shipped_op_spellings.py`), because the sentence carried no scope for
  the lane to catch. `select_issues_preflight.py`'s receipt names `roots`, the paths actually searched, on
  every state including `could-not-search` — paste the whole line, `not-matched over 1 file
  (scripts/doctor.py)`, never a paraphrase of it. This is not a demand to sweep the whole tree on
  every pre-flight; a narrow probe is often the right probe. The defect is a narrow probe's answer
  wearing a repository-wide claim's clothes.
- **Select in the dispatch order, and compute it rather than feel it (#798, extended by #993).**
  Two axes, author before priority within a band. `python3
  "${CLAUDE_PLUGIN_ROOT}/scripts/select_issues.py" --board` is the one place the table lives; call it
  rather than re-deriving it here. **`--board` fetches its own board too, the same way the
  default, no-flags call documented above does (#1200)** — #1178 had found the two modes did not
  share an input contract (`--board` read a board-shaped payload on stdin), and #1200 closed that
  the other way, by removing the stdin read rather than documenting it. Neither mode takes a
  caller-built payload any more; a failed fetch answers `could-not-select` for either one. The rows
  below transcribe `scripts/select_issues_rank.py`'s own `ROWS` (the module was `dispatch_rank.py`
  before #1069); a table that disagrees with it is a bug in this file, not a second opinion.

  | Rank | Who filed | Priority |
  | --- | --- | --- |
  | 1 | any | a blocking-class row in `skills/manager/phases/findings.md`'s own table |
  | 2 | external | high |
  | 3 | maintainer | high |
  | 4 | loop | high |
  | 5 | external | medium |
  | 6 | maintainer | medium |
  | 7 | loop | medium |
  | 8 | external | low, or no priority label |
  | 9 | maintainer | low, or no priority label |
  | 10 | loop | low, or no priority label |

  **"Loop" is an issue carrying `labels.filed_by_loop`'s label.** An issue without it is either
  external or maintainer, never both and never a fallback "human" band — #798's original two-axis
  order collapsed an outside reporter and the maintainer into one "human" value, which ranked an
  untriaged external bug report (unlabelled by definition, since nobody has triaged it yet) below
  the loop's own high-band backlog. #993 splits it: **"external" and "maintainer" are read from
  GitHub's own author association** on the issue (`OWNER`/`MEMBER`/`COLLABORATOR` versus
  `CONTRIBUTOR`/`NONE`), never from a declared label — an issue the loop files is filed under the
  maintainer's own account, so `labels.filed_by_loop` is checked first and settles the author axis
  on its own for a loop-filed issue; the association is only consulted for everything else. This
  replaces priority-only ordering rather than layering over it. The reason is a measurement, not a
  preference: 476 issues in 20 days on this repository, 98% of them filed by the loop, 68% closed
  the same day — so a maintainer's ask sat behind the loop's own backlog, and the two maintainers no
  longer knew what the tool was doing.

  **Rank 1 is prose, not a row `select_issues_rank.rank()` ever returns** — nothing here can read an
  issue against the findings table; that classification is a judgment call made when a
  finding is written up. Check the blocking-class exception before consulting the computed table,
  the way the old six-row table's rank 2 encoded it: a blocking defect must not lose to any author's
  ordinary ask.

  **Rank 5's second clause in #993's own proposal — "or a bug with no priority label" — is
  deferred**, and is not in the table above. It needs a `labels.defect` (or `labels.type`) key
  `.oss.json` does not declare yet, the identical undeclared-axis shape #990 fixes for
  `labels.filed_by_loop`'s own rot. Until that key exists, an untriaged external bug ranks by
  priority alone, same as any other unprioritised external issue (rank 8).

  **`could-not-rank` is a real answer and must never render as the lowest-cost guess.** With no
  declared `labels.filed_by_loop`, every issue is unlabelled, and reading that as "all external" or
  "all maintainer" would misplace the loop's whole backlog either way. Same discipline one level
  down: a non-loop issue whose association could not be read must render as neither — guessing
  "external" promotes a stranger's ask above the maintainer's own, guessing "maintainer" buries a
  genuine external report — `rank()` refuses on both axes, and sorts an unrankable issue last, never
  first. The absence of a reading is not evidence of value.

- **Rank a finding by what cannot be undone**, then by who is walking away. The ranking table
  lives in `skills/manager/phases/findings.md` and **only there**, with the two verdict columns it carries:
  *blocks a release* and *embargo when reported upstream*, which are two different questions and
  disagree on one row. Read that file before ranking anything, and read the column you actually
  need rather than a restatement of it. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ranking_table.py"`
  prints the table's own bytes when a payload needs it verbatim. **A finding that fits no row is
  reported unranked**, never demoted to "no row, therefore minor".

- **Ask whether the fix compounds**, not whether the loop is worth it. A fix that removes a whole
  class of future defects outranks a bigger fix that removes one instance.

