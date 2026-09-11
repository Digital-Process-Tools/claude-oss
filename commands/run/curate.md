---
description: Curate the traps logged in trap.d/ into jit-context rules — promote, merge or decline, one fragment at a time.
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

**This is an interactive pass with the maintainer.** It is the one place in this loop where a human
is the point rather than the fallback. Do not promote, merge or decline a fragment without the
maintainer's word on it.

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

**Delete the fragment in every one of the three cases.** The directory ends this pass empty. A queue
allowed to carry over gets skipped for being too big, and then it is a landfill rather than a backlog.

**A declined trap must leave its trace** in `00-README.md`, or the next lane to hit the same thing
files it again and this pass declines it again. The rule builder skips that file by name, so an
absence recorded there reads as a decision rather than an oversight.

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

Report both results in the pull request that promotes the rule. A promotion with no firing proof is
a rule nobody has established is reachable.

## What this pass must not do

- **Do not add a required field to the fragment format.** Every one is friction at the moment
  friction stops the lesson being written, which is what `trap.d/` exists to remove.
- **Do not promote on volume.** A trap logged twice is evidence about frequency, not about whether a
  rule would fire correctly.
- **Do not leave a fragment for next time.** Decline it — that is what declining is for, and it is
  recorded rather than silent.
