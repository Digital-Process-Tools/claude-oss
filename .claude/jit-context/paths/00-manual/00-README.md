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

## 2026-09-16 — 22 fragments, 5 promoted into 5 new rules, 4 merged, 10 declined, 1 deferred

The four buckets sum to 22: seven fragments feed the five new rules below, four are merged into
three existing ones, ten are declined outright with the reason, and one is left in `trap.d/`,
unchanged, named as deferred.

Five new rules: `paths/00-manual/issue-design-question-not-dispatchable.md` (from
`1044.rank-then-hunt-half-is-an-undecided-design-question-not-a-diff`),
`paths/00-manual/run-step-worktree-and-pr-ownership.md` (two fragments --
`1389.run-step-in-the-main-clone-strands-it-on-a-feature-branch` and
`1389.run-step-pull-requests-have-no-owner-in-the-merge-path`),
`paths/00-manual/triage-merged-but-still-open-needs-reopen-check.md` (from
`1550.merged-but-still-open-check-cannot-see-a-deliberate-reopen`),
`paths/00-manual/sub-manager-probe-is-not-maintainer-consent.md` (from
`1551.sub-manager-read-a-status-probe-as-maintainer-consent`), and
`tools/00-manual/supertool-answers-can-diverge-from-ground-truth.md` (two fragments --
`1566.supertool-read-grep-served-stale-cached-content` and
`1576.supertool-validate-op-ignores-markdownlint-config`).

Four merges: `paths/00-manual/counter-scripts-silent-gaps.md` (two fragments --
`1566.release-trigger-stale-head-second-git-call-swallows-failure` and
`1566.stale-head-shape-also-lives-in-release-delta-siblings` -- the same silent-fallthrough class
this file already names, confirmed still live by direct read after the sibling fetch-path fix
shipped), `paths/00-manual/sub-manager-spawn-guard-fail-open-gaps.md`
(`1571.role-marker-is-not-cleared-when-a-sub-manager-finishes` -- a third gap in the same module's
fail-open contract, compounding the marker-scope gap already recorded there), and
`paths/00-manual/claude-md-budget-guard-derivation.md`
(`1583.budget-guards-split-across-two-axes-and-only-one-runs-locally` -- a sharper statement of the
same "which guard actually covers what you touched" problem this file already exists for).

**Declined, with the reason.**

- `1477.setup-md-still-has-a-third-unattended-ask-site` -- a genuine, narrow gap (a fifth unattended
  "ask" site in `commands/run/setup.md`, lines 72-86, out of #1477's own scope), but it is a
  specific line range to fix in code, not a reusable session rule. Worth a maintainer filing it as
  its own issue; not a jit-context rule.
- `1499.spawn-token-defeats-the-tick-cost-measurement` -- a real structural tension (the spawn token
  has to be widely present to authenticate a message and uniquely present to identify a transcript;
  it cannot be both), but the fix is a code/design decision (an agent id or session-scoped handle
  in place of `--match` on the token), not a session behaviour a rule can change. The honest
  `COST: not attempted` the fragment reports is itself the correct behaviour in the meantime.
- `1520.live-fire-spawn-guard-check-is-not-safely-runnable-from-a-developer-lane` -- a one-off
  recommendation (run this specific checklist item by hand, ideally against a disposable scratch
  repository) for a single remaining item on issue #1520, not a pattern that recurs.
- `1577.lane-cost-over-threshold-423554-context` -- the fragment's own text already states
  `handback.md`'s answer: reporting rather than filing, no action required. Recorded here so a
  future pass does not re-derive the same "no action" conclusion from scratch.
- `1577.lane-setup-guard-derivation-misses-shipped-op-spellings` -- a real coverage gap in
  `lane_setup.py`'s `CROSS_CUTTING_GUARDS` table, but the fragment itself says it needs a design
  decision on the routing heuristic, out of scope for the lane that found it. A code fix, not a
  session rule.
- `1578.jit-context-readme-line-394-trips-markdownlint-atx-heading` -- a one-character fix (a
  missing space after a leading `#` in `.claude/jit-context/paths/00-manual/00-README.md`), caused
  by a two-commit composition gap already named in the fragment itself. Narrow enough to fix
  directly; not a rule.
- `1579.claim-lane-guard-scope-misses-two-documented-call-sites` -- `tests/test_dispatch_claim_
  drops_lane_1579.py`'s own file list misses two of five documented `--claim` call shapes. A test
  coverage gap to fix in the test itself, not a rule this index can express (the rule builder skips
  `tests/`, and the finding is about that guard's own scope, not a pattern to watch for elsewhere).
- `1581.claude-md-own-table-row-stale-behind-its-own-budget-dict` -- superseded by this pass's own
  merge above: `1583.budget-guards-split-across-two-axes...` shows `test_claude_md_budget_table_
  709.py` does in fact catch exactly this drift class (it failed in CI on four such rows), so this
  fragment's core claim ("nothing catches this") no longer holds once 709/725 are the guards
  actually run against the edited file.
- `1583.claude-md-layout-lists-deleted-report-phase-file` -- a real, still-live stale line in
  `CLAUDE.md`'s own Layout inventory, but `/oss:curate` has no authority to edit `CLAUDE.md` outside
  its own three narrow exceptions, none of which cover this. Needs a maintainer or a lane whose own
  diff already touches that file for an unrelated, in-scope reason.
- `1583.loop-cost-report-missing-oss-lane-report-row` -- a missing `ATTRIBUTION_MAP` row for the
  `oss:lane-report` spawn #1583 introduced, in `scripts/loop_cost_report.py`. A one-line code fix,
  not a rule.

**Deferred, left in `trap.d/` unchanged.**

- `1544.tree-snapshot-vanished-inside-worktree` -- deferred in the 2026-09-16 pass above; carried
  forward unchanged (no recurrence, no new information) and reconsidered here. Root cause is still
  unconfirmed, but the defensive mitigation the fragment itself names (snapshot immediately before
  spawning, read back at compare time) stands on its own regardless of cause, so this pass promotes
  it to `tools/00-manual/tree-snapshot-compare.md` rather than deferring a third time on the same
  unchanged evidence.

## 2026-09-16 — 16 fragments, 4 fed 3 new rules, 7 merged, 4 declined, 1 deferred

Three new rules from four fragments: `tools/00-manual/tree-snapshot-compare.md`
(`1544.tree-snapshot-vanished-inside-worktree`, promoted -- see the note above), and
`paths/00-manual/tick-handback-curate-parsing.md` (both `1600` fragments together, since read
side by side they are one composition risk between the same two commits rather than two), and
`paths/00-manual/regex-against-stringified-path-assumes-posix-separator.md`
(`1618.worktree-attribution-regex-assumes-forward-slash-separator`).

Seven merges into five existing files: `paths/00-manual/posix-shell-portability.md`
(`1511.pre-existing-non-ascii-glyphs-in-oss-workspace-oss-step-uncoded-for-cp1252` -- a glyph
printed by a shell script can be unencodable on the console it reaches), `paths/00-manual/
filesystem-probe-states.md` (two fragments -- `1584.remind-budgets-check-raises-instead-of-
missing-state` and `383.stat-kind-docstrings-invert-doctor-py-measurement`, both misreadings of
what `Path.exists`/`is_file`/`is_dir` swallow on this repo's own supported interpreters),
`paths/00-manual/sub-manager-spawn-guard-fail-open-gaps.md` (two fragments -- `1585.clear-marker-
root-uses-git-dir-not-common-dir` and `1585.spawn-guard-transcript-path-assumption-not-live-fire-
verified`, both further gaps in the same module's fail-open contract; match widened to include
`scripts/agent_role.py`, where the marker path this pass's finding concerns actually resolves),
`tools/00-manual/sub-manager-hand-polls-ci.md` (`1594.tick-merge-spawn-notified-five-hours-after-
its-merge` -- a spawn that has already gotten its answer another way needs to close its own
backgrounded poll, not leave it resident), and `paths/00-manual/subprocess-decodes-with-the-
locale.md` (`1595.delegation-cost-json-could-not-read-stdout-encoding` -- the same Windows
encoding risk this file already names, running in the write direction: `print()` to stdout, not
only `subprocess` reads).

**Declined, with the reason.**

- `1516.oss-workspace-replay-stub-feeds-mcp-list-text-to-mcp-get-liveness-ask` -- a real,
  well-confirmed correctness bug in one relay stub's argv-blind dispatch, but a single incident
  confined to one call site with a non-trivial fix (real per-argv dispatch or a second relay of an
  already-computed answer) -- a code fix for whoever picks up `bin/oss-workspace`'s census plumbing
  next, not a pattern that recurs elsewhere.
- `1555.lane-coupling-check-vanished-worktrees-precedent-does-not-hold` -- a reasoned answer to one
  issue's own design question (does `doctor_check_lane_coupling.py` share `check_vanished_
  worktrees`'s retirement precedent -- checked directly against `oss_config.py`/`scaffold.py` and
  found it does not, since `labels.lane_patterns` still has a live write path). The answer is
  already recorded in the issue; nothing here is a rule for a future lane to act on.
- `1578.markdownlint-json-missing-from-claude-md-ownership-table` and `1584.claude-md-has-no-
  dedicated-section-for-remind-budgets-py` -- two real completeness gaps in `CLAUDE.md`'s own hand-
  curated tables (a `defaults`-tier file missing from the ownership contracts row; a new budgeted
  script with no dedicated `##` section), each with a concrete code-level fix named in its own
  fragment (a comparison test in `test_claude_md_ownership_table_1348.py`'s own shape; a maintainer
  decision on whether `remind_budgets.py` earns a full section or a folded mention). Neither is
  actionable by a jit-context rule: the loop cannot edit `CLAUDE.md` outside its own three narrow
  exceptions, so a future lane reading a rule here still could not act on it. Same shape as `1583.
  claude-md-layout-lists-deleted-report-phase-file`, declined above for the identical reason.

**Deferred, left in `trap.d/` unchanged.**

- `1584.jit-rules-and-subagents-vocab-stale-after-once-flip` -- issue #1584's own reopening comment
  deliberately deferred this exact rewrite as a separate change with its own argument ("bundling it
  here would mix a mechanical flip with a rewrite"), after `claude-jit-context` 0.10.0 changed
  `once`-mode dedup from per-session to per-reader. Attempting the rewrite inside this pass, without
  independently re-verifying the new semantics against the 45 default-mode files the same comment
  flags as a separate open question, risks landing a second wrong claim into a rule already caught
  getting a harness-payload fact wrong once. Left for the dedicated rewrite the issue asked for.

## 2026-09-17 — 17 fragments, 3 promoted, 3 merged, 10 declined, 1 deferred

**Promoted.**

- `1629.markdownlint-md018-false-trips-on-issue-number-references` -> `paths/00-manual/
  md018-issue-ref-at-line-start.md` -- a real, recurring papercut with no config escape
  (`.markdownlint.json` enables MD018 with no rule-specific exception), narrow enough to state as
  a rule rather than an incident.
- `1629.supertool-head-substring-guard-and-git-diff-branch-form-friction` -> `tools/00-manual/
  supertool-op-discoverability-friction.md` -- two op-shape papercuts (`| head` after a supertool
  call still refused; `git-diff:branch:BASE:full` is the working form, not a bare ref), both
  generalisable and neither already stated.
- `1637.hand-merged-conflict-resolution-is-not-a-real-merge` -> `vocabulary/00-manual/
  hand-merged-conflict-is-not-a-real-merge.md` -- a real mechanism (`git merge-base` is graph-only,
  not content-only), confirmed on PR #1637 with `git log --format=%P` and `git merge-tree`, worth
  knowing before anyone else "resolves" a `CONFLICTING` state by hand.

**Merged.**

- `1584.jit-rules-and-subagents-vocab-stale-after-once-flip` -> `vocabulary/00-manual/
  jit-rules-and-subagents.md`, rewritten in place. This fragment was deferred by the prior curate
  pass (recorded below, 2026-09-05 section is not the one -- see the "Deferred" entry this section
  now supersedes) specifically because the new semantics needed independent re-verification; this
  pass had two further fragments (`1584.jit-once-mode-flip-shipped-with-no-version-floor`,
  `1584.vocab-and-paths-rules-copied-mode-once-into-dimensions-with-no-mode-field`) that already
  re-derived the claim against `claude-jit-context` 0.10.0's own `scripts/common.sh` (confirmed
  directly here too: `jit_agent_key()` is "Used ONLY by pre-tool-hook.sh" -- i.e. only the `tools`
  dimension gets per-reader dedup; `paths`/`vocabulary` still dedup on plain `session_id`
  regardless of any `mode` field), which removed the risk the deferral was protecting against.
- `1628.toml-literal-block-backslash-doubling-costs-several-retries` -> `tools/00-manual/
  supertool-payload-forms.md`, widened `match` to also fire on `paste:@`/`edit:@` (previously
  scoped to `gh-*` ops only) and added the specific reflex this fragment describes (doubling a
  backslash out of Python-string habit, when a TOML literal block does zero escape processing).
- `1629.supertool-cwd-op-not-usable-inside-batch-payload` -> `vocabulary/00-manual/
  worktree-writes-land-where-cwd-says.md`, a new bullet alongside its other `cwd:PATH` op-shape
  papercuts.

**Declined -- code-level defects, not rule content (an observation about one incident, not
something a jit rule fixes by reminding a future reader).** Each names a concrete fix in its own
fragment; none of them is curatable via a `.claude/jit-context/` rule, so none is promoted, merged
or filed from here -- filing is out of this pass's four-outcome scope.

- `1584.jit-once-mode-flip-shipped-with-no-version-floor-on-jit-context-dependency` -- needs a
  `plugin.json` dependency version floor (or a `doctor.py`/`plugin_update.py` check), not a rule.
- `1584.remind-budgets-module-budgets-zero-remind-mode-files-after-once-flip` -- needs
  `scripts/remind_budgets.py`'s own docstring/follow-up sweep restated in terms of `once`, not a
  rule about the module.
- `1584.vocab-and-paths-rules-copied-mode-once-into-dimensions-with-no-mode-field` -- the generator
  bug itself (`scripts/oss_rules.py` writing `mode: once` for `paths`/`vocabulary`, and the three
  `01-oss` vocabulary files carrying it) needs a code fix plus `oss_rules.install()` regeneration,
  which this pass does not do; the one `00-manual` file this pass **can** safely touch
  (`paths/00-manual/regex-against-stringified-path-assumes-posix-separator.md`) had its erroneous
  `mode: once` stripped directly in this same PR as incidental cleanup, since paths carries no
  `mode` column at all.
- `1628.dirt-state-porcelain-scan-cannot-see-gitignored-artifact-allowlist-paths` -- needs
  `scripts/worktree_reap.py`'s `dirt_state` to also read `git status --ignored`; a code fix.
- `1628.doctor-check-worktree-reap-warn-with-no-remedy-when-lsof-absent` -- needs
  `scripts/doctor_check_worktree_reap.py`'s could-not-tell arm changed WARN to NOTICE, matching two
  sibling modules' own precedent; a code fix, not new knowledge to remind anyone of.
- `1628.gitignore-scaffold-template-still-missing-artifact-allowlist-entries` -- needs
  `scripts/scaffold.py`'s `GITIGNORE` template updated, plus a doc note that already-scaffolded
  repos need the addition applied by hand; a code/template fix.
- `1628.raw-heredoc-write-block-applies-outside-the-repo-too` -- the fragment's own author states
  "No rule change suggested here -- the guard did exactly what it says it does," logged only in
  case the same reasonable-sounding exception recurs; nothing to promote.
- `1629.supertool-git-commit-requires-explicit-paths-with-at-payload-message` -- already stated,
  verbatim in substance, by `tools/00-manual/git-commit-no-paths-refusal.md` (from #1467).
- `1637.lsof-nonzero-exit-partial-output-misread-as-unoccupied` -- needs
  `scripts/worktree_reap.py`'s `_lsof_process_cwds` to read `rc` and return `None` on non-zero exit,
  matching the sibling `_gh_json` pattern two functions away; a code fix.
- `1638.cohort-35-freeze-partial-due-to-stale-partial-attempt-residue` -- needs
  `scripts/cohort_freeze_record.py`'s `label_filter` route to exclude non-open issues, or the 17
  stray labels stripped by hand; a code/data fix, explicitly scoped by its own fragment as "not this
  release's own responsibility to fix live."

**Deferred, left in `trap.d/` unchanged.**

- `1632.red-curate-pr-has-no-owner-after-its-spawn-dies` -- the fragment's own text states the
  open question plainly: "What is not established is whether the scheduler should be doing that at
  all, or whether curate's own PR belongs in the next tick's review set." That is an architecture
  decision for `skills/manager/` (does a tick's own review step need to pick up a PR opened by a
  different spawn?), not a call this pass can make alone, and not a jit rule -- a future agent
  cannot fix a missing ownership seam by being reminded of one.
## 2026-09-18 — 20 fragments, 6 promoted, 1 merged, 8 declined, 5 deferred

**Promoted.**

- `1638.curate-pr-grows-budgeted-jit-file-without-updating-remind-budgets` -> `paths/00-manual/
  curate-pr-jit-file-needs-remind-budgets-check.md`, new rule firing on any edit under
  `.claude/jit-context/`: run `remind_budgets.py --check` before committing.
- `1649.releaser-spawn-still-bare-agent-call` -> `paths/00-manual/
  agent-call-needs-run-in-background-pin.md`, new rule firing on `commands/*.md`/`agents/*.md`:
  every `Agent(subagent_type: ...)` call must carry an explicit `run_in_background` token, after
  #1586 and #1649 each fixed one bare instance of the same class piecemeal.
- `1654.checks-failed-event-fires-on-a-cancelled-leg-not-a-failing-one` -> `vocabulary/00-manual/
  checks-failed-can-mean-cancelled.md`, new vocabulary rule: a `checks_failed` channel event can
  mean a cancelled leg, not a real failure -- read `gh-pr:N:status` before acting on the event name.
- `1656.review-return-classifier-flags-fully-stated-findings-with-internal-back-references` ->
  `paths/00-manual/findings-brief-bans-above-and-tallies.md`, new rule firing on the review-brief
  agent files: ban the word above and closing tally lines in a `FINDINGS: <n>` brief, since
  `scripts/review_return.py` cannot tell a fully-restated cross-reference from a genuinely missing one.
- `1664.tick-filed-and-dispatched-a-lane-for-a-defect-the-maintainer-had-already-fixed-on-main` ->
  `paths/00-manual/recheck-red-main-before-file-and-dispatch.md`, new rule firing on the
  dispatch/sub-manager files: re-check a red-main sighting immediately before filing and dispatching
  on it, rather than acting on an already-stale board read.
- `1668.supertool-rename-refusal-exits-zero-so-a-fallback-never-fires` -> `tools/00-manual/
  supertool-rename-exit-zero-on-refusal.md`, new tools rule firing on `rename:` calls: the op can
  refuse and exit 0, so `||`/`&&` cannot be trusted after it -- verify the result directly.

All six proven both directions with `jit-dry-run.sh` (a must-fire payload and a must-stay-silent
payload each), plus a known-good control observed firing alongside each (`supertool-required.md`,
`agent-call-needs-run-in-background-pin.md`, `supertool-answers-can-diverge-from-ground-truth.md`,
`md018-issue-ref-at-line-start.md` and `tree-snapshot-compare.md` each fired correctly in the same
runs, confirming the harness itself was live).

**Merged.**

- `1642.release-auditor-mutation-receipt-filename-is-fixed-not-picked` -> `tools/00-manual/
  tree-snapshot-compare.md`, a new paragraph: name a mutation-receipt snapshot file from a unique
  per-spawn token (issue/PR number or PID), never a fixed template even one that only varies by
  round number -- the same collision the rest of that file already covers, applied to a sibling
  agent's own near-miss.

**Declined -- code-level defects, not rule content (an observation about one incident, not
something a jit rule fixes by reminding a future reader).** Each names a concrete fix in its own
fragment; none of them is curatable via a `.claude/jit-context/` rule, so none is promoted, merged
or filed from here -- filing is out of this pass's four-outcome scope.

- `1499.plugin-identity-detail-recorded-as-literal-unchanged` -- needs `scripts/oss_state.py`'s
  `--plugin-identity` flag to refuse a value that looks like one of the check's own verdict words;
  a code fix.
- `1578.markdownlint-json-missing-from-claude-md-ownership-table` -- needs `.markdownlint.json`
  added to `CLAUDE.md`'s own `defaults` row by hand, plus a comparison test mirroring
  `test_claude_md_ownership_table_1348.py` against `scaffold.TEMPLATES`; a content and test fix,
  and `CLAUDE.md` itself is hand-curated, outside this pass's authority to touch.
- `1625.claude-md-size-threshold-as-float-reads-as-unconfigured` -- needs
  `scripts/doctor_check_claude_md_size.py`'s `valid_threshold` to accept an integral float or
  render a distinct message; a code fix.
- `1636.first-fail-refresh-renders-as-not-asked-not-refresh-failed` -- needs
  `scripts/doctor_check_statusline_unknowns.py`'s two consumers reordered to read the failure
  marker before falling back to "not-asked", mirroring the board field's own correct shape; a code
  fix.
- `1642.tick-review-still-uses-tmp-for-its-mutation-receipt` -- the already-shipped
  `tools/00-manual/tree-snapshot-compare.md` rule already says not to use `/tmp`; this fragment
  names one file (`agents/tick-review.md`) that still does, which a new or merged rule cannot fix --
  it needs the same three-part edit (worktree-local path, `-before-snapshot.json` suffix,
  delete-after-compare) actually applied there.
- `1651.triage-route-threshold-string-value-silently-dead-routes` -- needs
  `scripts/doctor_check_triage_route.py` (and its sibling `doctor_check_trap_queue.py`) validated
  with the same predicate `workspace_routes._valid_threshold` uses, not a bare `is not None`; a
  code fix.
- `1656.superseded-by-pr-tick-review-scope-not-updated-for-foreign-authored-prs` -- needs
  `agents/tick-review.md`'s own scope statement widened for a `superseded_by_pr` pull request that
  predates the loop's handback format or was opened by an external contributor; a prose fix to one
  file, and the auditor that found it could not confirm the case is reachable today.
- `1660.posthang-diagnostic-test-never-exercises-real-dump-traceback-later` -- needs
  `tests/test_posthang_diagnostics_1660.py` to exercise the real `dump_traceback_later` call under
  an actual `-n 2` xdist session; a test-coverage fix.

**Deferred, left in `trap.d/` unchanged.** Five of twenty (25%) -- worth stating plainly per this
command's own instruction, since it is above the usual small fraction: three are architecture or
policy decisions this pass cannot make alone, and one is an incomplete investigation whose cause is
not yet known well enough to write a rule from.

- `1630.fifty-one-worktrees-accumulate-because-every-reap-gate-declines` -- needs a design decision
  on a separate reap sweep (unconditional for `[merged, clean]`, dirt-classification for
  `[merged, dirty]`) that this pass is not positioned to design; each individual per-tick decline is
  already correct.
- `1632.red-curate-pr-has-no-owner-after-its-spawn-dies` -- carried forward unchanged from the
  2026-09-16 deferred entry above: the fragment's own text still states the open question plainly
  (whether the scheduler should be doing ad hoc repairs at all, or whether curate's own PR belongs in
  the next tick's review set), an architecture decision for `skills/manager/`, not a jit rule.
- `1649.scheduler-direct-push-to-main-bypassed-six-required-checks` -- needs a policy decision
  (drop the bypass privilege on the branch-protection ruleset, versus route `agents/doctor.md`
  repairs through a pull request like every other change) that was not established from the
  fragment's own reads.
- `1666.cohort-35-label-accumulated-across-repeated-partial-freeze-attempts` -- needs a design
  decision on cohort semantics (retire `cohort-35` and freeze a fresh `cohort-36` cleanly, versus
  make `cohort_freeze_record.py`'s label write conditional on route agreement) that the fragment's
  own author explicitly leaves open.
- `1667.next-minor-pin-guard-failed-on-one-leg-and-passed-on-three` -- the fragment's own author
  states the one read that would separate the two explanations (whether the passing legs even
  collected the test) was not taken; nothing here can write a rule from an unconfirmed cause.

## 2026-09-18 — 10 fragments, 3 promoted, 2 merged, 1 declined, 2 deferred

**Promoted.**

- `1405.next-action-reads-stale-after-every-tracker-side-merge` -> `paths/00-manual/
  fetch-before-you-rank.md`, new rule firing on `commands/run.md` / `agents/scheduler-step.md` /
  `scripts/next_action.py`: every loop merge goes through the tracker, never the clone, so the
  clone's own `main` is behind `origin/main` by construction after every ordinary tick -- fetch
  and pull before trusting a ranking or count read.
- `1666.cohort-35-label-accumulated-across-repeated-partial-freeze-attempts` and
  `1666.cohort-35-partial-freeze-again-at-v0.40.0` -> `paths/00-manual/
  cohort-freeze-label-before-agreement.md`, new rule firing on `scripts/cohort_freeze_record.py`:
  a partial freeze still writes the label before discovering the two routes disagree, so repeated
  partial attempts re-stamp a cohort onto successive open-board snapshots -- five recurrences on
  the same cohort now recorded, cite the last cohort that fully agreed instead of retrying.
- `1673.a-hung-test-renders-as-a-post-session-hang-under-xdist` -> `paths/00-manual/
  xdist-hang-renders-as-post-session-hang.md`, new rule firing on `tests/` and
  `.github/workflows/tests.yml`: a `[ 99%]` line with no `[100%]` after it means the suite did not
  finish regardless of the summary line, `--durations` cannot see a hang because the stuck test
  never reports, and `-o faulthandler_timeout=180` is what actually names the stuck test.

**Merged.**

- `1632.red-curate-pr-has-no-owner-after-its-spawn-dies` and
  `1670.curate-worktree-fix-trades-a-stranded-clone-for-a-leaked-worktree` -> folded into the
  already-shipped `paths/00-manual/run-step-worktree-and-pr-ownership.md`, which already carried
  this exact gap as an open architecture question. Read together (the whole point of holding every
  fragment at once), the pair adds real, reusable content beyond restating the open question: the
  ad hoc recipe that resolved a real CI-red step-opened PR (read the failing leg, spawn a throwaway
  repair, merge on green), the "return the clone to the default branch" obligation that recipe
  itself needs, and the new leaked-worktree manifestation the worktree fix (#1670) introduced in
  place of the stranded-clone one it closed. This revises the prior pass's 2026-09-17 defer of
  `1632` (below) now that its sibling fragment is visible alongside it.
- `1648.windows-fd3-inheritance-across-msys-python-boundary-unverified` -> folded into the
  already-shipped `paths/00-manual/windows-subprocess-resolution.md` (already firing on
  `scripts/plugin_update.py`), alongside the same file's own root-cause fix for the CI hang this
  question turned out to share a cause with (`1673`, promoted above): the probe-vs-opt-in fd fix
  closes the hang risk this fragment worried about, but the original "does it actually reach the
  terminal on Windows" question is still unconfirmed and stated as such in the merged text.

**Declined.**

- `1649.scheduler-direct-push-to-main-bypassed-six-required-checks` -- the specific defect
  (`agents/doctor.md`'s on-default repair path committing without checking branch protection first)
  is already fixed: that file now calls `branch_protection_state` directly before writing a byte on
  a default-branch clone, and writes only when it reports `not-protected`. The deferred policy
  question this fragment raised (drop the bypass privilege vs. route repairs through a PR) is now
  largely moot for the doctor-repair path specifically, since doctor no longer needs to bypass
  anything to do its job; the scheduler's own sanctioned `trap.d/` direct-write exception is a
  separate, already-documented case (`trap-fragments.md`), not this fragment's subject.

**Deferred, left in `trap.d/` unchanged -- carried forward from 2026-09-17, no new information.**

- `1630.fifty-one-worktrees-accumulate-because-every-reap-gate-declines` -- still needs the same
  design decision on a separate reap sweep named in the 2026-09-17 entry below; nothing in this
  pass changes that.
- `1667.next-minor-pin-guard-failed-on-one-leg-and-passed-on-three` -- still needs the same read
  (opening the three passing legs' own logs to see whether they collected the test at all) named in
  the 2026-09-17 entry below; not taken here either.

## 2026-09-22 — 18 fragments: 4 promoted, 2 merged, 6 filed, 2 declined, 3 deferred

**Promoted.**

- `1693.explore-reviewer-red-green-check-staged-a-revert-in-the-shared-worktree` ->
  `vocabulary/00-manual/red-green-check-needs-its-own-clone.md`, new vocabulary rule firing on
  "self-review"/"red/green": a spawned reviewer that reverts tracked files in place to replay a
  red/green check, even calling it a "scratchpad copy", leaves the change in the real shared
  worktree's git index, not an isolated copy -- confirmed by a concurrent auditor's
  `tree_snapshot.py compare` reporting `mutated`. Use a genuinely separate worktree or clone instead.
- `1682.claude-md-history-narrative-drifts-from-its-own-table` and
  `1689.claude-md-own-row-drifted-from-release-marker-history` -> one new rule,
  `paths/00-manual/claude-md-budget-row-cross-check.md`, firing on `CLAUDE.md` and
  `scripts/claude_md_budget.py`: two independent lanes, four days apart, each found the "Re-baselined
  for #NNNN" narrative claiming a different byte count than the real committed table/code state.
  Read together, this is a recurring failure mode (trusting the prior paragraph's claimed ending
  number instead of measuring), not two one-off drifts -- worth a rule on its own even though neither
  fragment alone met the "not on volume" bar.

**Merged.**

- `1654.oss-workspace-progress-fd-windows-unverified-silent-fallback` -> folded into the
  already-shipped `paths/00-manual/windows-subprocess-resolution.md`: a failed `os.fdopen` on the
  progress fd and a healthy run with nothing yet to stream both set `progress_writer = None` and
  proceed identically -- the same defect class this whole plugin is named after, applied to a file
  this rule already governs.
- `1687.round2-auditor-deleted-a-sibling-snapshot-file` -> folded into the already-shipped
  `tools/00-manual/tree-snapshot-compare.md`: a required second-pass `oss:auditor` round deleted
  another spawn's still-live `-before-snapshot.json`, reasoning it was leftover debris from an
  earlier round in the same lane that really had left one behind. Never delete a file matching that
  naming convention that you did not personally create -- report it as an anomaly instead.

**Filed, as defect reports rather than rules.**

- `1651.setup-md-tracked-table-omits-triage-route-threshold` -> #1704. A one-off documentation gap
  (a table missing one key its own sibling row precedent already covers), not a recurring pattern a
  rule could catch.
- `1679.cross-repo-loop-filed-issue-missing-filed-by-loop-label` -> #1705. A code-path question
  (does cross-repo issue filing set the label at all) that needs reading the filing implementation,
  not an agent-behaviour pattern.
- `1681.release-gate2-absent-review-comment-age-clears-silently`,
  `1681.release-gate2-malformed-prs-json-exits-same-code-as-blocked` and
  `1681.release-gate2-newline-in-pr-number-reaches-column-0` -> #1706 (filed together, same script,
  same introducing PR). Three code-level absence/format defects in `release_gate2.py`, not rules.
- `1682.label-attachment-stated-unconditionally-in-two-of-three-touched-files` -> #1707. A
  documentation-consistency gap between three sibling files, mechanical fix, not a rule.
- `1686.partial-priority-label-creation-reads-satisfied-forever` -> #1708. A genuine design decision
  (doctor would need to record which labels it created itself) already named as such by both
  reviewers who found it; not a rule this pass can write.
- `1725.triage-signature-receipt-suppresses-a-standing-over-threshold-reading` -> #1709. A real
  question about `next_action.py`'s own suppression-receipt semantics, needing a decision about
  intended behaviour, not knowledge a rule could carry.

**Declined outright.**

- `1678.declined-trap-fragment-survives-curate-decline` -- actioned directly rather than turned into
  a rule: `1649` (see below) had already been declined with its trace recorded in this file on
  2026-09-18, but the fragment itself was never deleted, so it resurfaced in this pass's own
  backlog. Deleting it now closes the procedural gap this fragment reported; no fourth disposition
  ("declined but retained") is needed, `commands/run/curate.md`'s existing three deletion outcomes
  already cover it once the delete step is actually taken.

**Already declined; completing an interrupted decline.**

- `1649.scheduler-direct-push-to-main-bypassed-six-required-checks` -- declined and traced on
  2026-09-18 (see that section above); deleted now per `1678`'s own finding and remedy.

**Deferred, left in `trap.d/` unchanged -- carried forward, no new information.**

- `1630.fifty-one-worktrees-accumulate-because-every-reap-gate-declines` -- still needs the same
  design decision on a separate reap sweep named in the 2026-09-17 entry; nothing in this pass
  changes that.
- `1660.pytest-leg-margin-arithmetic-ignores-pre-run-tests-step-overhead` -- needs an instrumented
  CI run timing each step of a real job separately (checkout, setup-python, `pip install`) to know
  whether the existing margin tests already understate the true headroom; not something a single
  lane can produce locally.
- `1667.next-minor-pin-guard-failed-on-one-leg-and-passed-on-three` -- still needs the same read
  (opening the three passing legs' own logs to see whether they collected the test at all) named in
  the 2026-09-17 entry; not taken here either.
