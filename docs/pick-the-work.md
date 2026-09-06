# Pick the work

How the loop decides what to build next, and how a decision becomes a running developer lane.

This is the derivation, not the operator's manual. `skills/manager/phases/dispatch.md` says what to
run; this says why the shape is what it is, so the next session does not re-derive it. It is written
because that re-derivation has happened repeatedly, and each time reached a slightly different
answer.

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
| `lane-other`, dispatched solo | **built** (#1130) -- fixture-verified only; no issue has carried the label yet |
| `--claim` renders the whole `Agent(...)` call | **built** (#1143) |
| The brief validated as part of rendering | **built** (#1143) |
| `select_issues.py` fetches its own board; no stdin payload | **designed, not built** (#1143) |
| One group per lane label, rather than a partition of the board | **designed, not built** (#1143) |
| Issue bodies returned with each group | **designed, not built** (#1143) |

Today `select_issues.py` still requires a caller-built payload on stdin and returns a partition of
the whole board -- 18 groups on a 38-issue board, for a tick that dispatches at most five lanes.
Steps 1 and 2 below describe where that is going, and #1143 is the issue that gets it there.

## The steps

Five steps. Two are calls, one is a judgement, one is a paste, one is the lane running.

---

### Step 1 — Select the fleet

| | |
| --- | --- |
| **Who** | the sub-manager, once per tick |
| **Runs** | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/select_issues.py"` |
| **Input** | nothing. It fetches the board itself -- issues, labels, `author_association` -- reads `.oss.json` for the declared label spellings, and derives the held set from the lanes already running. There is no stdin payload and no `--fetch` mode. |
| **Output** | the fleet: **one group per lane label**, each carrying up to three issues, **with the full body of every issue in every group returned**. |

State, and the third must never render as the second:

    candidates        at least one lane can be dispatched, with the reason every dropped issue was dropped
    none-available    every input was read cleanly and nothing survived: a real, established absence
    could-not-select  at least one input could not be read. NEVER none-available

Per issue: `eligible` / `assigned` / `assignee-unreadable` / `stale` / `unrankable` /
`lane-collision`. Per group: its own `candidates` / `none` / `could-not-tell`, whether its adjacency
is `measured` or `inferred`, and -- when short of three -- one of `board-exhausted` / `no-adjacent` /
`did-not-search` / `could-not-tell`.

---

### Step 2 — Veto

| | |
| --- | --- |
| **Who** | the LLM. This is the only step it judges. |
| **Input** | the issue bodies step 1 already returned. **Not the board.** No further reads. |
| **Output** | for each group: dispatch it, or drop it and say why. |

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

**It also emits step 5's `--lane-fill PRIMARY:COUNT[:REASON]` token**, with the count from the claim
result and the reason carried through from the group `select_issues.py` already labelled. Nobody
computes it. That closes the same defect the label had: two calls that must agree, kept in agreement
by hand.

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

## What each call returns

### `select_issues.py`

It fetches the board itself -- issues, labels, `author_association` -- reads `.oss.json` for the
declared spellings, and derives the held set from running lanes. There is no stdin payload and no
`--fetch` mode: **one way to do it**, because a choice is how you get two behaviours with one of
them wrong.

Out: the fleet, plus three states that must never be confused --

    candidates        at least one lane can be dispatched, with the reason every dropped issue was dropped
    none-available    every input was read cleanly and nothing survived: a real, established absence
    could-not-select  at least one input could not be read. NEVER none-available

Per issue: `eligible` / `assigned` / `assignee-unreadable` / `stale` / `unrankable` /
`lane-collision`. Per group: its own `candidates` / `none` / `could-not-tell`, whether its adjacency
was `measured` or `inferred`, and -- for a group short of three -- one of `board-exhausted` /
`no-adjacent` / `did-not-search` / `could-not-tell`. A short lane with no reason is a defect in the
tick, and `oss_state.py --decision` refuses the call outright when one arrives.

It also returns **the bodies of every issue in every group it returns**, because it has already read
them: body text is what `_derive_declared_files` parses for backticked paths (#851, #1135). Two
conditions. They carry the untrusted-input fence, or a tracker body arrives looking like the tool's
own output. And a body cut to a cap says `truncated` with its full length, because a truncated body
and a short body must not render alike.

### `lane_setup.py`

One call claims every issue, registers the lane, derives base commit and branch and worktree,
resolves the file set, validates the brief, and renders the whole `Agent(...)` line.

It refuses to render on a structural brief finding, on a `subagent_type` outside
`KNOWN_AGENT_TYPES`, on a missing one, and when the primary issue is not held. It renders --
findings printed -- on a presence-only brief finding, because four of the eight brief elements are
presence-only and blocking dispatch on "this section seems missing" would stop legitimate work on a
weak signal. It always prints **a brief that passes is not a brief that was reviewed**.

**The label counts only issues that came back `claimed`.** A lane whose third issue returned
`could-not-claim-assignee` renders `x2`. Deriving the count from the request rather than the result
would replace a retype with a confident wrong number, which is worse than the retype.

`--claim`'s five states, the brief's result and the label's outcome are reported **separately**,
never flattened into one verdict.

**It also emits step 5's `--lane-fill PRIMARY:COUNT[:REASON]` token**, with the count from the claim
result and the reason carried through from the group `select_issues.py` already labelled. Nobody
computes it. That closes the same defect the label had: two calls that must agree, kept in agreement
by hand.

## The rule the steps converge on

**Every step is either a tool composing, or a human pasting what a tool composed. Never a human
composing.** Step 1 and step 3 compose; step 4 and step 5 paste; step 2 is the one judgement, and it
decides yes or no rather than producing a value. There is nowhere left in the sequence where a
number, a list or a call is assembled by hand -- which is the only property that made every defect
below unreachable rather than merely warned against.

## The one judgement left to the LLM

Read the bodies the call already handed you -- two or three issues, not the board -- and ask one
question: **is this worth a lane?** Stale, settled elsewhere, needs the maintainer, wrong for the
project. That is the judgement no ranking function reaches, and it is where a tick has genuinely
earned its keep: skipping an issue a previous tick had already resolved as a design question.

**The machine picks; the LLM vetoes.** Ranking, grouping, disjointness and staleness are mechanical
and belong in code -- an agent re-deriving them by eye spends a lane's worth of context to reach a
worse answer, and reports no third state when a read fails. Everything an agent does between the
selection call and the veto is waste.

## Why the shape is this, and not what it was

Every defect found in this area came from the same place: **a step composed by hand, turn after
turn, guided by prose read once.**

- A tick's three `Agent()` calls all omitted `subagent_type` and silently ran as `general-purpose`,
  caught only because the tick happened to notice (#989). Nothing distinguishes a lane run by the
  wrong agent from one run by the right one: same brief, it commits, it reports.
- `fleet_label` promised in its own docstring to refuse a label built from an incomplete bundle. It
  could not: its only check was that the caller's list was non-empty, and it never saw the real set.
  A three-issue lane labelled `[534]` rendered with no multiplier and no error -- the #539 failure,
  reachable through the module written to close it (#1143).
- The issue list was retyped between `--claim` and `--label`, two calls that had to agree. A
  hand-carried list that must match another call's list is the #317 defect `lane_setup.py` exists to
  close, reappearing inside it.
- `brief_schema.py` had one call site and no backstop: a dispatcher could simply not run it, and a
  brief composed inline in the prompt was never checked at all, since it only read files.
- A payload built by hand with the key `labels` instead of `declared` returned `none-available` --
  "every input was read cleanly and nothing survived" -- on a board carrying 24 live candidates.
  Nothing looked wrong. The module written to prevent an absence-produced-by-the-tool produced one,
  because its input was shaped by the caller it delegated input to.
- Omitting the `author_association` fetch rendered eight, then ten, issues `unrankable` in two
  separate runs. Always the caller's omission, never a property of the board.

`dispatch.md` had already written the conclusion before any of this was built: *prose read once at
the top of a phase file is not present at the moment a call is typed by hand, turn after turn, so
the fix is not a stronger sentence -- it is not composing the call by hand at all.*

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
- **`lane-other`'s solo rule is fixture-verified only.** No issue on the board has carried that
  label yet, so the branch has never executed against a real one.
- **Nothing measures fleet under-fill.** A tick that dispatches one lane and a tick that dispatches
  five produce identical handbacks. `--lane-fill` records a short *lane*; nothing records a short
  *fleet*, so the failure is invisible unless a human asks.
