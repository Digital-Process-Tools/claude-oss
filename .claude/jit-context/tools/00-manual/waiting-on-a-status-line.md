---
title: "Waiting on a status line: the negation contains the assertion"
description: "NOT ALL GREEN contains ALL GREEN. Wait on a transient state disappearing, never on a terminal state appearing, and match the line rather than the receipt."
tool: Bash
match: ~(until|while) |grep -q
mode: remind
---

**A substring match cannot see the word in front of it.** Good status output prints the negated
form (`NOT ALL GREEN`, `not configured`, `no findings`, `could not`), so a positive-signal grep is
satisfied by the exact sentence saying it should keep waiting -- `grep -qE "ALL GREEN"` matched
`NOT ALL GREEN` and returned in seconds with 12 checks still pending (#1066, #1072).

Rules, in order of how much they buy:

- **Wait on a transient state disappearing, never a terminal state appearing.** Absence has no
  antonym to collide with: `until ! ... | grep -q "pending"; do sleep 45; done`.
- **Match the line, not the receipt.** A whole-receipt alternation (`completed|success|failure|
  cancelled`) fires on a mid-progress line naming several of those words at once. Anchor on the
  field's own line, e.g. `^Status:` (#1180) -- the same defect in GitHub's own PR-body parser is
  `pr-body-closing-keywords.md`.
- **A written-out third state hands the alternation more vocabulary to collide with, not less
  (#1530).** A careful "not concluded" sentence containing the word "failed" satisfied a
  `(GREEN|NOT GREEN -- .*(failed|FAIL))` grep on the first poll. Grep a counted line (`Legs:` /
  `pending`) instead of the prose one; a tally carries no vocabulary to collide with.
- **Enumerate the terminal side when one exists, not the transient one (#1369).** A transient
  vocabulary is rarely closed -- an undocumented `pending` status was missed by a loop enumerating
  only `queued`/`in_progress`. `status == "completed"` (anchored) covers everything else regardless
  of what the transient set grows.
- **Inverting the grep means inverting the keyword too.** Rewriting a "wait while pending" loop into
  a "wait for completed" loop by negating only the `!`/`until` leaves the predicate doubly-inverted
  and exits immediately -- happened one minute after fixing the enumeration bug above, in the same
  loop.
- **A `cmd | grep -q` pipeline cannot carry three states.** `cmd` failing outright (rate limit,
  network blip) is indistinguishable from "looked, found nothing incomplete" -- both exit the grep
  with nothing selected. Use a tool with its own exit status (`gh run watch --exit-status`), or check
  the ask's own exit code separately before interpreting its output.
