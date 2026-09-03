# Review returns: what a spawn hands back, and what it did not

**Read this when** a reviewer's final message has arrived -- before you sort it, and before you write `review` in the report.

`agents/developer.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** A phase file you did not open, or could not, is a clause of your brief
that did not run: name it as an item under the report's `compliance` survey, with the reason. A rule
that did not run renders exactly like a rule with nothing to say, so the absence is stated, never
silent.

## When a spawn runs and comes back empty

That rule has a loud half and a quiet half, and only the loud half was ever written down. A spawn
that errors is handled below. This is the other one: a spawn can **execute, consume its budget, and
return an empty final message** — the review happened, the conclusions are gone. Reported honestly
and structurally that is `findings: []` under `state: checked`, which is byte-identical to a clean
review, and it has already cost this repository real findings that nobody can now recover.

So it gets its own state. `review.classes` and `review.findings` carry a fourth one,
**`returned-nothing`**, that no other survey in the report can spell — `checked` would render a real
review as a clean one, and `not-checked` claims nobody looked, which understates what is missing.
The validator refuses it without a reason.

**How you decide you are in it: compute it, do not read tone.** Both briefs already require a
sentinel — `NO FINDINGS`, and what was checked — precisely so silence is distinguishable from
cleanliness. Sorting what comes back used to be your judgment, performed once per spawn by an agent
that has just been told a review happened, and **that judgment is the step that fails silently**.
Pipe each reviewer's final message, verbatim, through the classifier:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/review_return.py" --framed - <<'MSG'
    <the reviewer's final message, exactly as it reached you, every line at this indentation>
END OF MESSAGE
MSG
```

**The indentation is the guard, not a style.** A quoted heredoc ends at the first line *equal* to
its terminator, at column zero — so a message placed at column zero decides where its own transport
ends, and everything after that point is parsed by bash as commands, in your session, with the
maintainer's credentials. That is #404, and it needs no adversary: the first observed instance was a
reviewer **quoting this very code block**, terminator included, which is an ordinary thing for a
reviewer of `agents/developer.md` to do. Indenting every line makes a content line that ends the
stream unconstructible, which is why the fix is not a longer or a random terminator — any terminator
written down here is one a message can quote.

So: **prefix every line of the message with those four spaces, blank lines included, and change
nothing else about it.** Relative indentation inside the message survives, because a fixed four
spaces come off every line. Then close it with `END OF MESSAGE` at column zero, on its own line,
before the terminator.

`--framed` refuses rather than guesses, and both refusals are `could-not-read` — nothing was
reliably looked at. It says *the framing never closed* when `END OF MESSAGE` never arrived, which is
what a message that ended the stream early looks like from in here; and it names the first line that
is not indented, which is what a half-applied prefix looks like. Neither is a verdict about the
review. Re-send it framed correctly; if it refuses twice, read the message yourself and **say in the
report that you did**.

In a clone of this plugin, prefer this tree's own `scripts/review_return.py` for the same reason the
report validator prefers it — your branch may carry a newer copy than the cache. It prints one
`VERDICT:` line and exits `0` when the return survived, `3` for `referred-not-stated`, `4` for
`returned-nothing`, `5` for `could-not-classify` and `6` for `could-not-read`. **Quote that line in
`review.classes.reason` or `review.findings.reason`.** If neither copy exists or neither runs, that
is its own outcome and it goes in the report in as many words — falling back to reading the message
yourself is fine, saying nothing about having done so is not.

Six states, and the shape of the old four-way sort is inside them. It **states** findings
(`states-findings`); or it says `NO FINDINGS` and names what it checked (`no-findings`); or it
**refers to findings it does not state** (`referred-not-stated`), which includes a `FINDINGS: <n>`
header with fewer than `n` **enumerated** under it — a header over uncountable prose is
`could-not-classify` instead, because findings written as plain paragraphs are a delivered review
and calling those lost is a false alarm you would learn to ignore; or it is empty or whitespace-only
(`returned-nothing`).
The last two are both `returned-nothing` in the report, and the `referred-not-stated` arm is the one
to be careful with, because it is the one that sounds finished. A confident sentence about work you
cannot read is not a review that found nothing.

**`could-not-classify` is a verdict addressed to you, not an answer.** It means the message carried
no sentinel, no header and no back-reference, so the tool cannot tell a review that stated its
findings in prose from one that gestured — and it refuses to guess rather than calling an
undecidable message clean. Read that one yourself and say in the report that you did. `could-not-read`
is narrower still: nothing was looked at.

The classifier decides from the bytes you hand it and nothing else, which is the point. Do not infer
a verdict from what you believe the spawn did while it ran — you did not see that, and a transcript
you happen to hold is evidence about your own session, not a return value.

The state's own definition is what makes that arm legitimate rather than a stretch: `returned-nothing`
is *the review happened and its conclusions are lost*, and an empty message is the instance it was
first observed in rather than the boundary of it. Conclusions referred to and not stated are lost in
exactly the same way and to exactly the same degree.

**What the report must say, and it is a required field rather than good manners.** Set the state to
`returned-nothing` and put in `reason` which spawn went quiet, **which of the two ways** — nothing at
all, or a gesture at findings it never stated — and **what is lost, counted**. "Came back empty" about
a spawn that returned a confident paragraph is a reason that will be read as the wrong failure.
Anything you can re-derive from your own context goes in `items` with disposition `open`, never
`fixed`: you are reconstructing somebody else's reading and cannot check the reconstruction. Say in
the same breath how many you could not recover at all. `returned-nothing` carrying items is the
normal shape, not a contradiction — and `checked` is unavailable to you from the moment one spawn
comes back empty or gestures at findings it did not state, however completely the other one
answered.

**Record the residue, and do not mistake it for the finding.** A message that referred to findings it
did not state usually leaves something behind — a count, a subject, a filename, a severity. That
residue goes into `items` as an `open` item, **quoted rather than paraphrased**, because it is the
only handle anybody will have. And it is a handle, not a finding: one lost return preserved the name
of a single file and nothing else, and because nobody owned the residue, nobody opened that file for
the rest of the session. Say what the residue is, say what it is not, and say how many findings the
count implied that you have nothing at all for. A count is the cheapest residue there is and the
easiest to drop, and it is the one that tells a maintainer the size of what is missing.

**One fresh re-spawn, and it does not erase the first outcome.** Spawn a new agent of the same type
with the same brief, once, and stop there; a second empty return is a finding, not a third attempt.
Whatever the retry hands back, the state stays `returned-nothing` and the reason names both
attempts. Converting *the reviewer said nothing* into *no findings* is the bug; converting it into
*I retried and it worked, nothing to see* is the same bug one layer up.

**Decided against, so that it is a decision rather than an omission: granting `SendMessage` to ask
the reviewer to repeat itself.** That was the missing capability the agents who hit this named, and
it is still the wrong answer. It widens a delegated agent from *spawns its own reviewers* to *can
address any live agent*, including the sibling lanes working other issues in the same round; and it
does not recover the lost message anyway, because an agent asked to repeat regenerates — what comes
back is a fresh review wearing the first one's authority. A fresh spawn buys the same thing and
says what it is.

**None of this is a finding about a particular agent type.** The count is now six across two
repositories and two days, not the two it was when this paragraph was written, and the shape did not
change with it: every observed instance was the same reviewer type and the auditor half returned
normally every time — but agent type, brief and task shape vary together in all six, and nothing
separates those explanations. **A handful of samples is not a measurement**, so nothing in this
subsection names an agent type: the rule is mechanism-agnostic and applies to whatever you spawned.
The confound is worked through once, below.

## The brief sentence is an experiment, not a fix

A sentence added to a brief to change how a model writes its last paragraph cannot be shown to work
from inside the session that adds it, and the temptation is to treat it as done because it is
written. So it is recorded here as an intervention with a baseline, and the record is part of the
change rather than a courtesy.

- **Baseline, two independent populations.** In one session in this repository, **three of roughly
  seven review spawns** executed, formed conclusions and returned a final message referring to
  findings it never stated — two of those unrecoverable, one recovered by the permitted re-spawn and
  correct, one surviving only as the name of a file. Two days later, in a different repository, all
  **three of three** developer runs in one fleet hit it, claiming ten findings between them of which
  nine are gone. The agents did not know about each other. Every instance was recorded as
  `returned-nothing` rather than `checked`, which is why there is a baseline at all.
- **Intervention 1, and it did not hold.** The sentence, the `FINDINGS: <n>` header and the
  `referred-not-stated` sort arm, in `agents/developer/review.md` and above. Together they cost three paragraphs of brief and one
  comparison. #275 and #296 were the first two instances and PR #332 shipped that language; **#392
  reports the identical shape recurring twice in one day, in two unrelated lanes, after it
  shipped.** Two prose attempts, two recurrences. That is what makes a third one the wrong move
  rather than the obvious one.
- **Whether #392's two lanes are new samples is not established, and the count is not incremented on
  them.** They were dispatched in the same fleet, in the same repository, on the same day as the
  "three of three" population above, and nothing distinguishes them from lanes already inside it.
  Counting them again would inflate the baseline the next intervention is graded against — which is
  the failure this section exists to avoid, pointed at its own arithmetic.
- **Intervention 2, and it is deliberately not prose.** `scripts/review_return.py` computes the sort
  from the returned bytes; the section above tells you to run it and quote its `VERDICT:` line. It
  asks the reviewer for nothing, so it does not fail the way intervention 1 and its predecessors
  fail. It also cannot be graded by the metric below, and that is the honest limit of it: it does not
  change how often a spawn gestures, only whether a gesture is recorded as a clean review. Its own
  evidence would be different — reports whose `review` survey states `returned-nothing` with a quoted
  classifier verdict, over reports that state `checked` with no verdict quoted at all.
- **What would count as evidence.** The same rate, over later sessions, counted the same way: spawns
  that referred without stating, over spawns dispatched. Nothing else. A session with no instances is
  one observation, not a result, and a run in which nobody counted is not a zero.
- **The confound, which is why one tempting explanation is not built on.** Every instance came from
  one spawn type and the other type answered normally every time — but agent, brief and task vary
  together, so *a fixed enumeration is harder to gesture at than a free-form list* is a hypothesis
  and not a finding. Nothing here is arranged around it, and nothing here should be read as having
  tested it.
- **What is not established at all.** Whether these spawns genuinely produced findings and lost them
  at the return boundary, or never produced them and misreported, has not been observed — nobody has
  read a reviewer's own transcript. Those are different bugs with different fixes. The header is
  chosen partly because it does not need that question answered: a count that exceeds the findings
  stated under it is the same detection either way.
- **So nothing below is relaxed on the strength of it**, and nothing above either. The
  `returned-nothing` state, the counted reason, the one permitted re-spawn and the rule that a retry
  does not erase the first outcome all stand exactly as they are. An unmeasured mitigation treated as
  a measured one would be this plugin's own defect class, one layer up: a guard nominally on, and the
  reason nobody re-reads it.

## When the spawn itself fails

**A spawn that errors because the name does not resolve is `could not run`.** Not a clean audit,
not an omission. `oss:auditor` was in exactly that state for two releases while every report that
did not quote the error read as an audit that found nothing (#81), which is why this is written
here rather than left to a reader who happens to know.

So, in order:

1. **Quote the spawn error verbatim in your report.** Paraphrasing it loses the one fact that tells
   a maintainer this was a wiring failure rather than a clean class.
2. **Re-dispatch to `general-purpose` with a pointer to `agents/auditor.md`**, carrying the same
   brief, the same diff and the same "must not edit anything". The definition still holds; only the
   name failed to resolve. Say in your report which agent actually ran.
3. **If the fallback does not run either, that is `could not run` and it stands as the outcome.**
   Report it as the third state. Do not fold the auditor's classes into the reviewer's answer to
   make the report look complete — one generalist covering both is precisely the merge this file
   spawns two agents to avoid.

The unresolved name is itself a finding about the plugin, not just an obstacle to route around.
Report it even when the fallback ran cleanly.
