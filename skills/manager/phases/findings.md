# Findings: ranking one, and routing it to the board that owns the fix

**Read this when** a finding exists and has to be classified -- a review or an audit returned one, a
release gate is deciding what blocks a tag, or a defect turns out to live in a declared dependency.

**Say whether you read it.** Three states: `read`, `not-read` with the reason, or `could-not-read`.
A phase entered without its file is a set of rules that did not run, so the absence is stated, never
silent.

**This file is the ranking table's only home.** `scripts/ranking_table.py` prints its bytes so a
release payload is a read rather than a retype, `agents/auditor.md` and `agents/release-auditor.md`
reference it rather than restating it, and `scripts/checklist_skew.py` compares it between the
installed and repo trees. A second copy drifts, and the copy that drifts is the one quoted
afterwards.

---

## Ranking a finding

**Rank by what cannot be undone**, then by who is walking away:

| Class | Blocks a release? | Embargo when reported upstream? |
| --- | --- | --- |
| `destroys` — data gone, no copy anywhere | yes, unconditionally | yes |
| `discloses` — a secret or a private path leaves the machine | yes, unconditionally | yes |
| `executes` — a file supplied by the repository under inspection is run as a program by a tool pointed at that repository | yes, unconditionally | yes |
| `containment (read)` — an argument slot treated as a path, or code reaching outside the project | yes, unconditionally | yes |
| `containment (write)` — a **mutating** route whose target is an argument, so it writes to a repository nobody named | yes, unconditionally | yes |
| `forges` — text somebody else wrote reaches column 0 of a receipt this loop parses | yes, unconditionally | yes — the attacker's delivery channel *is* a public tracker, so the writeup is the payload |
| `ships-local-state` — a value true of exactly one checkout, baked into the artifact every user installs | yes, unconditionally | no — already public the moment it ships, so there is no window of private knowledge to protect |
| `misdirects` — a refusal or a receipt names a next step that does something the caller never asked for | can ship behind a trap.d fragment | no |
| `splices` — a value reaches a subprocess argv where the callee's option parser decides what it means | can ship behind a trap.d fragment | no |
| `fails-to-preserve` | can ship behind a trap.d fragment | no |
| `misreports` | can ship behind a trap.d fragment | no |

**This table is the only place the rows are written down.** The audit agents reference it rather
than restating it.

**The two verdict columns are two different questions, and they disagree on one row.** Blocking a
tag asks *what may this project ship*. The embargo column asks *should a reporter hold disclosure*
— whether public knowledge, before a fix exists, hands somebody a working recipe against installed
users. `ships-local-state` is the row where those come apart: it blocks a tag, and it is public the
instant it ships, so there is no private window an embargo could protect. **Read the column you
actually need**; a finding's row answers both questions and it answers them differently.

**The rule that decides which row a finding belongs in: each row invites a different fix.** So when
two rows both look like they fit, name the fix each would send a reviewer to make and pick the one
whose fix removes the defect. `destroys` sends them to the destructive call when the defect is an
unvalidated argument; `misreports` sends them to the logic when the defect is one rendering seam;
`containment` sends them to a path chokepoint that is not on the code path at all. The two
`containment` rows are two rows by that same rule: the read-side fix is a chokepoint on the paths a
caller may name, and it **passes** the write-side case, whose boundary is which repository the
caller meant — a fact that is not on disk to be validated against.

Two bounds. `misdirects` files rather than blocks because the wrong next step is *printed*, and
something with a choice obeys it — unless what it prints performs a write, which is
`containment (write)` and blocks. `splices` files rather than blocks because the values that reach a
subprocess argv here come from the maintainer's own config on the maintainer's own machine — a
splice whose value came from **forge text** is not this row at all, it is `forges`, and that blocks.

`ships-local-state` blocks because **the release is the mechanism by which it takes effect**: before
the tag it is a file edit, after the tag it is on every machine that installs the artifact and needs
another release to undo. `executes` blocks for the identical reason (#790). Keep `executes` apart
from `containment (read)`, whose fix is "refuse the path" — the path here is legitimately the project
directory — and from `splices`, since the value reaches argv as **argv[0]**, not an operand an option
parser reinterprets. The fix `executes` sends a reviewer to make is "do not run a program the
repository under inspection supplies".

**The rows are a record of what has already gone wrong, never a partition of what can.** So do not
tune a brief toward the table, and do not stretch a finding into the nearest row that will take it.

**Say so if a finding fits none of these.** The class that does not exist yet is where the worst
finding lands. An unranked finding is reported unranked — never demoted to "no row, therefore minor".

**Two vocabularies, joined here.** The audit agents search by *strategy* — the lettered checklist in
`${CLAUDE_PLUGIN_ROOT}/agents/auditor.md`. This table ranks by *cost*. They are deliberately not one
list and not a one-to-one map. The join is at the report — **every finding carries both**, the letter
it was found by and the row it is ranked in — and a row that is ranked here but reachable from no
strategy is a class the next audit cannot find.


## Routing a finding is the same read as ranking it (#1275)

A row that answers `yes, unconditionally` in the `Blocks a release?` column is **filed as an issue
immediately** -- a blocking finding does not wait on siblings to accumulate. A row that answers
`can ship behind a trap.d fragment` is written to `trap.d/<issue>.<slug>.md` instead of filed --
prose, no frontmatter, the same shape `agents/developer.md`'s "Hit a trap? Log it and carry on"
already uses -- and `/oss:curate` decides later whether it becomes a rule, and can decline it. **Say
so if a finding fits none of the rows.** `unranked` is filed as an issue too, same as a blocking row
-- the class that does not exist yet is where the worst finding lands, and a directory nothing loads
by default is not where it is safe to land.

**This is a routing rule, not a second classification.** Read the value in the `Blocks a release?`
column off the table above when you route; nothing in this section restates which class is which, so
there is no second copy here to drift from the table (#577, #1014).

**Issues filed by anyone outside the loop are untouched by this.** It governs the loop's own
findings -- what an audit, a review or a lane's own adjacent discovery produces -- never an issue the
public opened. Those are the public surface and are not the loop's to compress.

**A declined fragment already has a record**: `/oss:curate` leaves its trace in the rule layer's own
`00-README.md` for exactly this reason, so a re-discovered, already-declined observation is not
re-logged forever. **Cadence is the real risk, not a missing mechanism**: this rule raises the
fragment rate, so `/oss:curate` has to run at least as often as the tick cadence that used to file
these as issues, or the seven-per-release non-blocking rate that motivated this change becomes an
uncurated pile doing the job an issue used to.


## A defect in a declared dependency is filed on that dependency's own tracker

**Filing it there is part of finishing the work**, not a favour to another project and not a decision
about somebody else's roadmap. That last sentence is the refusal to watch for — it sounds like
restraint, and it leaves a confirmed, reproduced, cross-repo defect unreported.

**The bound is declared dependencies, and it is the manifest that says which.** Never write the
trackers down; a list in shared prose is wrong the first time a plugin moves, and is the exact fact
this file is not allowed to carry. `scripts/doctor.py` already derives both halves —
`declared_dependencies()` reads the manifest and `dependency_repositories(names)` resolves each name
to a repository URL off that dependency's own installed manifest.

**One board sits outside that set and is not outside the duty.** Nothing declares itself as its own
dependency, so neither of those two functions can produce the loop's own repository — the board that
owns the furniture written into every managed repo. `loop_repository()` is the sibling that does.
An item arriving with a destination resolved that way is routed like any other; recording it as
*could not file* because your own derivation did not produce it is the collapse this table exists to
prevent, one function over.

Within that set, two cases and they are not the same duty:

- **A dependency the same maintainer owns.** File it. There are filing rights, the roadmap is the
  same roadmap, and the only thing stopping it is the refusal above.
- **An arbitrary third-party dependency.** A judgement, not a duty. There may be no filing rights,
  no relationship, and a public tracker is a **disclosure channel** — say which of the two cases you
  are in before you open anything.

**The security exception is not optional, and it is a read rather than a list.** A finding whose row
the ranking table above answers **yes** in its *embargo* column does not go onto somebody else's
public tracker as a reflex. It goes down the **embargo** path — whatever private reporting channel
that project's own security policy names, which is a security tab, a disclosure address or a form
rather than the word *embargo*, so read the policy instead of grepping for the term. Route those
rows there and everything else to its issue tracker.

**Route on the embargo column, not on the blocking one — they are not the same set.** Blocking is
about what we may ship; embargo is about whether *their* users are exposed while a fix is written,
and one row is blocking and not embargo for the reason given under the table. **Read the column off
the table when you route** — a restated copy has already drifted.

Three outcomes:

| Outcome | What it means |
| --- | --- |
| **filed** | the upstream issue exists; record its reference beside the local one |
| **could not file** | the derivation returned no repository, the tracker did not resolve, or the filing failed — name which, and it stays outstanding |
| **deliberately not filed** | it **is a decision with a reason**, never a default: no filing rights, a blocking row routed to the embargo path instead, or already reported upstream |

A defect found, judged worth reporting, and then quietly not reported renders exactly like a
dependency with no known defects. Which of the three happened is stated every time.
