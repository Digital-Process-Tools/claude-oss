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
  `vocabulary/00-manual/jit-rules-and-subagents.md`, **by #939 in commit `77b0da6`, before this
  pass ran**. The fragment was the working note for a rule that already existed. Note this pass
  also *modifies* that same file, for a different fragment entirely
  (`905.jit-probe-payload-form`, counted under the six merges) — the two are unrelated, and an
  audit of this diff read the `+12` there as 939's promotion happening here, which would make the
  bucket counts sum to 31 rather than 30. They sum to 30: six fragments feed the four promoted
  rules, six are merged, eighteen are declined.
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

## 2026-09-08 — 50 fragments, 11 promoted into 7 new rules, 10 merged, 22 filed, 7 declined

The four buckets sum to 50: eleven fragments feed the seven new rules below, ten are merged into
six existing ones, twenty-two are declined **as rules** and filed as defect reports instead, and
seven are declined outright with the reason.

Seven new rules: `tools/00-manual/waiting-on-a-status-line.md`,
`tools/00-manual/pr-body-closing-keywords.md`, `tools/00-manual/a-watcher-is-a-checker.md`,
`tools/00-manual/a-write-outside-supertool-meets-no-validator.md`,
`paths/00-manual/subprocess-decodes-with-the-locale.md`,
`vocabulary/00-manual/measuring-ci-cost.md`,
`vocabulary/00-manual/worktree-writes-land-where-cwd-says.md`.

Six merges, into `tools/00-manual/ci-evidence-is-about-one-commit.md` (four fragments on polling CI
truthfully), `paths/00-manual/filesystem-probe-states.md`, `paths/00-manual/loop-prose-parity.md`,
`paths/00-manual/config-value-validation.md`, `paths/00-manual/test-fixture-pitfalls.md` and
`vocabulary/00-manual/jit-rules-and-subagents.md`.

Twenty-two fragments were declined as rules **because they are defect reports**, and were filed
instead: #1324 (`1266.full-matrix-never-actually-dispatched`), #1325 (six fragments on the
`gh_which` "one place" claim and the two vendored copies nothing compares), #1326 (three guards that
cannot fail), #1327 (five third states that never reach the reader), #1328 (a spawned agent's own
definition vintage), #1329 (two guards whose declared scope is narrower than their reach), #1330
(`tree_snapshot compare` flagging its own artifact), plus a comment on #1310 carrying the three
`doctor_check_lane_other_label.py` findings into the lane that will touch that file, and a comment
on #1318 for the test-isolation fragment.

**Declined, with the reason.**

- `1069.supertool-read-op-served-stale-content` — one observation, explicitly unconfirmed, on one
  path, with the fragment itself unable to distinguish a supertool cache bug from a one-off. The
  transferable half ("cross-check the one file a diagnosis hinges on") is already the habit that
  found it. If it recurs with a second instance, it becomes a supertool issue, not a rule here.
- `1075.payload-rule-fires-too-late` — a correct observation about rule *placement*: a `PreToolUse`
  rule matched on `~gh-issue-create` is read at composition time only by accident, because the
  natural order is to write the body first. Both proposed shapes are upstream changes (match the
  draft write instead, or make `gh-issue-create` accept a markdown file). Nothing to write here.
  Superseded in part by `1146`'s merge above, which states the general limit of `mode: remind`.
- `1079.gh-jq-join-of-empty-array-can-vanish-under-strip` — the specific hazard (a trailing empty
  data row eaten by `_run`'s `.strip()`) was removed by #1226's move to `tojson`, which cannot print
  an empty line. The general form is a special case of `filesystem-probe-states.md`'s existing rule
  about collapsing two states into one.
- `1228.site3-race-recurred-on-release-commit-dd2353e` — a recurrence of a closed issue, which is
  tracker work rather than a rule. The mechanism behind it is now in `filesystem-probe-states.md`
  via `1293`'s merge above.
- `1291.supertool-paste-backslash-heuristic-full-resend` — the refusal was a correct catch; the
  request is that it point at the offending line rather than the whole field. Upstream, in supertool.
- `1295.changelog-fragment-overstates-watcher-and-is-stale` — both overclaims already folded into
  `CHANGELOG.md` at v0.28.0 and v0.29.0 (lines 48 and 144). Released history is not edited here. The
  substantive half of the second one is #1324; the first is a wording debt on a shipped entry.
- `1299.patch-tag-must-bump-version-sites-too` — `commands/release.md`'s own procedure already
  produces a release commit before the tag moves, and v0.29.1 followed it correctly. The exposure is
  time pressure on a fix-forward, not missing knowledge, and a rule cannot fire on haste.

## 2026-09-09 — 27 fragments, 3 promoted into 1 new rule, 4 merged, 19 filed, 1 declined

The four buckets sum to 27: three fragments feed the one new rule below, four are merged into three
existing ones, nineteen are declined **as rules** and filed as defect reports instead (eight
issues, #1343-#1350), and one is declined outright with the reason.

One new rule: `vocabulary/00-manual/self-hosted-plugin-resolution.md` — this repo IS the plugin, so
the checkout is the authority and `${CLAUDE_PLUGIN_ROOT}` may be several releases behind it.
Assembled from `1127.plugin-install-cache-severely-behind-checkout`,
`1324.report-schema-skew-pinned-plugin-cache` and `1334.gate3-checklist-vintage-behind-tree-being-gated`,
which are three readings of one fact: a stale pinned copy makes a script regress silently, a
validator answer `UNVALIDATABLE` about a valid payload, and a release gate audit prose older than
the tree it gates.

Four merges: `paths/00-manual/trap-fragments.md` (`1338.home-path-in-fragments-three-times` — never
paste an absolute machine path into a fragment; the guard fired three times in one morning and each
one reddened the default branch), `paths/00-manual/rules-layer-symlinks.md`
(`1331.rebuild-tsv-writes-a-column-oss-rules-does-not`, plus a widened `match:` so the rule also
fires on a jit-context index file rather than only on `scripts/oss_rules.py`),
`vocabulary/00-manual/worktree-writes-land-where-cwd-says.md` (`1307.cwd-reset-lands-write-in-main-clone`
— a retry right after a refusal is a new call and needs its own `cd`; third instance of #1155's
shape), and `tools/00-manual/a-write-outside-supertool-meets-no-validator.md`
(`1333.raw-python-write-in-lane-setup` — a multi-anchor mutation is the second pull toward a
throwaway patch script, and loses the same validators).

Nineteen fragments were declined as rules **because they are defect reports**, and were filed
instead as eight issues:

| issue | fragments | subject |
| --- | --- | --- |
| #1343 | 5 | `bin/oss-workspace`'s channel-arming block, including an unbound `channel_ready` that kills the launcher outright |
| #1344 | 2 | two rounds of the same unvalidated-env-var short circuit in `doctor_check_mcp_channel_registration.py` |
| #1345 | 3 | `doctor_check_statusline_unknowns.py` — the `repo`-missing collapse, and the uncovered `dr?` field |
| #1346 | 2 | two rounds of `--mark-stale`'s silent no-op and the `--root` IndexError |
| #1347 | 4 | four guards that cannot report what they could not look at |
| #1348 | 1 | CLAUDE.md's ownership table missing `trap.d/`, with no test comparing it to `scaffold.OWNED` |
| #1349 | 1 | a task-notification read as a handback, which ran two sub-managers over one board for an hour |
| #1350 | 1 | nothing can tell a lane branch held by a live scheduler from one abandoned by a dead session |

**Declined, with the reason.**

- `0.requivo-session-lookup-is-cwd-scoped` — `requivo session list` resolves `.requivo/sessions`
  under the current working directory, so a `cd` to the path a handoff named hid the session that
  was actually wanted and produced a confident "it does not exist". Real, and it cost a correction
  — but it is one incident about a tool outside this repository, and the transferable half ("a tool
  that resolves relative to cwd answers about somewhere else without saying so") is already
  `vocabulary/00-manual/worktree-writes-land-where-cwd-says.md`'s subject. Nothing here would fire
  usefully on any match this repo has. Note the fragment also broke the naming convention: there was
  no issue being worked on, so it was filed as `0.<slug>.md`.
