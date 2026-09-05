---
title: "The selection scripts: hand the manager dispatchable groups, not inputs to join"
description: "select_issues.py composes the four reads so a session never joins them by hand. Group by declared-file overlap -- topic is the intent, overlap is the only mechanism a script has. Every input owes a third state."
match: (^|/)scripts/(select_issues|dispatch_rank|lane_setup|issue_claim|preflight_check)\.py$
---

**What this family is for.** Do everything a script can do toward *which issues should a developer be
given*, so the manager is left with judgement and delegation rather than arithmetic. The unit handed
back is the **group** -- one dispatchable lane -- not a list the caller still has to join.

**Three issues per group is the target, and it is a target rather than a quota.** One issue per
lane is the under-filled state, so a selection that returns singletons has not finished its job.
But the bound is declared-file overlap, never the count: a group is padded to three only from
issues that genuinely land inside the same files, and a group of two or one is correct when
nothing else overlaps. Report **why** a group is short -- no overlapping candidate, or a capped
board read -- rather than returning a short group silently, which reads identically to a lane
nobody could fill.

**`select_issues.py` composes, never reimplements.** `dispatch_rank.order/rank` for the order,
`preflight_check.search` for staleness, `lane_setup.resolve_lane/lane_overlap` for collision,
`issue_claim.check` for who holds it. Add a caller, never a second copy of one of those answers.
It makes exactly one `gh` call, on survivors only; the board itself is handed in as data, so a probe
never depends on credentials.

**Group by declared-file overlap. Topic is the intent, overlap is the mechanism (#1068).** A script
cannot read topic -- #267 settled that an issue's files are not derivable from its body, and that
stays settled. What makes a group safe to hand one developer is that its members touch the same
declared files, which is also what keeps two lanes from fighting over the tree. When topic and
overlap diverge, overlap wins and the manager may overrule; never the reverse, and never invent
`lane_patterns` or a `preflight_pattern` for an issue that carried none. An issue declaring no files
is returned **ungrouped**, not guessed into a group -- and is never collision-checked at all, which
is the correct answer rather than a silent `lane-collision: no`.

**Every input owes a third state, and the join is where they get lost.** The module's whole reason
for existing (#970) is that `none-available` must never be reachable through a read that failed:
`could-not-select` names which input went dark. The board has that (`board_read_ok`); as of #1067
three inputs on the collision path do not --

* `held_files` defaults to an empty set, so *could not enumerate the lanes* and *no lanes* are one
  value, and it has no documented producer in the loop's prose at all;
* the `refused`-pattern dark check sits inside `if lane_patterns and held_files:`, so an empty
  inventory skips the guard rather than the comparison;
* a member resolving to `glob-no-match` contributes `files: []` and reads as disjoint --
  `lane_setup._lane_resolved_to_nothing()` exists for exactly this and is never called from here.

When grouping lands, each member's own state has to survive into the group rather than being
flattened: a capped board read makes the whole grouping `could-not-tell`, because members may exist
outside the population anything ever saw.
