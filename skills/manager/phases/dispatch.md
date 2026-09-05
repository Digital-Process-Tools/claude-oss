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
a stronger sentence here -- it is not composing the call by hand at all. `scripts/fleet_label.py`
already refuses to compose a *description* from an incomplete issue bundle (#539); its
`agent_call` does the same for the **whole call**:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_label.py" 534 534,537,495 "auto-update path" oss:developer --model sonnet
    -> Agent(subagent_type: "oss:developer", model: "sonnet", run_in_background: false, description: "Lane 534 x3  auto-update path", prompt: "<brief>")

Paste that line and fill in `prompt` with the brief -- the one part only the caller can write.
Give it no fourth argument and it prints the description alone, unchanged from before. An omitted
`subagent_type` is a Python `TypeError` at the call site if you call `agent_call` directly, or a CLI
usage refusal; a misspelled one (`general-purpose` included, the historical failure's own value)
refuses against `KNOWN_AGENT_TYPES` rather than rendering a call that quietly spawns the wrong
agent. This does not prevent a call typed by hand anyway -- nothing in this repository can intercept
the real `Agent(...)` call before it runs, the same limit the model-choice recording above already
states -- it makes the correct call cheaper to produce than a wrong one typed from memory.

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

**A declined dispatch cites the call that established it, made this tick, or it is not a reason
(#866).** `under-filled`'s reason -- on either axis, and whether it parks a whole issue or shrinks a
lane's count -- names the op or script invocation run this tick: `gh-issue:844` showing a non-empty
assignee, `gh-prs` showing the PR holding the files. Checkable by shape, not by trusting the prose:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --check-decline-reason "TEXT"`
reports `CITED` when the text carries a backtick-quoted call and `UNCITED` otherwise. An inherited or
freehand reason with no such citation is not a reason, even a true one -- dispatch the issue instead
of parking it on a stale handoff. **This check is advisory, not enforced** -- unlike `--lane-fill`,
which refuses `--decision` outright on an unreasoned short lane, there is no lane record for an issue
that was never dispatched to attach a refusal to. Run it and put `UNCITED` in the tick's own report;
nothing currently blocks the call the way a short lane is blocked.

**Do not check that intersection by eye. `fix/247-244`'s lane was a literal path
(`skills/manager/SKILL.md`) and `fix/262-248`'s was a glob (`commands/*.md`); the second agent's fix
correctly touched `commands/tick.md`, and nothing caught the collision because a path and a glob do
not intersect visibly (#267).** `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --lane PATTERN
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

**A fourth state, `could-not-check` (#774), is not the same failure and does not take the same
fallback.** `could-not-derive-the-held-set` means the *derivation itself* broke -- `gh`, a timeout, a
missing record -- and retyping the held set by hand genuinely substitutes for it. `could-not-check`
means the derivation ran and a specific pattern was refused by `_lane_pattern_problem` for cause:
empty, drive-prefixed or leading-`/`, a `..` traversal, or a literal `|` (the repeatable-flag form
spelled wrong, #766). Read `overlap_detail` (or the `overlap : COULD NOT CHECK -- N of N lane
pattern(s) refused: PATTERN` receipt line) for which pattern and why, before doing anything else.

If the refused pattern is on **your own `--lane` side**, retyping the identical string as `--against`
gets refused identically -- the string is what is wrong, not the flag. Fix the pattern (correct the
typo, drop the leading `/` or the `..`, split a `|`-joined value into one `--lane` per file) and
re-run `--derive-held`. If the refused pattern is on the **derived-held side** -- a real git-tracked
file whose own name trips the same refusal, such as a literal `|` in a filename -- there is no flag
to fix: `--against` and `--derive-held` are mutually exclusive, so hand-typing that one file as
`--against` refuses it the same way. Read that file's overlap by eye instead, and say in the record
that the automated check could not vouch for it -- never dispatch on a bare `could-not-check` read as
though it were `available`.

**A fifth state, `resolved-to-nothing` (#809, #837), is not a sixth row beside `filled` /
`under-filled` / `could-not-tell` above -- it is a reason `could-not-tell` carries, folded in rather
than counted, and it must never read as `filled`.** It means every member of a candidate lane was
individually well-formed and checked, and the whole lane still named zero files on disk -- a glob
that matched nothing, a directory with nothing under it. `overlap` renders `[]` for exactly the same
reason a real, disjoint, non-empty lane would, so `overlap` alone cannot tell the two apart;
`lane_report` marks it separately (`availability.state` and `overlap_state` both
`"resolved-to-nothing"`) and the receipt prints `verdict : RESOLVED TO NOTHING` /
`overlap : n/a -- lane resolved to zero files on disk, nothing to compare (#809)` rather than
folding it into either `available` or `COULD NOT CHECK`. A candidate that named nothing has not been
confirmed free -- counting it toward `filled` is the exact fold this loop is named for catching, so
it is reported the same way `could-not-tell` is reported above: the candidate and the pattern that
resolved to nothing, not silence.

None of this touches the other side of the check -- naming which further open issues could join an
already-claimed lane (above). An issue's own files are still not derivable from its body (#267), so
naming the candidate issue to check stays yours, not the script's.

When the disjoint areas run out, say so rather than inventing another lane. **Bundling related
issues into one brief is better than splitting one file across two agents** — the fuller rule for
when and how far to bundle is below, beside the claim it is dispatched alongside. Stacking is the
other lever: branch the second agent off the first's branch rather than off the default branch. It
costs a rebase per merge. Do not stack more than two deep without a reason.

**Claim before you spawn, not after** — every issue in the lane in one call:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_claim.py" <N> [<N> ...] --claim

Dispatch only what comes back `claimed` or `already-mine`. A spawn that dies on its first call must
not leave an unclaimed issue with a worktree attached, and a lane running for hours while the issue
reads `Assignees: none` is how two readers pick the same issue.

**`could-not-read` is not `unassigned`, and the script is what holds those apart** — picking an issue
whose claim state is unknown is this repository's own defect class, one layer up. The rest of the
argument, including what a `claimed` row does *not* promise, is in the script's own docstring rather
than here (#964).

**Run `scripts/select_issues.py` (#970, #1036) as the dispatch-selection call itself — this
is the directive, not only a description of what the script does.** It composes the ranking,
staleness and lane-collision checks above plus this claim read into one call, board in, ranked
claimable candidates out, three states (`candidates` / `none-available` / `could-not-select`, the
last never rendering as the second) and a per-issue disposition (`eligible` / `assigned` /
`assignee-unreadable` / `stale` / `unrankable` / `lane-collision`). It does not replace `--claim`
above — reading who is claimable and writing a claim stay separate calls, the same separation
`issue_claim.py` itself already makes between `--read` and `--claim` — and it does not invent a
preflight pattern or a lane pattern for an issue that named neither (#267): those stay
caller-supplied input, exactly as they are for the scripts it composes.

**A `candidates` result also carries `groups` (#1068) — read that, not the flat `candidates` list,
when deciding what to dispatch.** Each group is a suggested lane, targeting three members (never
padded to hit that number), with a per-member disposition and a per-group third state
(`candidates`/`none`/`could-not-tell`) — a group is a suggestion, never a dispatch, so still weigh it
against topic and judgement above. `ungrouped` names candidates a group could not be built for at all
(no declared files, per #267, or files that could not be resolved) — distinct from a group that
stayed short and says why. Pass `board_capped` / `board_cap_detail` in the payload when the board read
that fed this call was itself capped (#593's `per=` ceiling) — otherwise a short group because the
read was truncated cannot be told from one because nothing genuinely overlaps.

**Before #1036 this paragraph only described the script; nothing told a session to run it.**
`commands/tick.md` step 5 named `dispatch_rank.py` and `lane_setup.py --claim` as the commands to
run, by name, and a tick following that imperative literally got the four-scripts-joined-by-hand
shape #970 exists to replace — with no refusal step, so a tick that found nothing and a tick whose
claim read failed closed identically as `nothing left`. `skills/manager/phases/tick-order.md` step 5
now names this script directly for the same reason (that content moved out of `commands/tick.md`
itself for #1037, into the file a sub-manager's own steps live in).

**`held_files`'s producer, named here because #1067 found nothing in this tree named it anywhere.**
Feed `select_issues.py`'s top-level `held_files` from `lane_setup.derive_held_set(repo_slug,
worktree_root, exclude_issue=<the issue being considered>)["held"]` (sorted keys) — the same call the
lane-collision check above already runs. Its `state` and `detail` carry straight through as
`lanes_read_ok` (`state == "resolved"`) and `lanes_read_why` (`detail`, when it did not): `lanes_read_ok
is False` forces `could-not-select` before `held_files` is read at all, so a lane inventory that could
not be enumerated is never indistinguishable from a tick with no live lanes. A caller that never
populates the pair (nothing to offer) is read as "not attempted", the same posture `board_read_ok`'s
own absence already gets.

A contributor without write access cannot self-assign — GitHub restricts assignment to write or
triage permission — so this mechanism claims for the maintainer's own loop only. What an outside
contributor uses to claim an issue is a separate decision (#460); it must land somewhere this same
selection step reads, not in a channel of its own that renders an actually-claimed issue as free.

**A fourth fact the assignee field cannot carry at all: the maintainer deliberately holding an issue
open (#844).** An empty assignee field on a public repository means only "no maintainer lane holds
this" — never "nobody wants it" and never "the maintainer is willing to have it taken". A reservation
made off the tracker — in a session handoff, from memory — is structurally invisible to a sub-manager
spawned fresh into the repository with nothing (#695): it can only read what is on the tracker.
`labels.reserved` in `.oss.json` is the fix, the same opt-in shape `labels.filed_by_loop` already is
(#762) — derivable from the tracker by anyone rather than recalled — and `dispatch_rank.reserved`
reads it back, printing `[RESERVED]` beside every issue that carries it when ranking the board. A
repository that has not declared a spelling reads every issue as unreserved, never as `could-not-tell`
— there is nothing ambiguous about a label field with no candidate spelling to look for.

**The lane's top issue is the best-ranked one, by the dispatch order in `SKILL.md`'s "Deciding what
to build" (#798).** Author before priority within a band: a human ask outranks loop work of the same
or lower band, and a blocking-class defect the loop found still outranks an ordinary ask. Compute it
with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_rank.py"` rather than reading the table and
judging, and report a `could-not-rank` rather than treating it as the bottom of the board.
**Companions are chosen by file adjacency to that top issue, whatever their own rank** — the saving a
bundle buys is a shared worktree, and ranking companions again would break up the bundles worth having.

**Three issues per lane is the default, not the ceiling (#799).** Measured across 237 lanes in
this repository's own transcripts (#499): a lane's cost is dominated by fixed overhead paid once
regardless of how much work it carries — a turn-1 baseline, an orientation phase, two self-review
spawns, a full suite run — so three issues in one lane cost 16% less per issue than one issue alone,
and four or more is a cliff at 141 median turns and 68% worse per issue. The number was already
right and the default was wrong: the loop picked one issue and then went looking for companions, so
most lanes ended up carrying one. Fill to three. **Cap at three, never four**, and
`dispatch_rank.check_lane` refuses a fourth before the spawn rather than after, because past the
spawn the cost is already committed.

**Run the companion search. It is a separate call from the conflict check, pointed the other way.**
`--against` answers two different questions depending on what it is aimed at, and #918 is the tick
that aimed it at the wrong one: it checked the three lanes it had already picked against *each
other*, got `no overlap`, and recorded `no-adjacent` — a claim about the board, on a measurement that
never looked at the board. Three single-issue lanes went out with 31 issues open and every gate
green. Aim it at each *candidate's* declared lane against the top issue's, one call per candidate,
before the lane is filled. **Board size never enters that failure**: with 100 issues open the same
sequence returns the same answer, because the board is not what it read.

**A lane dispatched with fewer than three says why, in the handback, in one of four words.**
`board-exhausted` — fewer than three file-disjoint candidates remain. `no-adjacent` — the search
above ran across the board and nothing shares a file or module with the top issue. `did-not-search`
— it did not run (#918). `could-not-tell` — it ran and could not be computed. **A short lane with no reason is a defect in the tick**, and the four are a closed set on
purpose: a free-text reason is unreadable by anything but a person, which is the defect #773 filed
against a handback state carrying only prose. The last two earn their place separately — a board
never measured for adjacency, one whose measurement was attempted and failed, and one measured and
found to have none are three different facts, and #918 is the tick that proved the first was being
reported as the third.

**`board-exhausted` is now checked against the board, not merely typed (#871).** Every refusal on this
path used to be a *shape* refusal — one of the three declared words — and never asked whether the
reason was *true*: a one-issue lane could write `board-exhausted` and satisfy every gate while 35
issues sat open. `--lane-fill PRIMARY:COUNT:board-exhausted:CANDIDATES` carries the fourth,
optional field — the file-disjoint candidate count the same `resolve_lane`/`lane_overlap` sweep above
already produces — and `oss_state.py --decision` now refuses the whole call when `CANDIDATES` is at
or above three, the same way an unsupported reason word already was. Omit it and nothing changes;
name it and a lazy `board-exhausted` is refused at the one place a lane record already exists to
attach the refusal to, the way #866's advisory check could not for a declined dispatch with no record
of its own.

**#918 gives `no-adjacent` the same treatment, through the same field.**
`--lane-fill PRIMARY:COUNT:no-adjacent:CANDIDATES` carries the count of candidates *adjacent to the
top issue* — the companion search's own output, not the disjoint sweep's — and the threshold is
stricter than `board-exhausted`'s: that one needs three to be refuted, but `no-adjacent` means zero,
so **one adjacent candidate refuses it**, because one adjacent candidate is one issue this lane could
have carried. The field is one field and the word decides which count it is; `did-not-search` and
`could-not-tell` take **no** count at all and `oss_state.py` refuses one supplied anyway, because a
count refutes a claim and neither of those two makes one. Attach it whenever the search ran: a
`no-adjacent` with no count is still accepted, and is exactly as unfalsifiable as every refusal was
before #871.

**A bundle is not a cluster** — `agents/triager.md`
correctly refuses to cluster on a shared file, because a cluster claims one change fixes several
issues and needs a shared failure to back that; a bundle claims only that the fixes share a
worktree, and the file each one reads is exactly the right evidence for that weaker claim. A bundle
of two or three stays two or three fixes, never one: **each issue keeps its own test story and its
own changelog fragment**, and the pull request closes every issue it carries.

**Never bundle an issue a running lane already touches** —
check with `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" --lane PATTERN --against PATTERN`, read
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

### One fan-out, then the lane is resumed, never re-dispatched

**A tick performs exactly one dispatch (#880).** One fan-out, filled per the axes above, then the
tick sees those lanes through to merge -- a second fan-out is a second tick inside the first, and
the receipt lies for it (three lanes, one re-dispatched twice, reads as five).

**A red lane, or one whose base moved, is resumed via `SendMessage` to its own agent -- never
re-dispatched fresh at the same issue.** The agent that wrote the diff knows why; a fresh spawn
re-derives everything from nothing, paying #695's saving back as a cost (`commands/tick.md` step 7,
#818, already resumes a paused sub-manager this way; a resumed lane costs the message against a
fresh developer spawn's measured 150k-290k tokens).

**A lane's own agent can genuinely be gone -- context died, or resumed and silent twice, the bar
`agents/developer.md` sets its own review spawns -- and that is its own named state,
`agent-unreachable`, distinct from `resumed`.** A re-dispatch with neither an attempted resume nor
that finding is the defect this section stops; state which one applied in the handback.

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

**Run `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --claim --lane PATTERN [--lane
PATTERN ...]` from the clone before writing each brief, rather than typing
the base commit and the live-worktree list into it by hand.** Both rot between the moment you read
them and the moment the dispatched agent does: `main` has moved mid-tick before, and a hand-copied
worktree list has already flattened `cannot tell` to `idle` once, which is how `fix/313` and
`fix/341` were each briefed onto `README.md` forty minutes apart (#317, #360). The script hands back
the resolved base, the derived branch and worktree, and the condensed board in one call, freshly
re-derived rather than pasted — paste its board output straight into the brief so every agent knows
who else is out there. `skills/manager/phases/tick-order.md` names the same call and its three
states in full (#1037: this content moved out of `commands/tick.md` into that phase file); this is
the pointer, not a second copy of that explanation.

**`--claim` belongs only here, never on a probe above** (#705): every call used to record this
lane unconditionally, so probing several candidates before picking one left phantom records that
blocked `--derive-held` for hours. The probe forms above are now read-only; only `--claim` writes.

**`--claim` refuses without `--lane` (#788), and refuses a claim made from inside a worktree rather
than the clone (#865) -- both enforced by `lane_setup.py` itself now, with the argument in its own
code rather than only here.** #788 is an argparse `parser.error`; #865 is a report-time refusal (it
sets `effective_claim` false and prints `CLAIM REFUSED` with the reason) rather than an argparse
error -- same posture, different mechanism, both read by whoever edits the script next. Pass the
same patterns this candidate was already probed
with above; this is the one call that writes, so it is also the one call the files must be named on.
When a dispatched lane's own brief tells it to run `--claim` as its own first call, that call must
run from the clone, before the `git worktree add` (or equivalent `cd`) the brief also asks for — not
after: `.oss.local.json` is git-excluded from every worktree this loop cuts, so `--claim` standing
inside one would derive `worktree_root` from that worktree's own path and write into a registry
sibling to it, invisible to every other lane's `--derive-held` -- which is exactly what the refusal
now stops before it happens.

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

Every brief carries these eight, and `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brief_schema.py" <brief-file>` checks the draft before
the spawn — `ok` / a row per missing element / `could-not-read`. Four are checked structurally and
four are presence only, and the receipt says which: **a brief that passes is not a brief that was
reviewed** (#967). `brief_schema.py` is the symmetric half of `scripts/report_schema.py`: one checks
what goes into a lane, the other what comes back out of it.

1. **Use supertool, as an instruction not a note.** Paste verbatim:

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
8. **Re-read the composed brief for a leftover `{{...}}` placeholder before the `Agent()` call, not
   after.** There is no templating step between writing this text and it being sent -- whatever
   string is typed is what the agent receives verbatim. A sub-manager dispatching three lanes in one
   tick wrote one brief's supertool paragraph as the literal marker
   `{{PASTE THE FULL CONTENTS OF <scratchpad path> HERE}}` instead of the real blockquote content,
   caught it only after all three `Agent()` calls had already returned, and found `SendMessage`
   unavailable to correct any of them (#1022) -- so this is only catchable before the call.
   `brief_schema.py` (above) now flags any literal `{{...}}` in the draft file structurally; this
   item is the same check performed by eye for a brief composed and sent without ever touching a
   file, which the validator cannot reach.


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
  writing a brief, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preflight_check.py" --pattern
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
  the lane to catch. `preflight_check.py`'s receipt names `roots`, the paths actually searched, on
  every state including `could-not-search` — paste the whole line, `not-matched over 1 file
  (scripts/doctor.py)`, never a paraphrase of it. This is not a demand to sweep the whole tree on
  every pre-flight; a narrow probe is often the right probe. The defect is a narrow probe's answer
  wearing a repository-wide claim's clothes.
- **Select in the dispatch order, and compute it rather than feel it (#798, extended by #993).**
  Two axes, author before priority within a band. `python3
  "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_rank.py"` is the one place the table lives; call it
  rather than re-deriving it here.

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

  **Rank 1 is prose, not a row `dispatch_rank.rank()` ever returns** — nothing here can read an
  issue against the eleven-row findings table; that classification is a judgment call made when a
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

- **Rank a finding by what cannot be undone**, then by who is walking away. The eleven-row table --
  `destroys`, `discloses`, `executes`, the two `containment` rows, `forges`, `ships-local-state`,
  `misdirects`, `splices`, `fails-to-preserve`, `misreports` -- lives in
  `skills/manager/phases/findings.md` and **only there**, with the two verdict columns it carries:
  *blocks a release* and *embargo when reported upstream*, which are two different questions and
  disagree on one row. Read that file before ranking anything, and read the column you actually
  need rather than a restatement of it. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ranking_table.py"`
  prints the table's own bytes when a payload needs it verbatim. **A finding that fits no row is
  reported unranked**, never demoted to "no row, therefore minor".

- **Ask whether the fix compounds**, not whether the loop is worth it. A fix that removes a whole
  class of future defects outranks a bigger fix that removes one instance.

