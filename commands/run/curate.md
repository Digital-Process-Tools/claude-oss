---
description: Curate the traps logged in trap.d/ into jit-context rules — promote, merge, decline or defer, one fragment at a time.
allowed-tools: Bash
---

Read what is waiting:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/trap_curate.py" .
```

Three answers, and the third is the one that matters: `N waiting`, `none waiting`, and
`could-not-read` — a directory that could not be listed **never** reports zero, because a pass that
was silently skipped and a cycle with nothing to curate would otherwise render identically.

`none waiting` ends the pass. Say so and stop; there is nothing here to decide.

## What this pass is for

A lane that hit a trap logged it without deciding anything — no dimension, no match pattern, no
judgment about whether it is worth keeping. **All of that judgment is this pass**, and it is taken
here rather than in the lane because it needs every fragment visible at once: "these three are one
rule" is not visible from inside the lane that wrote one of them.

## The pass decides. The pull request is the review

This step used to stop here and hand the fragments to a maintainer, one at a time, because
`/oss:curate` was a command a person typed and a human reading the terminal was the only review that
existed. It is now a step `/oss:run` reaches on its own, and a pass that pauses to ask is a human put
back into the loop wearing a different sentence — the same failure this issue exists to remove, not
a milder version of it.

**Decide every fragment.** Every outcome below writes a file — a rule under
`.claude/jit-context/<paths|tools|vocabulary>/00-manual/`, a body merged into an existing rule, a
decline line in that layer's `00-README.md` — and every file this pass writes in one run goes up as
**one pull request**. The PR is the review: the maintainer reads it and can refuse any part of it,
the same way every other write this loop makes into this repository already works. State each
decision's reason **in the PR body** as a sentence a reviewer can disagree with — never a bare
verdict — because that sentence is what gets reviewed, not the fact that a decision was made.

## Read every fragment first, then decide

Read them all before deciding any of them. A fragment read alone gets promoted; the same fragment
read beside two others gets merged, which is the cheaper answer and the one only this position can
see.

For each fragment, exactly one outcome:

| outcome | what it means | what to do |
| --- | --- | --- |
| **promote** | this is a rule, and no existing rule covers it | write it into `.claude/jit-context/<paths\|tools\|vocabulary>/00-manual/`, with a firing proof — below |
| **merge** | an existing rule already governs this situation | add it to that rule's body, and pay for the growth if the rule is getting long |
| **decline** | not worth a rule: too narrow, already obvious, already stated elsewhere, or an observation about one incident rather than a rule | one line in that layer's `00-README.md`, naming what was declined and why |
| **defer** | genuinely cannot be decided alone, even with every other fragment visible — ambiguous dimension, an incident too thin to tell rule from noise, a call this pass is not positioned to make | leave the fragment in `trap.d/`, unchanged, and name it plus the reason in the PR body |

**Delete the fragment for promote, merge and decline — the directory ends this pass empty of
everything it resolved.** A queue allowed to carry over gets skipped for being too big, and then it
is a landfill rather than a backlog. **Leave a deferred fragment exactly where it is**, so the next
pass finds it rather than a decision made to clear the queue.

**A declined trap must leave its trace** in `00-README.md`, or the next lane to hit the same thing
files it again and this pass declines it again. The rule builder skips that file by name, so an
absence recorded there reads as a decision rather than an oversight.

**`defer` is a real answer, not a delay dressed up as one, and it is bounded.** The old rule here was
*do not leave a fragment for next time* — written for a human who can always reach a decision given
enough time in the room. A spawn sometimes honestly cannot: it lacks the standing to judge, or the
fragment is too thin to tell a real rule from a one-off. Forcing a decline in that case records a
wrong decision as a made one, which is worse than an honest deferral. But a pass that defers most or
all of what it read has curated nothing — if `defer` is more than a small fraction of the batch, say
so plainly in the PR rather than reporting a completed pass; that is itself the finding (the
fragments arrived too ambiguous for this pass, or this pass lacked context it needed), not a curation
this issue's fix produced.

## One pass takes the whole backlog, uncapped

Whether one pass takes every waiting fragment or caps itself at some batch size is a decision, not
an accident, and the answer is: **take all of it.** *Read every fragment first, then decide*, above,
is not a courtesy — a merge candidate split across two batches is invisible to whichever batch does
not hold its sibling, so capping the batch size directly breaks the co-visibility this pass exists
for. 36 fragments in one pass, the live count this issue was filed against, is a lot of judgment to
hold at once; the answer to that is `defer` on the ones this pass cannot actually decide, not a
smaller batch that quietly loses the cross-fragment view. The PR that results can be large — that is
the cost of the review being real, not a reason to shrink the batch to make the PR look smaller.

## Choosing the dimension, which is the whole decision

| dimension | fires on | use when |
| --- | --- | --- |
| **paths** | a file path in the tool call | the knowledge belongs to a folder — "before you touch this, know X" |
| **tools** | tool name plus a command pattern | the fix is an interception before a specific call runs, not information |
| **vocabulary** | keywords in the prompt | a domain somebody names out loud |

**Default to paths.** The folder is the situation, and the expensive mistakes happen while touching
something. A keyword that is also ordinary English fires constantly and pulls its whole body in every
time it does.

## Prove it fires before you commit it

A rule that never matched and a rule with nothing to say **render identically**. Rebuilding the index
is not evidence. **Drive the hook, in both directions**, following the *Prove it fires* section of
the `claude-jit-context:vocabulary` skill — that skill owns the recipe and the paths, and a second
copy of them here would go stale the first time that plugin moves a script. Two payloads, never one:

- one naming a file the rule **must** govern, and
- one naming a file it **must ignore**.

The must-fire payload proves the rule exists. **The must-stay-silent payload is the one that finds
real defects** — a match pattern one character too wide fires on every session that touches the
repository, and nothing downstream will ever tell you.

**Put a known-good rule in the same batch.** A probe whose payload the hook does not understand
reports silence, which is indistinguishable from a rule that does not fire; a control you have
already seen fire is what tells those apart. That is logged in `trap.d/` because it happened while
this command was being written.

**Report both results in the pull request that promotes the rule. A promotion with no firing proof in
the PR is refused by this pass itself, not by whoever reviews it** — the mechanical guard is what
makes deciding alone safe, and it does not relax because nobody is watching in real time.

## What this pass must not do

- **Do not add a required field to the fragment format.** Every one is friction at the moment
  friction stops the lesson being written, which is what `trap.d/` exists to remove.
- **Do not promote on volume.** A trap logged twice is evidence about frequency, not about whether a
  rule would fire correctly.
- **Do not decline a fragment just because deciding it is hard.** `defer` is for that; `decline` is
  for a fragment that genuinely is not worth a rule. The two must never be interchangeable exits from
  the same discomfort.
- **Do not ask.** There is no maintainer to ask mid-pass — the PR this pass opens is the only place
  a human's word enters, and it enters after the decisions are made, not before.
