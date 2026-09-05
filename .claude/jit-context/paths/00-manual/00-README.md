# Declined traps

`/oss:curate` reads `trap.d/` and gives every fragment exactly one outcome: promote, merge, or
decline. This file is the record of the declines, so the next lane to hit the same thing finds a
decision rather than an absence and does not refile it. The rule builder skips this file by name.

## 2026-09-05 — 30 fragments, 4 promoted, 6 merged, 18 declined

**Already actioned; the fragment is a record of work that shipped.**

- `915.tick-md-unbudgeted-and-read-twice` — `commands/tick.md` now has a budget table
  (`scripts/command_budgets.py`, #940), and the double-read note lives in `commands/tick.md`'s own
  first paragraph. The token measurements are preserved in the fragment's successor issue, not here.
- `915.budget-table-baseline-column-unchecked` — closed by #1014;
  `tests/test_baseline_matches_disk_1014.py` compares every declared baseline against the file's
  actual size. Recurred once (#1029) and was caught by that test, which is the outcome wanted.
- `915.developer-floor-dominates-lane-cost` — acted on by #939, which split `agents/developer.md`
  into a spine plus three phase files (89,714 B to 47,819 B). The per-lane cost measurement itself
  is summarised in CLAUDE.md's own budget section.
- `939.submanager-init-floor-measured` — a measurement of one tick on one model, explicitly
  self-described as needing re-measurement rather than trust. Not a rule.
- `939.submanager-loads-the-spine-before-reading-tick-md` — folded into #1037, which asks the
  larger question the ordering is a symptom of: whether the scheduler should hold `commands/tick.md`
  at all.
- `918.loop-runs-a-release-behind-the-repo-it-manages` — closed by #942: `doctor.py`'s
  `check_plugin_copy` now answers "is the installed copy behind the repository I am standing in",
  and `commands/tick.md` step 1 reads that line.
- `973.submanager-has-no-sendmessage-so-the-documented-resume-path-does-not-exist` — closed by
  #987; sub-managers now hold `SendMessage` and resume lanes per #880 rather than re-dispatching.
- `939.jit-rules-silent-in-subagents-once-the-session-consumed-them` — already promoted, to
  `vocabulary/00-manual/jit-rules-and-subagents.md`. The fragment was the working note.
- `970.select-issues-unwired` — filed as #1036. A wiring defect on the tracker, not a rule.

**One incident, not a rule.**

- `845.worktree-deletion-mechanism-not-found` — an investigation that correctly concluded the
  mechanism is not in this plugin's code. The transferable half ("a *not found here* conclusion
  needs the same grep discipline as a *found it* one") is real but too general to fire usefully on
  any match. `lane_setup.detect_vanished_worktrees` is the durable output.
- `1022.brief-placeholder-not-substituted` — a literal `{{PASTE ...}}` placeholder shipped in three
  briefs because nothing templates an `Agent()` prompt. Caught immediately, exposure limited because
  `agents/developer.md` carries the real content anyway, and the `SendMessage` gap that made it
  unfixable after dispatch is closed (#987).
- `972.the-plugin-root-snapshot-was-gone-and-could-not-read-was-the-only-honest-answer` —
  superseded by `976.check-plugin-root-says-could-not-read-for-two-unrelated-worlds`, which holds
  both instances and is the sharper statement of the same overloaded third state.

**A defect report, which belongs on the tracker rather than in a rule.** Each was filed on
2026-09-05; a rule cannot fix a mechanism that is wrong.

- `915.lane-fill-adjacency-gate-reproduces-one-issue-lanes` — three one-issue lanes dispatched with
  31 issues open, every gate green, because the conflict check was pointed at the running lanes and
  its `no overlap` was written up as `no-adjacent`.
- `918.suggest-companions-reported-false-positives` — `lane_setup.py --suggest-companions` cited the
  same file for every candidate; not independently reproduced, and possibly a contract that
  contradicts #267 rather than a bug.
- `915.no-detector-for-stale-remote-branches` — 57 merged `origin/fix/*` refs accumulated with no
  diagnostic anywhere; a quantity that drifts one way with no reporter.
- `918.the-fix-for-an-audit-finding-is-unreviewed-by-default` — the commit answering an audit is
  never itself a subject, and a second round found two real bugs in one.
- `918.submanager-handback-promised-its-own-resumption` — a sub-manager closed by promising to
  resume itself, which it cannot; recurred one turn after being corrected twice, so the fix is
  structural rather than prose.
- `976.check-plugin-root-says-could-not-read-for-two-unrelated-worlds` — already on the tracker as
  its own issue number.
