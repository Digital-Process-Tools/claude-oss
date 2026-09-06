# Pick the work

How the loop decides what to build next, and how a decision becomes a running developer lane.

This is the working description of the sequence: what runs, in what order, who runs it, and what
each step takes and returns. `skills/manager/phases/dispatch.md` is the operator's manual a session
follows mid-tick; this is the whole shape in one place, so it is read rather than re-derived.

## What is built, and what is designed

**Read this before the steps.** Parts of the shape below are on `main` today and parts are not, and
a document that reads as current when it is aspirational is this repository's own defect class.

| | state |
| --- | --- |
| Two entry points, submodules behind each | **built** (#970, #1069) |
| Ranking by author x priority | **built** (#798, #993) |
| Grouping, three per lane, per-group states | **built** (#1068) |
| A file set derived from the `lane-*` label | **built** (#1129) |
| The lead using body-declared paths; `measured` vs `inferred` adjacency | **built** (#1135) |
| `lane-other`, dispatched solo | **built** (#1130) |
| `--claim` renders the whole `Agent(...)` call | **built** (#1143) |
| The brief validated as part of rendering | **built** (#1143) |
| `select_issues.py` fetches its own board; no stdin payload | **built** (#1145) |
| One group per lane label, rather than a partition of the board | **built** (#1146) |
| Issue bodies returned with each group | **built** (#1147), **narrowed** (#1180): the default fleet print no longer attaches them at all -- see step 1 and step 2 below |
| `--claim` emits step 5's own `--lane-fill` token | **built** (#1148) -- `COUNT` is fully mechanical (the claim's own held issues); `REASON` is derived from a `--group-state` flag carrying the group's own `state` field for three of its four values, or an explicit `--short-reason` override for the fourth (#1153) |

**Every row is built. None of it has been observed in a live tick.** The five steps below were
tested, and each was run against the real board by hand during the round that built them, but no
sub-manager has yet dispatched through the sequence end to end: every lane dispatched while it was
being built had its `Agent(...)` call composed by hand, which is the one thing the design forbids.
The first tick to run it is the first evidence, and is where to look for what is still wrong.

Two known gaps, neither blocking:

- **Body-derivation over-claims what an issue merely cites.** An issue quoting nine paths resolves
  to all nine. A bundle that should not have been bundled is the cost; the group's own `overlap`
  field shows it.
- **Nothing counts a short fleet.** A lane returning `none` is visible in `lanes`, so an idle lane
  is legible in the output itself -- but no metric records it, so a run of under-filled ticks is
  only noticed by a reader.

## The shape

Two entry points. Two calls. Nothing hand-assembled between them.

    select_issues.py   ->  the fleet: one group per lane, each up to three issues   [reads only]
    lane_setup.py      ->  a pasteable Agent(...) call, and the claim is now yours  [writes]

**The boundary between them is read versus write, and it is the reason there are two rather than
one.** `select_issues.py` never mutates anything, so asking "what could be dispatched?" is free and
repeatable. `lane_setup.py` writes assignees, the lane registry and a worktree. Collapsing them
would make it impossible to look without claiming, which breaks a dry run and the tick's own preview
step.

**Everything below the entry points is a module, not a command.** That is the `doctor.py` model --
twenty files behind one entry point -- and it is the part of this repository that has held up.
Modules keep each concern testable; a single command keeps the caller from composing anything by
hand. Both matter, and they are not in tension.

## The steps

Five steps. Two are calls, one is a judgement, one is a paste, one is the lane running.

---

### Step 1 — Select the fleet

| | |
| --- | --- |
| **Who** | the sub-manager, once per tick |
| **Runs** | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/select_issues.py"` |
| **Input** | nothing. It fetches the board itself -- issues, labels, `author_association` -- reads `.oss.json` for the declared label spellings, and derives the held set from the lanes already running. There is no stdin payload and no `--fetch` mode. |
| **Output** | the fleet: **one group per lane label**, each carrying up to three issues, **no issue bodies attached** (#1180). |

State, and the third must never render as the second:

    candidates        at least one lane can be dispatched, with the reason every dropped issue was dropped
    none-available    every input was read cleanly and nothing survived: a real, established absence
    could-not-select  at least one input could not be read. NEVER none-available

Per issue: `eligible` / `assigned` / `assignee-unreadable` / `stale` / `unrankable` /
`lane-collision`. Per group: its own `candidates` / `none` / `could-not-tell`, whether its adjacency
is `measured` or `inferred`, and -- when short of three -- one of `board-exhausted` / `no-adjacent` /
`did-not-search` / `could-not-tell`.

**#1180: the default print no longer attaches every issue body.** #1147 attached the full, fenced
body of every group member so step 2 never had to read the tracker again -- but the bodies
themselves were measured at 66% of a real fleet's serialized bytes, enough on their own to push the
whole payload over the harness's output-truncation cap. When that happens the caller gets a
persisted-file pointer instead of a fleet, and step 2 ends up re-reading every issue by hand anyway
-- the exact cost #1147 existed to remove. `select_fleet(..., include_bodies=False)` is what
`main()`'s default print now calls; a library caller of `select_fleet()` directly still gets bodies
attached by default (`include_bodies=True`), unchanged.

---

### Step 2 — Veto

| | |
| --- | --- |
| **Who** | the LLM. This is the only step it judges. |
| **Input** | the surviving groups' own issue bodies -- a second, bounded call (below), never the board. |
| **Output** | for each group: dispatch it, or drop it and say why. |

**The bounded second call**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/select_issues.py" --bodies N N ...`,
naming exactly the issue numbers in the groups step 1 handed back (never the whole board) -- one more
`gh` read, bounded to a handful of numbers rather than the whole fleet, in exchange for a payload
that fits. Returns `{"state": "ok" | "could-not-fetch", "bodies": {"<number>": {"body",
"body_truncated", "body_length"}}, "not_found": [N, ...]}` -- the same fenced-body shape #1147
already uses, keyed by issue number. `not_found` names a requested number that is not (or no longer)
on the open board, a stated absence rather than a silently missing key.

One question per group: **is this worth a lane?** Stale, settled elsewhere, needs the maintainer,
wrong for the project. Nothing else -- not ranking, not grouping, not disjointness, all of which
step 1 has already decided better.

---

### Step 3 — Claim and compose

| | |
| --- | --- |
| **Who** | the sub-manager, once per surviving group |
| **Runs** | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <primary> --claim --lane <pattern> --claim-also <N> ... --phrase "<phrase>" --subagent-type oss:developer --brief <brief-file>` |
| **Input** | one group from step 1, and a brief file the caller wrote |
| **Output** | a pasteable `Agent(...)` line, the `--lane-fill` token for step 5 -- and the claim, the lane registration and the worktree are now written |

It claims every issue, registers the lane, derives base commit / branch / worktree, resolves the
file set, validates the brief, and renders the call.

**Refuses to render** on a structural brief finding, on a `subagent_type` outside
`KNOWN_AGENT_TYPES`, on a missing one, and when the primary issue is not held. **Renders, findings
printed**, on a presence-only brief finding. Always prints *a brief that passes is not a brief that
was reviewed*.

**The label counts only issues that came back `claimed`** -- a lane whose third issue returned
`could-not-claim-assignee` renders `x2`.

`--claim`'s five states, the brief's result and the label's outcome are reported **separately**,
never flattened into one verdict.

**It also emits step 5's `--lane-fill PRIMARY:COUNT[:REASON]` token** (#1148), with `COUNT` from the
claim's own held issues -- nobody computes that by hand any more. `REASON` comes from `--group-state`
(#1153): the caller pastes the group's own `state` field from step 1's own JSON, unchanged, and
`--claim` mechanically derives `no-adjacent` (from `none`), `could-not-tell` (from `could-not-tell`)
or `did-not-search` (from `lane-other`) -- three of the four closed-vocabulary words, each an exact
match for what that `state` value already means. The fourth, `state == "candidates"` (some companions
found, the group still ran short), has no safe translation: `board-exhausted` is a claim about the
WHOLE board's remaining disjoint candidates (#871), which a single group's own `state` never
establishes, so it is never guessed at there -- an explicit `--short-reason` is still required for
that one state, and always overrides `--group-state` when both are given. Never invented when
neither is given: a short lane with no derivable and no explicit reason renders a token with no
reason at all, so step 5's own `--decision` refusal (#852) still fires on it downstream.

---

### Step 4 — Dispatch

| | |
| --- | --- |
| **Who** | the sub-manager |
| **Input** | the rendered line from step 3 |
| **Output** | a running developer lane |

Paste the line, fill `prompt` with the brief -- the one part only the caller can write. Launch every
lane of the fleet in a single message so they run concurrently.

---

### Step 5 — Record

| | |
| --- | --- |
| **Who** | the sub-manager, at the tick's own `--decision` call |
| **Runs** | `oss_state.py ... --lane-fill PRIMARY:COUNT[:REASON] --lane-dispatch-state ISSUE=STATE[:WHY]` |
| **Input** | the tokens step 3 emitted, one per lane. **Paste only** -- nothing is computed here. |
| **Output** | the tick's record, refused outright if a short lane arrives with no reason |

**Why this is not folded into step 3.** `oss_state.append` writes **one entry per tick**,
append-only and atomic, and refuses an entry carrying no decision. A claim is not a tick decision,
and it happens before the tick has one. Folding would need either one entry per lane -- turning a
record of what the tick decided into an event log -- or mutable entries, which trades away the
atomic write whose point is that a failure leaves the history unchanged rather than half-written.
Both cost more than the single call the fold would save. So the *write* stays here; only the
*composing* moved to step 3.

---

## A lane is a lane label

`.oss.json` declares five: `lane-dispatch`, `lane-doctor`, `lane-prose`, `lane-release`,
`lane-scaffold`. Each names a subsystem, in its own GitHub label description:

    lane-dispatch :: Tick machinery: select_issues, lane_setup, ranking_table, tick_handback, review_return
    lane-doctor   :: Diagnostics: doctor.py, doctor_check_*.py, install-audit, the oss-workspace launcher route
    lane-prose    :: The loop's markdown: skills/manager, agents, commands, CLAUDE.md -- budgets and parity
    lane-release  :: Release and changelog: release_*.py, assemble_changelog, the six gates, version sites
    lane-scaffold :: What is written into another repo: scaffold.py, oss_rules.py, the ownership contracts

**So the fleet size is the declared lane count, and it is not a number anybody invented.** Five lane
labels, five concurrent lanes, up to three issues each: at most fifteen issues in flight. The bound
comes from configuration like every other per-repo fact, and it needs no measurement study to
justify it.

**And the lanes are disjoint by construction.** The labels already partition the codebase by
subsystem, which is the exact property the grouping machinery otherwise tries to establish by
comparing file sets and hoping. Two issues in different lanes cannot collide, because their lanes
name different files. That is what makes them lanes rather than buckets: one worker each, no
crossing.

`lane-other` (#1130) is the exception that proves the rule. It means *triaged, and no lane owns
these files* -- so it has no subsystem, cannot be made disjoint by construction, and is dispatched
**solo**: never given a companion, never offered as one.

## The rule the steps converge on

**Every step is either a tool composing, or a human pasting what a tool composed. Never a human
composing.** Step 1 and step 3 compose; step 4 and step 5 paste; step 2 is the one judgement, and it
decides yes or no rather than producing a value. There is nowhere left in the sequence where a
number, a list or a call is assembled by hand.

**The machine picks; the LLM vetoes.** Ranking, grouping, disjointness and staleness are mechanical
and belong in code -- an agent re-deriving them by eye spends a lane's worth of context to reach a
worse answer, and reports no third state when a read fails. Everything an agent does between step 1
and step 2's veto is waste.

## What this deliberately does not do

**It does not make grouping thematic.** A lane is joined by files, not by subject. Two issues that
touch one file must not go to two lanes; two issues about the same topic that touch nothing in
common have no reason to share one.

**It does not infer a file set from an issue body's prose.** #267 settled that. A path a human wrote
in backticks is a declaration and is read; everything else is not guessed. An issue that declares
nothing and carries no lane label resolves to **unknown** -- never to an empty file set, which would
read as disjoint with everything and bundle an unexamined issue into any lane on the board.

**It does not claim precision it lacks.** A file set derived from a lane label is a whole subsystem,
not one issue's files, so `lane_patterns_source` records `declared` / `derived-from-body` /
`derived-from-label` / `None`, and a group records whether its adjacency was `measured` or
`inferred`. A one-file overlap and a twenty-seven-file same-label overlap are different claims and
must not render alike.

## Still open

- **Body-derivation over-claims what an issue merely cites.** An issue quoting nine paths as
  examples resolves to all nine. Label-derivation over-claimed a subsystem; body-derivation
  over-claims whatever the author quoted. Distinguishing a path an issue *claims* from one it
  *cites* is unsolved.
- **Nothing counts a short fleet.** A lane returning `none` is visible in `lanes`, so an idle lane
  can be read off the output -- but no metric records it, so a run of under-filled ticks is noticed
  only by a reader who looks.
- **The sequence has not run in a live tick.** See the table above.
