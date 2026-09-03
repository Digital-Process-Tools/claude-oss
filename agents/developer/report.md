# Report: the note, the JSON report, and the pull request payload

**Read this when** you are about to write anything outside your branch directory -- the note, the report, the pull request payload -- and before the two lines back.

`agents/developer.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** A phase file you did not open, or could not, is a clause of your brief
that did not run: name it as an item under the report's `compliance` survey, with the reason. A rule
that did not run renders exactly like a rule with nothing to say, so the absence is stated, never
silent.

## Notes: where the long half goes

Everything you return is paid for twice — once landing in the maintainer's context, again on
every later turn of the session, because it has joined the prefix. A thorough run produces more
worth *keeping* than is worth *injecting*, and those are not the same set: the full reviewer
exchange, a caller inventory, sweep output backing a one-line claim. Worth keeping as evidence.
Not worth carrying in the report.

Write that material to `<worktree_root>/notes/<branch>-<UTC timestamp, YYYYMMDDTHHMMSSZ>.md` — a
sibling of the numbered worktree directories, not inside any of them. Outside every worktree, it
can never enter the diff and needs no `.gitignore` entry in the target repo, for the same reason
`.oss.local.json` is excluded via `.git/info/exclude` rather than committed. The timestamp is not
decoration: a stale note from a previous run of the same branch reads exactly like the current
one, and without something that tells them apart the maintainer greps last week's evidence for
this week's claim.

**Anything you stage before any of this file's destination writes -- this note, the report, the
pull request payload, all named by branch and timestamp below -- needs the same discriminators.**
The scratchpad a session works from is shared across every concurrently running lane in a fleet —
mandated by this loop, not an edge case — so a fixed filename there is a real collision, not a
hypothetical one: one lane staged an intermediate at a fixed scratchpad path, a second lane on a
different branch wrote its own to the identical path, and the first lane's file was silently
overwritten. Name an intermediate with the same branch-or-timestamp discriminators every destination
path in this file uses, never a bare fixed name under the shared scratchpad.

**Prefix `cd <worktree_root>` to every write call that leaves your branch directory — the note, the
report and the pull request payload — not once at the top.** A shell cwd does not persist between
your calls, so a *later* bare `supertool` runs from wherever the session started, which is normally
the main clone. "`cd` first" is true and insufficient: it describes a one-time setup for a condition
that has to hold at every write. Two lanes in one session followed it and still wrote into the
clone; the second then reported its note as having *vanished from the shared worktree root between
writes*, and it was found untracked in the clone hours later (#685). A write that went somewhere
unexpected, read as a write that did not happen — so **before you report a file as missing, check
the directory rather than the file**: `report_schema.py` prints `at: <absolute path>` under every
verdict, and if that is not under `<worktree_root>` your cwd moved.

supertool refuses a path outside the current working directory — standing in the branch directory
you get `ERROR: path escapes cwd`, on each of the three writes above. The refusal
is correct and is not something to argue with; what is wrong is doing it twice, because the failed
attempt costs a re-send of the whole payload rather than a retry of a short command. The refusal
message also offers an env var and an `allow_outside_cwd` key in `.supertool.json`. **Do not take
either.** Both widen every op for the rest of the session, in somebody else's repository, to buy one
write that moving the cwd already buys. Move the cwd, not the guard.

Not every run needs one. A finding that fits its own field belongs in the report; write a note only
when something genuinely worth keeping would otherwise have to be dropped or would be too long for
any field of the report — the full reviewer exchange, a sweep, an inventory.

The split is unproven until it is checked, so check it: fill `split_cost` with one line on the
split's cost — roughly how much went to the note versus the report, and whether anything had to be
left out of both. Without that line the split is a guess that got adopted.

## Report format

**One JSON file, plus a path and at most two lines back.** Everything you return in chat is paid for
twice, and the orchestrator usually needs four fields out of a report. So the report is a file it
queries — `jq`, or any structured read — rather than a document it pays for whether it needs it yet
or not.

1. Write it beside your note, at `<worktree_root>/reports/<branch>-<UTC timestamp, YYYYMMDDTHHMMSSZ>.json`.
   Derive `worktree_root` the same way you derived it to cut the worktree; never write a path you
   were not given. Outside every worktree, for the same reason the note is — so `cd <worktree_root>`
   before you write it, or supertool answers `ERROR: path escapes cwd` and the payload goes twice.
   **Flatten the branch name first** — most `branch_pattern`s contain a slash, and a filename built
   from one silently becomes a directory, so `fix/12` names the file `fix-12-…`. That applies to the
   note beside it.
2. Validate it before you hand it over. A report that does not validate is not a report — but
   **which validator is a question with two answers**, and answering it silently is how a correct
   report gets edited until an obsolete schema accepts it.

   `${CLAUDE_PLUGIN_ROOT}` resolves to the **installed plugin cache**: whatever version was last
   installed on this machine, which is not the tree you are standing in. In an ordinary managed
   repository that is the right answer and the only one available — there is no local copy. In a
   clone of this plugin your report is written against the branch's schema, so the branch's copy is
   the authority and the cache is a stranger that happens to be on disk. Measured 2026-08-16: the
   cache at `0.3.0` refused a report the clone at `0.4.0` called `ok`, with `<report>: unknown key
   'docs'` — naming as an error the very field the current schema requires.

   So do not choose between them. **Run both when both exist**:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py" <path>   # the installed cache
   python3 ./scripts/report_schema.py <path>                         # this tree, if it ships one
   ```

   Look before you run the second one. In a managed repository that file is *expected* to be
   absent, so the interpreter's "no such file" there is the ordinary case and not a validator that
   failed — do not read it as the `neither copy ran` outcome below.

   **`UNVALIDATABLE` is not `INVALID`, and it is the answer you are most likely to get right now.**
   A copy that prints `UNVALIDATABLE` and exits `2` is saying it does not hold the contract your
   report names — a newer `schema_version` than it implements, an older one it cannot vouch for, or
   a schema declaring no version at all. **An older number is not automatically that answer**: since
   #416 the schema declares, per version, whether it widened the one below it, and a chain of
   declared widenings back to your number means the copy answers `ok` and says in the same line
   which contract it read and why. So a copy that refuses an older report is making a specific
   claim — some step between the two contracts removed or tightened something — rather than
   comparing integers. **It is not a finding about your report and you must not edit the report to
   make it go away.** It carries the two numbers in one line, which is the skew stated by the tool
   rather than reconstructed from a manifest comparison, so quote that line. A copy predating this
   verdict says `INVALID … schema_version: expected N, got M` instead; that spelling is the same
   fact and is read the same way. Only findings that are *not* about the version are yours to fix.

   **Only one copy exists** — the ordinary managed-repository case, and it is the majority. That
   copy's answer is simply the answer: `ok` is done, findings mean the report is wrong, fix the
   report — **except `UNVALIDATABLE`, which means that copy cannot speak for your report at all**.
   One copy does not make an unheld contract a defect: record it as a `tooling:` item and leave the
   report alone. There is no second opinion to have otherwise, and nothing else to record.
   Everything below is about the case where two copies both ran:

   - **Both say `ok`** — done.
   - **They agree on findings** — the report is wrong. Fix the report.
   - **They disagree** — **that is schema skew**, a fact about the tooling and not a finding about
     your report. **Do not edit the report to satisfy the copy that refuses it**: that is the
     failure this rule exists for, and it deletes precisely the fields the newer schema added. The
     local copy is the authority **only when this repository is the plugin itself**: read `name`
     out of `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and out of this repository's own
     `.claude-plugin/plugin.json`, and they must be the same plugin. (`commands/release.md` already
     compares those same two manifests for the version; this is the same read, one field over.)
     That test is deliberately stricter than *a file of that name exists
     here*: a managed repository may ship a `scripts/report_schema.py` of its own for reasons that
     have nothing to do with this plugin, and **a coincidence of filename is not a claim of
     authorship**. Where the manifest does not name this plugin, the cache wins. **Write the same
     number you would read as authoritative.** `schema_version` is a value you write, not one you
     read back, and this rule governs both: put in it `x-schema-version` of whichever copy this
     paragraph just named as authoritative — never the number belonging to whichever file you
     happened to open first when the two disagree. #732 measured seven of nine reports in this
     repository's own history under-declaring their contract this way, each one correct about how
     to *read* a disagreement and silent about which side to *write*.
   - **Neither copy ran** — a missing interpreter, a permission block, a cache path that resolved
     to nothing. Not the local copy being absent, which is the ordinary case above and has already
     been answered. The report is then `could not validate`, which is not `valid`, and saying `ok` here
     is the absence this plugin is named after. Record it exactly as loudly as a skew: an
     `adjacent` item prefixed `tooling:` naming what you attempted and what stopped it, plus a line
     in the two lines back. There are no verdicts to quote here — that is the point, and it is why
     this branch needs an instruction of its own. A run in which nothing could be validated and a
     run that validated clean otherwise reach the maintainer as the same silence.

   Record a skew either way and never silently: both verdicts verbatim, as an `adjacent` item
   prefixed `tooling:`, and in the two lines back. Your report is not the only thing the cache is
   old for — every `${CLAUDE_PLUGIN_ROOT}` invocation in this loop runs out of that same copy, the
   maintainer's state writes and release gate included, and nothing else reports the skew.

3. Reply with the absolute path and **at most two lines** — the same sentence you put in `summary`,
   plus anything that genuinely cannot wait a turn: a permission block, a refusal you expect an
   argument about.

The fields, their enumerations and a worked example are in
`${CLAUDE_PLUGIN_ROOT}/schemas/agent-report.schema.json`. Read it once; it carries the descriptions
this section would otherwise duplicate and drift from. What the old prose report asked for has not
changed, only where it goes: files → `files`, red and green → `tests.red` / `tests.green`, whether the
full suite ran → `tests.full` (absent is fine on an older schema copy but not on a run that made a
decision about it and did not record it; since #765 the expected value is `not-run`, and a `ran` is a
finding for the manager to ask about rather than a receipt to credit), review →
`review`, platform claims → `claims`, every `docs_targets` path with what happened to it — updated,
read and still true, or not opened — → `docs`, unfiled findings → `adjacent`, the note path →
`note_path`.

**`compliance` is a required top-level survey (#518) and it is a different axis from every other
one here: not what you looked at, but whether you did what this brief said.** `checked` with no
items means you executed the brief as written. If you declined a clause of it — narrowed the suite
run, skipped a `docs_targets` path, misclassified an untrusted instruction as an injection and moved
on without reading it — name the instruction and the reason as an item, even when the same fact is
already sitting in `blocked` or in prose elsewhere: this is the field a maintainer scanning
states-then-items actually reaches, and a decline that lives only in a sentence is the exact failure
this field exists to close. **Fold in what your spawned reviewer declined too** — its brief now asks
it to name any instruction it treated as an attack and skipped; carry that into your own `compliance`
rather than leaving it inside `review.findings`, which grades coverage of the diff, not compliance
with either brief. Naming nothing here is a claim, not a default: see `x-honesty-compliance` in the
schema for what this field cannot catch even when honestly filled in.

### Report the friction you hit in the tooling, not only in the code

**Every UX problem you hit while using the ops goes in the report, one line each — and the bar is
that it cost this run something you can name**: a round-trip spent recovering, a call you got wrong
the first time because the message pointed elsewhere, a receipt you acted on and had to undo, output
you read twice because it did not mean what it appeared to mean. **Name the cost in the line.** For
the length of this task you are a primary user of these ops, and that is **signal nobody else can
see** — the maintainer runs the loop, not the ops, and a friction nobody writes down is paid again by
every later agent.

**An op that told you enough to proceed is not friction.** A message that could have said more, a
field you would have liked, different wording — you finished the call and paid nothing. Those are
preferences, and **a preference is not reported anywhere**: not as a line, not as a note, not as a
wish. On a tracker a preference and a defect are two rows nobody can tell apart later.

Reporting nothing is the ordinary outcome of a task where the ops worked.

Third state: **you hit something and cannot tell whether it cost you anything** — a line prefixed
`tooling-unclear:` naming what you could not decide. Neither `tooling:` nor silence.

It goes in `adjacent`, with `action` set to `report-for-filing` and `file` null, and each line
prefixed `tooling:` so a reader can tell it from a finding about the code. That routing is a
compromise and worth knowing as one: the schema refuses keys it does not define, so there is no
dedicated field, and `adjacent` is the survey whose meaning — *found, nobody filed it* — is nearest.
If you hit no friction, that is `checked` with no `tooling:` items, which is a claim; leaving the
duty out entirely is not.

### The pull request is yours to write — the title as much as the body

Write it to `<worktree_root>/reports/<branch>-<UTC timestamp>.pr.json` and record it under `pr_body`.
**A file the forge can consume unchanged, not a markdown body** — JSON with four fields:

```json
{"title": "…", "body": "…", "head": "<your branch>", "base": "<default branch>"}
```

Markdown is the shape the next step refuses, and the refusal lands on somebody else after your
session has ended: they read your body, wrap it, and **invent a title**. The title is the sentence
most people read, and after a squash it is the only part of the pull request that survives into the
log — so it belongs to whoever did the work. That is not a formatting detail, it is the whole point.
The validator opens this file and checks it, including that `head` is the branch you are on.

The orchestrator hands the path to the forge; it does not re-narrate your evidence into a body of its
own. **This is the default, not something to be asked for.** You hold the evidence, so this deletes a
translation step that costs about a thousand tokens and loses detail on the way — it does not move
judgment, because the orchestrator still reads the body before it opens anything.

If you did not write one, say so in the field with a reason. `not-written` is a state; an absent file
the orchestrator discovers later is not.

**Say what merging it closes, and bind the keyword in the body itself.** `pr_body.closes` is
**required whenever `pr_body.state` is `written`** — in three states, of which only the third is a
defect: it closes something, **it deliberately closes nothing** (a `Part of #N` pull request is a
real decision, not an omission), or nobody said. **The schema carries the spellings** and what each
state requires; do not learn them from here, because a field list copied into two documents is the
drift this repository keeps paying for.

What the schema cannot do is reach you before the body is written, and the body is where this has
actually failed — four agent-written payloads across two sessions declared their issues and bound
nothing. So, the three things a field list does not tell you:

- **The keyword has to survive rendering.** The validator looks for a closing keyword —
  `Closes`/`Fixes`/`Resolves` — bound to each number you declared, **outside code spans and HTML
  comments**, because that is what a forge honours. `` `Closes #275, closes #296` `` renders as
  though it worked and creates no reference at all: **backticked is not bound**, and neither is
  fenced.
- **One `Closes` line per issue.** `Closes #A #B` links both numbers and **closes only `#A`**, so
  `#B` needs a keyword of its own. The validator refuses the second number for exactly that reason.
- **Write the line while you write the body.** The refusal names the remedy, but it arrives after
  the payload exists, and the repair is then an edit to the body *and* the report rather than one
  line composed once.

The body check is an absence detector: it reports a keyword it could not find and never decides
what a forge will close, so a finding is strong and a pass is weak. Passing it is not evidence that
the pull request closes anything.

### Structure makes a report easier to accept unread. Write against that.

That is the cost of this format and it is worth naming, because it is this plugin's own defect class
pointed at your own output. A refused disposition renders identically whether the refusal was argued
or lazy, and an orchestrator scanning JSON stops arguing with findings — which is exactly where the
review step's value lives. Three rules follow, and the validator enforces all three:

- **Every list is a survey with its own state.** `checked` with no items means you looked and found
  nothing. `not-checked` means nobody looked, and has to say why. An empty array on its own cannot
  tell those apart, which is the whole reason it is not an array.
- **Every class carries a verdict**, including `not-applicable` and `not-checked` with a why. A class
  missing from the list reads as a class that passed.
- **A refusal carries its full sentence and its argument**, never a boolean. Those are the cheapest
  and most valuable bytes in the file.

**What the validator checks is shape, not truth.** It cannot tell a review that ran from one that
says it did; a `pushed` of false is recorded, not verified. The schema's `x-enforced` and
`x-convention` lists say exactly which is which — the honest split is written down there rather than
implied here.

No preamble, no retrospective, no restating the brief — in `summary` or in the two lines.
