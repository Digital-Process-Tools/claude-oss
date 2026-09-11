# Inbound: refusing an issue, an outside pull request, and answering a person

**Read this when** step 3 of `skills/manager/phases/tick-order.md` -- "act on what is open before
starting anything new" -- and the board holds something the loop did not itself generate: an issue
nobody filed on our behalf, a pull request from someone other than the loop, or a comment on either
since the last tick. This is inbound work with a person waiting on it, and it is checked before
dispatch, in the same slot as any other unfinished act (#1394).

---

**No new forge call.** Step 2 of `tick-order.md` already reads the whole board in one call; this is
a branch on that data, not a second read. `scripts/inbound_triage.py` carries the classification --
`is_inbound_issue`, `classify_pr`, `comments_needing_answer` -- and every one of its inputs is a
field the board read, or an already-open per-issue call, already carries.

**This step classifies. It does not act.** Closing an issue, merging an external pull request and
replying to a comment are all public acts in the maintainer's name from an unattended loop -- a
different question from reading what arrived and deciding what it deserves, which is complete on
its own (#1394's own stated boundary). `#1395` covers the queue those acts go through. Every outcome
below may legitimately be "surface it to the maintainer" -- that is not a weaker answer, it is one
of the three this step is allowed to give.

## Issues not filed by the loop

`inbound_triage.is_inbound_issue(labels, declared)` reads the same `labels.filed_by_loop` label
`select_issues_rank.rank` already reads for its own author axis -- three states, not two:
`True` (inbound), `False` (the loop's own filing), `None` (the label is not declared at all, so
this cannot be told and must not be read as `False`).

An inbound issue already ranks above the loop's own backlog at every priority band
(`select_issues_rank`'s author axis) -- **accepting and ranking it is the existing path.** What was
missing is the second outcome `CLAUDE.md` already states as doctrine: **refuse it, with the reason
stated**, rather than leaving a correct, reproducible, well-written issue open forever because it
does not move toward this project's own goal.

**The reason has to be one of six, exactly as spelled, or the refusal does not happen.**
`inbound_triage.REFUSAL_REASONS`:

  duplicate | out-of-scope | not-reproducible | needs-info | wontfix | superseded

`inbound_triage.validate_refusal_reason(reason)` checks membership; nothing folds case or accepts a
synonym. Deciding *which* of the six applies to a given issue is a judgment call this module does
not make for you -- the same split `gate3_disposition.py` draws between the auditor's own verdict
and what happens to the tag once it is given. What this closes is the other half: a stated ground
this loop can point to, versus "declined" with nothing behind it, which is a verdict with no
evidence and the exact shape this repository refuses everywhere else.

**Recording and performing the closure is out of scope here** (#1395) -- surface the issue, the
reason and the chosen ground for the maintainer, or for the queue #1395 builds.

## Pull requests whose author is not us

`skills/manager/phases/merge.md` states the one line this used to be: *never auto-merge an
external-contributor PR*. That is still true, and it is not the whole treatment.

`inbound_triage.classify_pr(pr)` reads `author_association` (raw GitHub spelling or already
translated), `ci_state` and `mergeable`, and answers one of four states:

- **`not-inbound`** -- a maintainer-authored pull request. This is the loop's own PR, or the
  maintainer's; `merge.md` already governs it and this step has nothing further to say.
- **`green-and-mergeable`** -- external, CI green, and GitHub itself reports it mergeable. Both
  conditions: a green rollup on a branch GitHub cannot merge cleanly is not actually ready.
  **The name reports a measurement, not an instruction (self-review, #1394)** -- an earlier draft
  called this state `ready-to-merge`, a name that reads as a verdict authorising the one act
  `merge.md` forbids absolutely for an external contributor's pull request. This state is a
  classification, never a merge -- the never-auto-merge rule in `merge.md` still applies in full;
  what changes is that the tick now has something to surface rather than ticking past it silently.
- **`needs-answer`** -- external and anything else: red, pending, unknown CI, or not cleanly
  mergeable. A person has to look at it -- review, request changes, explain a decline -- and this
  step does not compute which.
- **`could-not-tell`** -- the association could not be translated at all. Never folded into
  `not-inbound` or either real outcome; an unrecognised value is not evidence of anything.

A pull request that sits `needs-answer` or `green-and-mergeable` for a second consecutive tick with
no change is worth naming in the tick's own decision -- "an outsider's pull request sits unread for a
fourth day" is the exact failure #1394 was filed to close, and a tick that dispatches three fresh
lanes past one is not free of it just because nothing crashed.

## Comments new since the last tick

`inbound_triage.comments_needing_answer(comments, since_iso, own_login=None)` filters an
already-fetched comment list (a per-issue `gh-issue:N:full`, or a pull request's own thread -- never
a board-wide fetch of its own) to what arrived after `since_iso` and was not authored by the loop or
the maintainer. Returns `None`, not an empty list, when `since_iso` is falsy: no watermark to compare
against and "compared, and nothing is new" must never render alike.

Every comment this returns is either answered this tick or named as needing the maintainer -- the
same two-way split as the issue and pull-request sections above, and the same boundary: answering it
publicly is #1395's act, not this step's.

## What this buys the statusline, and what it does not yet

The issue that filed this phase also asked for a count beside `trap.d`'s own backlog: unruled
issues, unreviewed pull requests, unanswered comments. That count exists now (#1406):
`scripts/statusline.py`'s `inbound_reading()` computes `unruled_issues` and `unreviewed_prs` on the
board's own refresh cadence, cached and rendered by `_inbound_field` (`inb Nis Npr`).
`next_action.py` calls the same function directly for a fresh reading rather than trusting a stale
cache. Only `unanswered_comments` stays unmeasured -- it always reports `None`, because counting it
needs a per-thread walk over every open issue and pull request that neither of those callers builds;
`scripts/statusline.py`'s own `?`-for-unmeasured convention is exactly what stops that particular gap
from rendering as a false, confident zero.
