# Declined traps

`/oss:curate` reads `trap.d/` and gives every fragment exactly one outcome: promote, merge,
decline, or defer (#1425) -- a fragment the pass genuinely cannot decide is left in `trap.d/`,
named and reasoned in the pass's own pull request, rather than forced into one of the other three.
This file is the record of the declines, so the next lane to hit the same thing finds a decision
rather than an absence and does not refile it. The rule builder skips this file by name.

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

## 2026-09-11 — 36 fragments, 3 promoted, 5 merged, 28 declined

**Promoted.** `tools/00-manual/refused-bash-call-is-all-or-nothing.md` (from
`1345.tmp-toml-collision-blocked-heredoc`), `paths/00-manual/frontmatter-key-spelling-is-
unverifiable-from-source.md` (from `1391.skill-frontmatter-underscore-vs-hyphen`),
`paths/00-manual/doctor-check-module-scope-import.md` (from
`1350.doctor-check-circular-import-systemic`).

**Merged.** `tools/00-manual/waiting-on-a-status-line.md` gained the GitHub-status-enumeration,
invert-the-keyword and pipe-cannot-carry-three-states material (from
`1369.status-enumeration-missed-pending`); `tools/00-manual/supertool-payload-forms.md` gained the
doubled-backslash-lands-as-valid-Python bullet (from
`1343.literal-backslashes-writes-doubled-escape-not-caught-by-py-syntax` and
`1389.toml-literal-string-no-escapes`, the same root cause found twice); `tools/01-oss/merge-gate.md`
gained the `mergeable`-is-stale-against-a-moved-base bullet (from
`1403.github-mergeable-is-computed-against-a-stale-base`, edited via `scripts/oss_rules.py`'s
`TOOLS_MERGE_GATE` per the rules-layer-symlinks rule, not the generated `.md` directly); and
`paths/00-manual/loop-prose-parity.md` gained the fifth Bash-granted-agent-file guard bullet (from
`1414.new-agent-file-needs-the-delegated-test-run-bucket`).

**Existing rule corrected, not promoted.** `paths/00-manual/launcher-prompt-selection.md` described
a three-way `/oss:setup`/`/oss:doctor`/`/oss:tick` launcher decision that `bin/oss-workspace` no
longer makes at all (#1392/#1404 moved it into `/oss:run`) -- rewritten to state what the launcher
actually still does. The underlying fragments (`1389.stale-launcher-docs-from-1404`,
`1392.env-relays-now-consumerless`) are declined below with issue numbers, since the residual work
(doc sweep, an open design decision on the four env relays) is not itself a rule.

**Already actioned or already stated elsewhere; the fragment is a record, not a new rule.**

- `1405.run-md-stale-shape` -- checked live: `commands/run.md` already documents the `ranked`/
  `candidates[0]` shape correctly (confirmed by grep, no stale `could-not-decide` prose remains).
- `1405.record-skip-uncalled-anywhere` -- checked live: `commands/run.md` now calls
  `next_action.py --record-skip` for a deliberate deviation from `candidates[0]`. Already wired.
- `1350.self-hosting-plugin-cache-schema-skew` -- the transferable half ("this repo IS the plugin,
  the checkout outranks `${CLAUDE_PLUGIN_ROOT}`") is already
  `vocabulary/00-manual/self-hosted-plugin-resolution.md`'s whole subject, already carrying three
  independently-measured instances. This is a fourth, from the same tick as one of the three
  already in that file. Nothing here would add content.

**One incident, a real defect, not a rule -- filed as an issue instead.**

- `1339.round2-doctor-check-statusline-remedy-unescaped-quoting`,
  `1339.round2-statusline-scaffold-oss-literal-duplicated-unguarded` -- filed as #1426.
- `1346.plugin-update-root-last-token-indexerror` -- filed as #1429.
- `1347.lane-coupling-import-loop-oserror-silently-swallowed` -- filed as #1427.
- `1350.doctor-inprocess-preexisting-failure-plugin-source-match` -- filed as #1428.
- `1354.checklist-skew-version-scrape-ambiguous-provenance`,
  `1354.report-schema-minlength-message-uses-unstripped-length`,
  `1354.tree-snapshot-artifact-regex-matches-any-depth`,
  `1354.workspace-plural-test-lacks-returncode-positive-control` -- filed as #1430.
- `1361.doctor-next-step-ignores-its-own-remedies` -- filed as #1441.
- `1378.cohort-citation-test-green-because-subject-absent` -- filed as #1442.
- `1389.stale-remedy-strings-picker-demotion` -- filed as #1431.
- `1389.stale-launcher-docs-from-1404` -- filed as #1439 (the docs/ half; the jit-rule half was
  corrected directly, above).
- `1392.env-relays-now-consumerless` -- filed as #1432 (the open thread-through-vs-delete design
  decision; the jit rule describing the launcher's current behaviour was corrected directly, above).
- `1405.inbound-no-repeat-suppression`, `1405.inbound-triage-not-actually-reused` -- filed as #1433.
- `1414.record-skip-cli-double-config-load` -- filed as #1434.
- `1418.root-vs-repo-flag-spelling-across-scripts` -- filed as #1435.
- `1419.gh-error-text-not-backslashreplace-safe`, `1419.inbound-phase-file-stale-gap-claim`,
  `1419.triage-recorded-flag-cannot-run-as-written`, `1419.triage-trigger-ignores-oss-local-json` --
  filed as #1436.
- `1421.channel-suppresses-warn-on-other-sessions-cached-reading`,
  `1421.record-skip-cli-untrapped-statererror` -- filed as #1437.
- `583.tick-md-over-command-budget` -- filed as #1438.

30 fragment files map onto these 28 declines (`1339`, `1354`, `1405`, `1419` and `1421` each cluster
two or four fragments into one bullet or one issue); together with the 3 promoted and 5 merged
fragments (`1414` counted once, under merged) this accounts for all 36.

## 2026-09-12 — 17 fragments, 1 promoted, 6 merged, 10 declined

**Promoted.** `tools/00-manual/gh-rate-limit-reset-and-pollers.md` (from
`1421.watcher-rate-limit-is-not-the-sessions-token`): read `rate_limit` against its own `reset`
timestamp before concluding anything about credentials, count pollers per channel before blaming
one, and a 403 "rate limit exceeded for user ID" beside a full `core` bucket is the secondary
limit, which `rate_limit` does not track.

**Merged.** `vocabulary/00-manual/self-hosted-plugin-resolution.md` gained two more instances of
its own subject -- a `scaffold.py --apply` write, not just a read, regressed two tracked files when
run from the pinned root (`1417.stale-plugin-copy-regressed-jit-rules`), and
`cohort_citation_order.py` without `--claude-md` reads the pinned root's `CLAUDE.md` by default
(`1459.cohort-citation-order-default-reads-the-plugin-copy`); `vocabulary/00-manual/worktree-writes
-land-where-cwd-says.md` gained a fourth instance, ten consecutive `edit`/`paste` calls landing in
the main clone before a routine `git status --short` caught it
(`1440.cwd-resets-between-supertool-edit-calls`); `vocabulary/00-manual/jit-rules-and-subagents.md`
gained the developer-lane-has-no-`SendMessage` clarification -- not a failure, the resume still
works from the manager side (`1436.developer-lane-has-no-sendmessage`). Two fragments
(`1459.gate3r1-merge-gate-contradicts-merge-phase`, `1459.gate3r1-merge-gate-hardcodes-main`)
were not merged as new bullets but used to correct the existing `TOOLS_MERGE_GATE` rule
(`scripts/oss_rules.py`, regenerated into `tools/01-oss/merge-gate.md`) directly: its own
pre-merge `git fetch && git merge origin/main` instruction contradicted `skills/manager/phases/
merge.md`'s #1085 policy (green-and-mergeable means merge, no pre-merge rebase, the squash's push
run is the backstop) and hardcoded `main` rather than the repo's own default branch -- one fix
closes both findings, since removing the offending instruction removes the hardcoding with it.

**Already actioned or already stated elsewhere; the fragment is a record, not a new rule.**

- `1390.dr-marker-cannot-tell-ours-from-not-ours` -- `vocabulary/00-manual/doctor-warning-
  lifecycle.md` already names this exact incident (four WARNs, none the loop's or a maintainer's
  to clear, pinning the statusline's `dr` marker) as the reason a WAIT-shaped third state exists
  beside WARN/FAIL. Nothing here would add content.
- `1438.raw-python-write-to-report-json` -- `tools/00-manual/a-write-outside-supertool-meets-no-
  validator.md` already covers exactly this shape (a raw `python3 -c` JSON round-trip skipping
  every supertool write validator), and the fragment names that file itself. A fourth confirming
  instance with no new failure mode is not worth the growth.

**One incident, a real defect or open design question, not a rule -- filed as an issue instead.**

- `1399.oss-config-repo-re-and-cohort-freeze-slug-guard` -- filed as #1475.
- `1405.next-action-reads-checkout-branch-not-default-branch` -- filed as #1476.
- `1425.setup-still-carries-interactive-stops-under-oss-run` -- filed as #1477.
- `1436.triage-step-does-not-record-its-own-sweep` -- filed as #1478.
- `1455.doctor-verdict-count-flakes-run-to-run` -- filed as #1479.
- `1459.gate3r1-pr-green-unresolved-runs-jobless`,
  `1459.gate3r1-tree-snapshot-windows-case-compare` -- filed as #1480.
- `1459.gate3r2-identity-check-collapses-could-not-tell` -- filed as #1481.

17 fragment files map onto these entries (`1459` contributes six -- two merged as a single rule
fix, one merged into `self-hosted-plugin-resolution.md`, and three bundled or filed singly as
issues); together with the 1 promoted and 6 merged fragments this accounts for all 17.

## 2026-09-14 -- 31 fragments, 7 promoted, 14 merged, 9 declined and filed, 1 deferred

**Promoted.** `paths/00-manual/counter-scripts-silent-gaps.md` (from
`1499.agent-cost-unreadable-transcript-dropped-silently`,
`1499.loop-cost-report-drops-unparseable-timestamp-silently`,
`1499.lane-setup-brief-schema-recon-check-no-word-boundary`,
`1508.doctor-event-filter-reports-one-poller-as-all`,
`1429.arg-value-last-token-indistinguishable-from-absent`,
`1433.next-action-inbound-suppression-count-only-signature` -- six independent instances of
one shape, a scripts/*.py counter or check dropping or misreporting an input silently);
`vocabulary/00-manual/could-not-tell-shallow-clone.md` (from
`1493.shared-clone-went-shallow-mid-run`).

**Merged.** `paths/00-manual/launcher-prompt-selection.md` corrected (`1474.jit-rule-restates-
removed-env-relays` -- three of the four env relays it described are gone entirely, not merely
dead plumbing pending a decision); `tools/00-manual/refused-bash-call-is-all-or-nothing.md`
gained a third instance (`1466.scratchpad-overwritten-mid-lane` -- the session scratchpad itself
is not immune to a concurrent lane's write); `paths/00-manual/test-fixture-pitfalls.md` gained
an `XDG_CACHE_HOME` bullet folding three incidents into one lesson
(`1428.stray-real-cache-pollution-broader-than-one-test`,
`1499.test-leaks-statusline-cache-into-real-home`,
`1508.quiet-main-leaks-real-channel-health-cache`); `tools/00-manual/ci-evidence-is-about-one-
commit.md` gained three bullets (`1458.pr-green-status-condition-narrower-than-docstring-
claims`, `1458.pr-green-supersede-keyed-on-name-not-workflow`,
`1499.gh-branch-codeql-job-list-empty-on-first-read`); `tools/00-manual/sub-manager-hand-polls-
ci.md` gained two bullets (`1499.pr-green-repo-flag-not-honoured`,
`1349.overnight-quota-2B-cache-read-context-growth` -- a much larger measurement of the same
subject plus a duplicate-sub-manager finding); `paths/00-manual/doctor-check-contract.md` gained
three concrete WAIT-arm instances of its own test 1 (`1448.doctor-could-not-check-demoted-to-
wait`, `1448.doctor-verdict-line-does-not-count-wait`, `1474.doctor-mcp-channel-wait-sentinel-
dead`); `vocabulary/00-manual/self-hosted-plugin-resolution.md` gained a fourth instance
(`1460.report-schema-cache-vs-branch-skew`). Three fragments carried a per-machine absolute
path in violation of the naming convention (`1460`, `1493`, `1499.pr-green-repo-flag-not-
honoured`); each was redacted to a placeholder in the promoted/merged text before the source
fragment was deleted, never copied verbatim.

**One incident, a real defect or open design question, not a rule -- filed as an issue
instead.**

- `1378.session-open-cost-unmemoised-liveness` -- filed as #1516.
- `1426.refresh-command-escape-incomplete-for-backslash-adjacent-quotes` -- filed as #1517.
- `1457.auto-mode-classifier-outage-stalls-lane` -- filed as #1518 (does not fit any jit
  trigger: it needs to be read before a rate-limit refusal happens, not matched by a file, tool
  or keyword after the fact).
- `1462.scaffold-template-shas-unwatched-by-dependabot` -- filed as #1519.
- `1469.pretooluse-agent-hook-field-confirmed` -- filed as #1520 (a research note toward a
  future feature, not a recurring trap).
- `1475.doctor-stale-comment-repo-problem`, `1475.oss-config-repo-re-still-accepts-dot-
  segments` -- filed together as #1521 (one root file, two related findings).
- `1476.curate-count-reads-stale-origin-default-branch` -- filed as #1522.
- `1474.wait-text-claims-launcher-is-only-arming-route` -- a 31st fragment that appeared mid-
  pass (a concurrent tick's own finding, on the same WAIT arm as `1474.doctor-mcp-channel-wait-
  sentinel-dead` above) -- filed as #1523.

**Deferred.** `1476.record-skip-dispatch-target` -- the fragment itself names three unresolved
design shapes for `record_skip`'s `dispatch` gap and asks `/oss:curate` to weigh them; none is
this pass's call to make alone. Left in `trap.d/`, unchanged.

31 fragment files (30 present at pass start, plus one written mid-pass by a concurrent tick) map
onto 7 promoted, 14 merged, 8 issues covering 9 fragments, and 1 deferred.

## 2026-09-15 -- 33 fragments, 9 promoted, 9 merged, 22 filed or commented, 6 declined outright, 1 deferred

**Promoted.** `tools/00-manual/exit-sensitive-pipe-to-head-tail.md` (from
`1532.rebase-continue-piped-to-head-dropped-a-commit`,
`1530.background-bash-reports-exit-0-for-an-argparse-refusal` -- a rebase and a background wait,
same SIGPIPE/last-command-exit-code mechanism); `tools/00-manual/git-stash-unstages-git-rm-
deletions.md` (from `1532.git-stash-unstages-git-rm-deletions`); `paths/00-manual/curate-pass-git-
add-before-delete.md` (from `1425.curate-deletes-untracked-fragments-unrecoverably` -- applied to
this pass's own execution as well as promoted, since it named this exact pass's own hazard).

**Merged.** `tools/00-manual/waiting-on-a-status-line.md` gained the `gh-branch` Verdict-line
`failed`-substring bullet (from `1530.gh-branch-verdict-says-nothing-has-failed`); `paths/00-
manual/test-fixture-pitfalls.md` gained three bullets -- monkeypatching a re-exported name
(`1535.monkeypatching-a-re-exported-name-patches-nothing`), deriving a caller sweep rather than
hand-picking one (`1532.deleting-a-surface-needs-a-derived-caller-sweep`), and synthetic fixture
paths (`1528.new-test-file-trips-repo-wide-lane-coupling-guard-untargeted`); `paths/00-manual/
filesystem-probe-states.md` gained the falsy-vs-`is None` three-states fold bullet (from
`1528.overlap-info-collapsed-checked-clean-into-never-checked`).

**Filed as issues.** #1549 (`1190.scheduler-blocks-on-ci-with-no-reselect-procedure`), #1550
(`1275.triage-report-parts-2-to-5-have-no-persistence-path`), #1551
(`1414.triage-sub-step-names-its-spawn-in-prose-only` +
`1469.phase-files-register-as-spawnable-agents`, filed together since the second is a sharper
instance of the first's class), #1552 (`1467.curate-pr-has-no-closing-reference-by-construction`,
also applied directly to this pass's own PR via `no_close = true`), #1553
(`1476.record-skip-dispatch-target`, deferred once already on 2026-09-14 -- a second deferral would
only delay the same open decision), #1554 (`1492.release-ci-wait-same-fixed-cadence-gap` +
`1546.pr-green-backoff-capped-by-timeout`, the same rate-limit-backoff gap on both of the loop's
CI-wait scripts), #1555 (`1528.dispatch-md-lane-collision-prose-now-stale` +
`1546.pick-the-work-stale-after-the-registry-retirement` +
`1546.lane-coupling-check-cannot-answer-any-more`, all stale prose or a stale check left behind by
#1530's registry retirement), #1556 (`491.claude-md-is-the-largest-unbudgeted-file`).

**Commented on the existing umbrella issue rather than filed separately**, since each is additional
material toward a checklist item #1499 already tracks: a comment on #1499 folding in
`1499.channel-excludes-the-one-event-the-poll-waits-for` (toward item 5, the event blacklist),
`1499.recon-report-is-paid-twice-and-the-second-copy-sits-in-the-sub-manager` and
`695.give-the-selection-scripts-to-the-lane-and-price-the-conflict` (both toward item 3, splitting
sub-manager cost).

**Declined outright, with the reason.**

- `1499.a-capped-read-is-not-a-whole-file` -- the recovered text is already in `CLAUDE.md`'s token
  economy section verbatim (it was a stray write to the main worktree, reverted, and the content
  landed through the normal channel instead).
- `1499.coordination-layer-costs-ten-times-the-lanes` -- its own measured table is already quoted
  verbatim in `CLAUDE.md`'s token economy section.
- `1499.developer-lane-context-breakdown-measured` -- a measurement; its actionable halves (capped-
  read paging, `cwd:PATH` for out-of-worktree reads) are already stated in `CLAUDE.md`.
- `1499.loop-cost-report-rerun-since-0.34.0-cycle` -- a re-run's own numbers, explicitly self-
  described as settling no enforcement decision and establishing no trend from one window.
- `1546.cost-line-folds-duplicate-to-absent` -- a deliberate trade-off already argued in the code's
  own module docstring (`scripts/tick_handback.py`), not an oversight; nothing here would add
  content.
- `695.sub-manager-context-accounting-measured` -- a measurement whose "levers" section is already
  covered by existing rules (never re-read a brief just written, read phase files with explicit
  ranges) and by the recon/give-the-selection-scripts material folded into the #1499 comment above.

**One fragment resolved by cross-reference rather than by its own content.**

- `1530.lane-patterns-still-feeds-overlap-info-after-1528` -- its own premise (a warning about what
  #1530's deletion step would break if it landed as scoped) is now historical: #1530 has since
  merged, and the resulting state is what `1546.lane-coupling-check-cannot-answer-any-more`
  describes and #1555 above files.

**Deferred.** `1544.tree-snapshot-vanished-inside-worktree` -- root cause explicitly unconfirmed by
its own text (three candidate causes named, none checked), too thin to tell a rule from a one-off
incident. Left in `trap.d/`, unchanged.

33 fragment files map onto 9 promoted, 9 merged, 7 issues covering 12 fragments, 3 fragments folded
into one comment on #1499, 6 declined outright, 1 resolved by cross-reference, and 1 deferred.

## 2026-09-15 — 24 fragments, 5 promoted into 3 new rules, 15 merged, 3 declined, 1 deferred

The four buckets sum to 24: five fragments feed the three new rules below, fifteen are merged into
six existing ones, three are declined outright with the reason, and one is left in `trap.d/`,
unchanged, already recorded as deferred under 2026-09-14 above.

Three new rules: `tools/00-manual/git-commit-no-paths-refusal.md` (from
`1467.git-commit-refuses-no-paths-despite-listing-them`), `paths/00-manual/claude-md-budget-guard-
derivation.md` (from `1544.claude-md-ceiling-history-names-a-number-never-on-disk` and
`1544.claude-md-own-baseline-not-in-guard-derivation`), and `paths/00-manual/sub-manager-spawn-
guard-fail-open-gaps.md` (from `1571.sub-manager-spawn-guard-import-outside-try` and
`1571.sub-manager-spawn-guard-role-marker-is-repo-global-not-caller-scoped`). All three proved a
must-fire and a must-not-fire payload against `pre-path-hook.sh` before being written into the
index.

Six merges: `paths/00-manual/counter-scripts-silent-gaps.md` (four fragments --
`1571.doctor-action-pins-drops-unresolved-when-drift-present`,
`1519.outbound-draft-pending-count-renders-unparseable-names-as-zero`,
`1519.outbound-naming-convention-forked-and-the-two-copies-already-disagree`,
`1571.ratelimit-backoff-constants-duplicated-with-no-cross-check` -- all four are the same class
this file already names, an absence or a missing cross-check dropped silently),
`paths/00-manual/loop-prose-parity.md` (four fragments on prose that drifted from what its own
file now does -- `1544.tick-dispatch-why-section-now-overstates-what-stays-unsplit`,
`1544.tick-review-procedure-never-names-what-to-do-on-could-not-read`,
`1573.merge-phase-gh-api-call-wraps-across-a-line-inside-its-own-backticks`,
`1567.respawned-for-cost-docstrings-still-say-three-dispatch-states`),
`paths/00-manual/test-fixture-pitfalls.md` (three fragments, all a positive control that never
runs the real helper it claims to be a control for --
`1544.absence-check-plus-synthetic-control-cannot-tell-checked-clean-from-nothing-to-check`,
`1571.merge-gate-guard-only-pins-substring-presence-not-op-validity`,
`1573.tick-merge-guard-positive-control-is-tautological`),
`paths/00-manual/config-value-validation.md` (`1571.outbound-route-threshold-key-validates-but-
nothing-reads-it`), `tools/00-manual/stacked-pr-cleanup-recovery.md`
(`1544.tick-merge-documents-cleanup-without-the-stacked-pr-hazard` -- the tool itself already
guards the hazard the fragment asked whether to restate in prose; the merge instead adds the one
genuinely new fact, that a refused cleanup is not a failed merge), and
`vocabulary/00-manual/worktree-writes-land-where-cwd-says.md` (two fragments, both a missing
`cwd:`/`cd` prefix landing a call in the wrong tree -- `1467.cwd-prefix-shape-costs-two-failed-
reads`, `1573.supertool-edit-with-no-cd-or-cwd-prefix-lands-in-the-wrong-tree`).

**Declined, with the reason.**

- `1520.spawn-guard-docstring-cites-wrong-field-count` and
  `1571.spawn-guard-docstring-claims-three-fields-harness-sends-five` -- the same underlying
  docstring bug (`sub_manager_spawn_guard.py`'s own comment says three `AgentInput` fields; the
  harness sends five), found independently by two different audit rounds. A wrong field count in
  a docstring is a one-line fact to correct directly, not a generalisable rule a future agent
  needs reminding of near this file -- the two live gaps that file actually has a rule for now
  (`sub-manager-spawn-guard-fail-open-gaps.md`, promoted above) are the ones worth carrying
  forward.
- `1573.tick-merge-classifier-composition-mismatches-scalar-vs-dict` -- a real but narrow bug
  (`agents/tick-merge.md`'s documented `gh api --jq .author_association` call composes a bare
  scalar into a helper that wants a dict), already fail-closed (the documented gate routes any
  classifier failure to `could-not-merge`, so nothing merges on an unread gate) and loud rather
  than silent when it fires. A one-off composition mismatch in one documented call, not a pattern
  this repo has hit more than once.
