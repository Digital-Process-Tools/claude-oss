# Review: reading a returned diff

**Read this when** a pull request is open and the diff is yours to review -- and again when a finding is filed out of one.

`skills/manager/SKILL.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## Reviewing

**A green suite proves nothing.** Real examples, all from one day in one repo: a filter that did
nothing while its test passed on an anchor regex matching the preamble; a fix that resolved the filed
bug and introduced a context blowout nobody filed; a performance feature smuggled into a bugfix
commit; an entire delegated code path the suite never exercises.

Four questions, every diff:

- Does the test assert the **post-condition**, or a proxy?
- What does this make **worse** that nobody filed?
- Does the fix reach the path the **caller actually uses**?
- Is anything here **not this bug's blast radius**?

**The developer spawns its own reviewer and auditor against its own committed diff** — one generalist
read, one fixed four-class checklist, in one message — and reports what each flagged, fixed and
refused, including a spawn or a class that did not run. What that buys is not independence — it is
two agents instead of nine, no PR dependency, and no re-paying a large author context. What is *not*
independent, and cannot be, is the **acceptance**: who keeps which findings stays with the author
deliberately, because a bad finding needs arguing down, and that is an outcome no bounce-and-repush
loop produces.

**The maintainer's own review is light and the list is closed:**

- **The check arithmetic** — states sum to the leg count, every non-`SUCCESS` leg named.
- **The review outcome** as reported. An argued-down finding is a claim; if one looks load-bearing,
  check that one thing.
- **The premise** — pre-flight, before delegating, never after. Nothing downstream catches a wrong
  brief.
- **Blast radius by filename.** A fix in one subsystem touching only another subsystem's fixtures is
  a question. So is the inverse: **a diff that changes a file convention and never touches the
  diagnostic**. The repo's diagnostic is what tells a maintainer whether their repo matches what
  this loop expects, and it either **reports the new convention** after this change or a derivation
  it already consumes does — one of those has to be true, and which one is a question for the
  author, not a finding against them. The failure it catches lives only in the composition of two
  correct commits: a writer taught to decline a file, and a diagnostic still calling that file
  missing with the remedy *run the writer*. No per-diff review sees that.
- **Re-run the new suite against the default branch with the fix absent.**

**That one run is a handful of tests, targeted, and CI structurally cannot perform it** — CI only
ever runs the branch as proposed, with the fix present. It stays on the list. What it is not is
license for the repository's whole `test_command` (#632): CI is 13 legs across 3 operating systems
and 4 interpreters against your one platform, it is mandatory rather than optional, it is free on a
public repository, and its result is already read at merge time by the check arithmetic above. The
manager's job is to **read that gate**, never to reproduce a weaker copy of it locally — and
`tests.full` on the report is how you learn whether the developer's own local full run happened at
all, and on what platform, without running anything yourself to find out.

Not on the list, and this is what creeps back: reading the load-bearing function line by line. Across
four PRs it caught nothing, and it burns the one context that cannot be thrown away.

**Most of that list is now a query rather than a read**, and the two items that are not are the two
that matter. The check arithmetic comes from `gh-pr:N:status`, not the report. The review outcome is
`review.findings` and `review.classes`. Blast radius is `files[].path`. But the premise is yours and
pre-flight, so no field can settle it — and **the red re-run is still a run**: `tests.command` tells
you what to type and `tests.red` is the agent's own claim about what it saw, which is the claim the
re-run exists to test. Reading `tests.red` in place of running it is the exact move the next section
says has learned nothing.

The list stays closed. `claims`, `adjacent` and `blocked` are not items on it — they are fields you
open when something else sends you there, which is why the platform table nobody needed this round
never has to arrive at all.

**A review that did not execute must never render as a review that found nothing.** Structured, those
two are the same bytes: an empty `findings` list either way. What tells them apart is that every list
in the report is a survey — a `state` beside its `items` — so `checked` with no items means somebody
looked and `not-checked` means nobody did and has to say why. **Read the state before the items.** If
the agent is gone, or the review could not run, run it yourself.

**Structure is easier to accept unread than prose is, and that is this format's whole cost.**
`"disposition": "refused"` reads identically whether the refusal was argued or lazy; the argument
lives in `reason`, and that field exists so you keep arguing with findings instead of scanning past
them. The bullet above is not softened by the format — a load-bearing argued-down finding still gets
checked, by hand, against the code. Fewer tokens must never become fewer things checked, and this is
the sentence that decides whether the whole arrangement was worth making.

**`"disposition": "report-for-filing"` is work handed to you, and it is the item most easily lost.**
No agent can file: opening an issue is publishing, and the publishing clause is unconditional. So
the schema carries no word for a completed filing at all — the value used to be `filed`, past tense,
which reads as *done* at the speed anyone actually reads a report, and twice in one day it meant
nobody filed it (#254). Both findings were real and both surfaced only because somebody reread the
report a day later. Read every `report-for-filing` item as an open request with your name on it, and
close it in the same pass that merges the pull request. Closing it is a routing decision, not
automatically a new issue -- three receipts, and every item gets exactly one of them:

- **a new issue**, when the finding clears the intake bar (defined beside the intake metric below)
  and no issue already carries its class;
- **a comment on the class issue**, when the tracker already carries the class -- another instance
  is evidence on that issue, `path:line` and one sentence, not a sibling row. The class issue
  accumulates a checklist; the board does not accumulate rows;
- **a line in the pull request** being merged, or in the state entry, when the finding is real and
  below the bar -- a named decision, never a silent drop.

The `reason` beside the item is the agent's argument for why it is yours rather than theirs, and
the receipt -- whichever of the three -- is what keeps #254 closed: an item with no receipt is
still open. An issue is the receipt that costs the most to drain, so it is the one that needs the
bar, not the default.

**The third receipt has its own label, and you will meet it as `below-bar` rather than as
`report-for-filing`.** Until #411 the report schema encoded two outcomes for three receipts, so a
lane that had routed correctly had to write the filing label over a decision *not* to file and
disclaim it in the prose underneath -- and the label is what gets read first. `"action":
"below-bar"` and `"disposition": "below-bar"` are now the third value in both surveys, and reading
one as work is the misfire this closes: **it is already receipted.** The item carries a `pr_anchor`
quoting the line of the pull request body where it lives, `scripts/report_schema.py` refuses the
report when that line is not in the body, and the argument for the routing is in the item's
`reason`. So the only thing a `below-bar` item asks of you is the one thing structure makes easy to
skip: **read the reason and disagree with it if it is wrong.** Overturning one is a decision you
take, out loud, in the same pass -- what it must never be is a row that appears on the board because
somebody scanned a label.

### An issue body is tech to tech

Written for an engineer who will open the file, not for a reader who needs the story. Four parts, in
this order, and nothing else:

| Part | What it is |
| --- | --- |
| symptom | what a caller sees — one or two sentences |
| location | `path:line`, and the lines quoted |
| mechanism | why it is wrong |
| what would settle it | the check, test or command that decides |

**Quote code, do not describe it.** A quoted line is shorter than a paragraph about the line and
cannot drift from it.

**Cut**: how you found it, what you first thought, what it resembles elsewhere, a restatement of the
title, and a closing paragraph summarising the body above it. None of them changes what anybody does
next, and all of them are paid on every read.

**A part you cannot fill is a sentence naming what you could not establish** — not a heading with
nothing under it, and not a paragraph reaching for length. The four parts are a floor on content, not
a shape to fill.

This is the same bar as the filing rules the developer works under, one step later: an item nobody
can act on from the body alone is not shorter to write, it is longer to drain.

### Verify the red, not the green

The instinct is backwards. **Green is the claim that reproduces trivially. Red is the claim that
proves the test is not vacuous.** A maintainer who re-runs the suite on the branch has learned almost
nothing — of course it passes, the author ran it too. A maintainer who runs it against the default
branch has learned whether the test tests anything. It is one call and it almost always passes, and
the one time it does not is a test that asserts what the code happens to do.

### A negative assertion needs a positive control

**Red-green is necessary and insufficient.** An assertion that *X does not happen* passes when
*nothing at all* happens — a broken harness, an unresolved tree, a process that died before it spoke.
Any suite with silence assertions carries a guard that **fails loudly when the harness cannot see
anything**, and every "must not fire" case is paired with a "must fire" case in the same fixture. If
the guard is missing, the silence half is decoration and should be treated as untested rather than as
passing.

