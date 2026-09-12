# Review returns: what a spawn hands back, and what it did not

**Read this when** a reviewer's final message has arrived -- before you sort it, and before you write `review` in the report.

**Say whether you read it.** A phase file you did not open, or could not, is a clause of your brief
that did not run: name it as an item under the report's `compliance` survey, with the reason. A rule
that did not run renders exactly like a rule with nothing to say, so the absence is stated, never
silent.

## When a spawn runs and comes back empty

A spawn that errors is handled below. This is the other half: a spawn can **execute, consume its
budget, and return an empty final message** — the review happened, the conclusions are gone.
Reported as `findings: []` under `state: checked` that is byte-identical to a clean review.

So it gets its own state. `review.classes` and `review.findings` carry a fourth one,
**`returned-nothing`**, that no other survey in the report can spell — `checked` would render a real
review as a clean one, and `not-checked` claims nobody looked, which understates what is missing.
The validator refuses it without a reason.

**How you decide you are in it: compute it, do not read tone.** Both briefs already require a
sentinel — `NO FINDINGS`, and what was checked — precisely so silence is distinguishable from
cleanliness. Sorting what comes back by your own judgment is the step that fails silently. Pipe each
reviewer's final message, verbatim, through the classifier:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/review_return.py" --framed - <<'MSG'
    <the reviewer's final message, exactly as it reached you, every line at this indentation>
END OF MESSAGE
MSG
```

**The indentation is the guard, not a style.** A quoted heredoc ends at the first line *equal* to
its terminator, at column zero — so a message placed at column zero decides where its own transport
ends, and everything after that point is parsed by bash as commands, in your session, with the
maintainer's credentials (#404). Indenting every line makes a content line that ends the stream
unconstructible, which is why the fix is not a longer or a random terminator — any terminator
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

`returned-nothing` is *the review happened and its conclusions are lost*; an empty message is one
instance of that, not the boundary of it. Conclusions referred to and not stated are lost in exactly
the same way and to exactly the same degree.

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
only handle anybody will have. And it is a handle, not a finding. Say what the residue is, say what
it is not, and say how many findings the count implied that you have nothing at all for. A count is
the cheapest residue there is and the easiest to drop, and it is the one that tells a maintainer the
size of what is missing.

**One fresh re-spawn, and it does not erase the first outcome.** Spawn a new agent of the same type
with the same brief, once, and stop there; a second empty return is a finding, not a third attempt.
Whatever the retry hands back, the state stays `returned-nothing` and the reason names both
attempts. Converting *the reviewer said nothing* into *no findings* is the bug; converting it into
*I retried and it worked, nothing to see* is the same bug one layer up.

**Decided against: granting `SendMessage` to ask the reviewer to repeat itself.** It widens a delegated agent from
*spawns its own reviewers* to *can address any live agent*, including sibling lanes in the same
round; and an agent asked to repeat regenerates, so what comes back is a fresh review wearing the
first one's authority. A fresh spawn buys the same thing and says what it is.

**None of this is a finding about a particular agent type.** Agent type, brief and task shape vary
together in every observed instance, and nothing separates those explanations. **A handful of samples
is not a measurement**, so nothing here names an agent type: the rule is mechanism-agnostic and
applies to whatever you spawned.

## The brief sentence is an experiment, not a fix

A sentence added to a brief to change how a model writes its last paragraph cannot be shown to work
from inside the session that adds it. Two prose interventions have shipped and the shape recurred
after both (#275, #296, PR #332, then #392). `scripts/review_return.py` is the third and is
deliberately not prose: it computes the sort from the returned bytes and asks the reviewer for
nothing. Its limit, stated: it does not change how often a spawn gestures, only whether a gesture is
recorded as a clean review.

**The baseline it is graded against, and do not re-count a population already in it.** In one session
here, three of roughly seven review spawns referred to findings they never stated; two days later, in
another repository, three of three developer runs in one fleet did the same (#275, #296, #392).

**The confound, so nothing is built on it.** Every instance came from one spawn type — but agent,
brief and task vary together, so *a fixed enumeration is harder to gesture at than a free-form list*
is a hypothesis, not a finding.

**What would count as evidence**, if you are grading any of this: the same rate, over later sessions,
counted the same way — spawns that referred without stating, over spawns dispatched. Nothing else. A
session with no instances is one observation, not a result, and a run in which nobody counted is not
a zero. Whether these spawns produced findings and lost them at the return boundary, or never
produced them and misreported, has not been observed; do not build on either.

**So nothing below is relaxed on the strength of it**, and nothing above either. The
`returned-nothing` state, the
counted reason, the one permitted re-spawn and the rule that a retry does not erase the first outcome
all stand exactly as written. An unmeasured mitigation treated as a measured one is this plugin's own
defect class one layer up.

## When the spawn itself fails

**A spawn that errors because the name does not resolve is `could not run`.** Not a clean audit,
not an omission (#81).

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

**A name that fails to resolve is not the only way a spawn fails, and the two are not the same
outcome (#1468).** Observed: a lane whose `Agent` tool was refused, absent from its own grant, or
erroring identically on every `subagent_type` it tried -- not one name failing while another
succeeds, but the tool itself unreachable one level down, even though the dispatching session's own
`Agent` tool worked throughout. That is total unavailability, not a resolution failure, and step 2
above is not a remedy for it: re-dispatching to `general-purpose` hits the identical wall that
stopped `Explore` and `oss:auditor`, so a second identical failure is not new evidence and is not
worth spending a turn on. Report `not-checked` per `agents/developer/review.md`'s own clause instead
of `could not run`, with the verbatim refusal or error text in `review.spawn_error` -- and never let
either failure mode read back as a clean review with nothing behind it.

## Fixing a finding is a new diff, and sometimes a new subject (#1047)

**A review's subject is the diff at the instant it ran; the fix for its findings is a later diff,
and nothing makes that one a subject again by default.** PR #921's fix for two findings shipped
unreviewed, and a later re-audit found two more real bugs inside it. Most fixes are one line and
re-reviewing them is waste, so compute the trigger rather than trusting the moment you most
believe the work is done:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/fix_commit_scope.py" --repo . --base <pre-fix> --head HEAD
```

`needs-second-pass` -- 3+ files touched, or any file this repo governs with its own byte-budget
table -- means spawn one more lightweight round over the fix alone before reporting, same shape as
the first. `within-scope` means the fix stayed small; `could-not-determine` is its own outcome,
never a quiet `within-scope` -- say so and fall back to judgement.

**The third condition is not mechanized on purpose.** Whether a touched function is a guard is a
judgement about behaviour a file list cannot answer -- if the fix changes what a guard *does*,
treat it as `needs-second-pass` regardless of what the script reports.
