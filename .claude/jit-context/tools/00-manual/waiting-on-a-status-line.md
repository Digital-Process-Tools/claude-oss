---
title: "Waiting on a status line: the negation contains the assertion"
description: "NOT ALL GREEN contains ALL GREEN. Wait on a transient state disappearing, never on a terminal state appearing, and match the line rather than the receipt."
tool: Bash
match: ~(until|while) |grep -q
mode: remind
---

**A substring match cannot see the word in front of it.** Good status
output prints the negated form (`NOT ALL GREEN`, `not configured`, `no
findings`, `could not`), so a positive-signal grep is satisfied by the
exact sentence saying it should keep waiting.

Measured (#1066, #1072): this loop returned in seconds with 12 checks
still pending, and the next step in the plan was a merge.

    until ./supertool 'gh-pr:N:status' | grep -qE "ALL GREEN"; do sleep 45; done

`gh-pr:N:status` prints `checks: 18 total: 6 passed, 0 failed, 12
pending ⚠ NOT ALL GREEN`.

Three rules, in order of how much they buy:

- **Wait on a transient state disappearing, not a terminal state
  appearing.** Absence has no antonym to collide with:

      until ! ./supertool 'gh-pr:N:status' | grep -q "pending"; do sleep 45; done

- **Match the line, not the receipt.** A whole-receipt alternation on
  `completed|success|failure|cancelled` fires on `Status: in progress --
  14 total: 5 passed, 1 failed, 8 pending`, because `passed` and `failed`
  are in that line. Anchor on `^Status:` (#1180).
- **Where a positive match is unavoidable, read the field, not the
  phrase.** A count is unambiguous; a phrase is not.

The same defect in GitHub's own parser rather than a shell:
`pr-body-closing-keywords.md` -- writing "does not close #N" closes #N.
