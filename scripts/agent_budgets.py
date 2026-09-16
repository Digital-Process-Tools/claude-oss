"""Per-agent-definition size budgets (#491).

Turn-1 context (system prompt + agent definition + brief) is a median 44% of
a whole agent's cache-read consumption, measured across 610 transcripts, and
`agents/developer.md` alone is the largest single file in that context.
Consumption is bytes x turns: a median lane runs 55 turns and the observed
max is 329, so every byte here is paid for that many times over, before a
single instruction in the file has changed anyone's behaviour.

Deduplication was measured and ruled out as a fix (12-word shingle overlap
between the largest files runs 1.2%-6.5%): these files are large because
their content is distinct, not because it is copied. So the only lever left
is a visible number and a rule against silent growth -- which is what this
module is. It does not, and must not try to, judge whether any given
paragraph earns its size; that stays a human judgement call, made by
whoever still remembers which trap the paragraph exists for.

Budget = the size measured when the budget was set, plus ~10% headroom --
enough to land one honestly-justified paragraph without tripping the test on
the same diff that adds it, not enough to make growth free indefinitely.
Crossing it means one of two things, and the PR should say which:
replace something to pay for the addition ("replace, don't append" -- the
issue's own rule), or raise the number here, in the same diff, with a
sentence saying what was weighed against what. Lowering a budget while a
file sits under it is always fine, and is exactly the visible signal #491
asks for.
"""

from __future__ import annotations

from pathlib import Path

# repo-relative path (POSIX, matched by name against agents/*.md on disk) ->
# (bytes measured when the budget was set, budget bytes incl. ~10% headroom)
BUDGETS: dict[str, tuple[int, int]] = {
    # Raised for #769: a review agent declared read-only wrote into the
    # worktree it was auditing, twice in one run, by two different agents,
    # leaving no ref movement and no reflog trace -- the brief already said
    # not to, twice, and that was the proof a sentence is not a mechanism.
    # The fix is a caller-side receipt (scripts/tree_snapshot.py, in the
    # shape review_return.py already argues for a different silent loss in
    # the same review step) plus the invocation and the two exit states a
    # developer lane has to act on, which does not fit the prior headroom.
    # Re-baselined for #939: the three late phases -- self-review, review
    # returns, the report -- moved out to agents/developer/*.md, read when a
    # lane reaches them rather than held in the system prompt from turn one.
    # 89,714 B measured before the split (the prior 83,014 baseline had gone
    # stale, unchecked, while the file grew) became 47,819 B after it. The
    # phase files carry their own budgets in scripts/developer_phases.py.
    # Lowered, not raised: growth back toward the old number is exactly the
    # signal this budget exists to make visible.
    # Re-baselined for #1014: `check()` only ever compares measured size
    # against `budget` (the ceiling), never against `baseline`, so these five
    # numbers had drifted from disk with nothing to notice -- confirmed by a
    # dedicated comparison, `tests/test_baseline_matches_disk_1014.py`, added
    # in the same diff so this class of drift is caught going forward rather
    # than re-discovered by hand again. Budgets (the ceilings) are unchanged;
    # every file measured here was already comfortably under its own.
    # Re-baselined for #1247/#1248: 40699 B became 41206 B. Widened the
    # changelog-assembler location guidance from two canonical to two common
    # locations plus a resolves-in-tree fallback, and added an instruction
    # against opening a self-review finding by quoting/negating the
    # NO FINDINGS sentinel. Ceiling unchanged; comfortably under it.
    # Re-baselined for #1391's own self-review round: 41206 B became
    # 41227 B -- both reviewer spawns independently found the frontmatter
    # description still naming `/oss:manager` as a typeable slash command,
    # the exact confusion #1391 set out to remove now that SKILL.md no
    # longer publishes into the picker. Reworded to name the manager loop
    # without slash notation. Ceiling unchanged; comfortably under it.
    # Re-baselined for #1468: 41227 B became 41443 B. The review-return
    # pointer sentence now names a second, distinct failure mode -- the
    # `Agent` tool being totally unavailable one level down, rather than one
    # subagent_type name failing to resolve -- so a lane reading only the
    # spine still knows the two are not the same outcome before it opens
    # agents/developer/review-return.md's own new section. Ceiling
    # unchanged; comfortably under it.
    # Re-baselined for #1499: 41443 B became 42116 B -- one paragraph
    # under "Where you work" tells a lane to start from the brief's
    # "# Recon brief" section, reading only the sites it names, rather
    # than re-doing the orientation a recon spawn already paid for.
    # Ceiling unchanged; comfortably under it.
    # Re-baselined for #1535: 42116 B became 43514 B -- the spawn payload is
    # now the issue numbers and the worktree and nothing else, so the
    # orientation a brief used to hand over (the issue text, the live-worktree
    # list, the guard set, the recon spawn) is stated here as the lane's own
    # work. #1499's "start from the brief's Recon brief section" paragraph is
    # rewritten in the same diff to name the lane's own spawn, since no brief
    # carries that section any more. Ceiling unchanged.
    # #1542: the recon spawn became the lane's unconditional first step and
    # moved to the head of the orientation list. 43639 B became 43780 B; the
    # sentence that made it conditional was replaced by one saying why it
    # cannot be one. Ceiling unchanged at that point, 320 B of headroom left.
    #
    # #1499, rebased over #1535, #1540 and #1542: the 20,000 B read cap, that
    # a capped read renders like a whole file, and "never re-read what you
    # already have" -- ~1,008 B that no paragraph already in the file argued.
    # 43780 B became 44788 B, which is 688 B over the old 44,100 B ceiling, so
    # the CEILING MOVES to 45,300 B. Weighed: the alternative was cutting the
    # ranged-read technique or the supertool guard's reach, both of which a
    # lane trips within its first few turns, to make room for the cap that
    # motivates the first of them. A lane pays this file on every turn, so the
    # raise is real cost; it is smaller than one extra review round over a lane
    # that paged a large file believing it had read it. 512 B headroom.
    # Raised for #1518: 44788 B became 45460 B, 160 B over the 45300 B
    # ceiling. A lane that hits the harness's own auto-mode Bash classifier
    # going down mid-call used to end its turn on a bare "waiting" sentence
    # with no report path -- observed costing a sub-manager one SendMessage
    # resume plus ~45s of in-lane waiting -- so the retry-then-handback rule
    # belongs in the spine: the classifier can refuse any Bash call at any
    # point in a lane's life, not only inside one of the three late phases,
    # so a phase file was not the right home for it. Weighed against cutting
    # something else to pay for it: nothing else in this section argues a
    # weaker case today, so the ceiling moves instead, to 46000 B, ~1.2%
    # headroom -- narrower than the ~10% convention because this file is
    # already the largest single turn-1 cost in the loop (#491's own
    # measurement) and a wider ceiling would only be spent again.
    "agents/developer.md": (45460, 46000),
    # Re-baselined DOWN for #1071: the prose shared with agents/release-
    # auditor.md (the total Bash grant's explanation, how a read happens,
    # test behaviour reasoned not run -- 286 shared 8-grams, ~10% of each
    # file) moved to agents/audit/shared.md, a fragment with two parents
    # rather than one, budgeted separately in scripts/audit_shared.py since
    # neither agent_budgets.BUDGETS nor developer_phases.DOCUMENTS fits a
    # file with no single spine. 14174 B became 12963 B. Ceiling left
    # unchanged; a lower ceiling would only be spent again without anyone
    # choosing to.
    # Re-baselined UP for #1210: #1071's dedup deleted "Test behaviour is
    # reasoned, not run" from this file's own raw text, leaving only the
    # pointer to agents/audit/shared.md -- but tests/test_delegated_test_
    # run_877.py reads each file's own bytes directly and never resolves
    # that pointer, so the marker sentence silently stopped existing
    # anywhere the test could see it. Restored in this file's own text
    # alongside the pointer. 12963 B became 13273 B. Ceiling unchanged.
    "agents/auditor.md": (14402, 15600),
    # Re-baselined DOWN for #1071, the same extraction: 14953 B became
    # 13992 B. Ceiling left unchanged for the same reason.
    # Re-baselined UP for #1210, the same restoration as auditor.md above,
    # then reworded once more in the same lane's self-review round to keep
    # tests/test_audit_shared_1071.py's own duplication threshold (< 150
    # shared 8-grams between the two files) from being crossed again by the
    # restoration: 13992 B became 14424 B. Ceiling unchanged.
    "agents/release-auditor.md": (14636, 16400),
    # Re-baselined for #1391's own self-review round, same fix as
    # agents/developer.md above: 15467 B became 15488 B.
    # Re-baselined for #1410: 15488 B became 15522 B -- the cohort-freeze
    # prohibition now says the freeze is the release's own script, not a
    # maintainer's hand, matching the same change in accounting.md and
    # commands/release.md. Comfortably under the 16600 B ceiling.
    "agents/triager.md": (15522, 16600),
    # Baseline raised three times, each time for the same reason: a
    # review finding was a correctness or precision fix with nothing safe
    # to cut to pay for it in the same diff. (7450, 8200) -> (8578, 9450):
    # the OSS_AGENT_ROLE mechanism did not survive across Bash tool calls,
    # and "tag, publish" overstated what the code-level withholding
    # covers. (8578, 9450) -> (9918, 10900): the marker was write-only and
    # blocked a legitimate release forever after a dead sub-manager's
    # leftover file. (9918, 10900) -> (11714, 12900): "Same model, same
    # authority" was false (the frontmatter pins sonnet; the scheduler
    # runs whatever the maintainer's session runs) and the model choice
    # was an unweighed default sitting next to `color: blue` -- correcting
    # the claim and recording the choice as a judgement, plus the
    # measurement-hazard note for whoever wires the scheduler, are the
    # maintainer's own decision made legible rather than left silent.
    # Raised for #818: a fourth handback shape (`TICK: paused` +
    # `WAIT-DISPATCH:`/`WAIT-OBSERVABLE:`) for a sub-manager reaching a CI
    # wait with none of the loop's three waiting mechanisms available to it.
    # Nothing in the existing three states was safe to cut to pay for a
    # correctness addition -- a design decision this repo's own conventions
    # ask to be written down, not trimmed to fit.
    # Raised for #978: the frontmatter grant `SendMessage`, mandated in prose
    # since #880, was never actually present -- two live sub-manager spawns
    # hit exactly that gap and fell back to a fresh spawn with no state to
    # record it under. The bulk of the argument (what to record if the tool
    # itself refuses -- documented as gated behind an opt-in feature on some
    # harness versions) went to skills/manager/phases/dispatch.md, where the
    # rest of #880's argument already lives; this file only grew one clause
    # in its own #880 pointer sentence naming that dispatch.md now covers it
    # too. Baseline re-measured to 15501 B post-commit, per this module's own
    # convention (see #818's entry above); budget set with ~10% headroom.
    # Re-baselined for #1014 (see the sentence beside the four-row block
    # above): 16341 B on disk against a stale 15501 declared baseline.
    # Re-baselined for #1037: 16871 B on disk against a stale 16341 declared
    # baseline -- this lane's own pointer-update to `skills/manager/phases/
    # tick-order.md` grew the file. Budget unchanged; comfortably under it.
    # Raised for #1048: measured 17894 B against the prior 17000 B budget.
    # A reminder paragraph had already failed twice on this exact defect (a
    # sub-manager promising its own resumption instead of using `TICK:
    # paused`), so the fix is a self-validation step -- run the draft
    # handback through `tick_handback.py` before sending it -- rather than
    # another sentence restating the rule. Trimmed once already to fit as
    # much of the addition as possible; nothing else in this file was safe
    # to cut without losing a still-live rule, so the ceiling moves instead.
    # Re-baselined DOWN for #1162: 15247 B became 14666 B. The nine-line
    # inline CI-wait block (the pr_green.py call, its four states, the
    # #1086 substring trap) moved to skills/manager/phases/ci-green.md,
    # shared now with agents/releaser.md, leaving a one-line pointer here.
    # Ceiling left unchanged rather than brought down with it, the same as
    # every other re-baseline in this file: a lower ceiling would only be
    # spent again by the next addition without anyone choosing to.
    # Re-baselined for #1190: 14666 B became 15571 B. The CI-wait passage
    # (#818) and the pr_green.py pointer (#1086) contradicted each other --
    # one said always hand back, the other handed over a waiter -- and a
    # sub-manager that followed #818 six times in one tick paid ~11k tokens
    # per resume for it. Replaced with one ordered procedure (re-select a
    # freed lane, else `pr_green.py --wait` inside the turn, else hand back
    # with the fleet's occupancy folded into WAIT-OBSERVABLE) rather than a
    # third rule beside the two. Ceiling left unchanged; 1229 B of headroom
    # remains.
    # Re-baselined again in the same lane's own self-review round: 15571 B
    # became 16060 B. A reviewer spawn found three follow-on gaps in the new
    # procedure -- the WAIT-OBSERVABLE example wrapped across a markdown
    # line inside its own placeholder, which scripts/tick_handback.py's
    # single-line regex would have silently truncated had a sub-manager
    # reproduced it verbatim; step 2's pr_green.py --wait call had no branch
    # for a `pending` timeout, reading as though every call resolves the
    # wait; and it did not name what to do when that call times out still
    # pending. All three fixed in place. Ceiling unchanged; 740 B of
    # headroom remains.
    # Re-baselined for #1179: 16060 B became 16630 B. The select_issues.py
    # dispatch-selection call sits past skills/manager/phases/tick-order.md's
    # ~292-line default read window, so a sub-manager reading only the first
    # window never saw it and went hunting by ls/find. The literal command
    # now lives directly in this file, never truncated. Ceiling unchanged;
    # 170 B of headroom remains.
    # Re-baselined for #1198: 16630 B became 16758 B -- the short-lane
    # REASON paragraph now names --claim --group-state STATE (#1153) as the
    # mechanical derivation path, pointing at dispatch.md for the full
    # mapping, alongside --short-reason. Ceiling unchanged; 42 B of
    # headroom remains.
    # Raised for #1275: 16630 B became 17104 B, past the old 16800 B ceiling
    # by 304 B. The new paragraph points a tick's own review-time findings at
    # findings.md's new routing rule instead of silently keeping the old
    # file-everything default. Ceiling moved to 18800 B, ~10% headroom over
    # the new size, rather than trimming something else to absorb it.
    # Re-baselined for #1409: 17104 B became 17270 B -- the short-lane
    # reason list gained a fifth word, declined-for-cause (#1407), and a
    # one-line note on what it needs. Budget unchanged; comfortably under.
    # Re-baselined for #1469: 17270 B became 17850 B -- "Run the tick" no
    # longer sends the sub-manager to commands/tick.md; it names that
    # file's own first-line spawn instruction explicitly instead. Ceiling
    # unchanged; comfortably under.
    # Re-baselined for #1499: 17850 B became 18021 B -- the spawn-depth
    # section names the oss:recon spawn that precedes each developer
    # brief, and says it is not a second dispatch. Ceiling unchanged.
    # Raised for #1526: 18021 B became 19460 B, past the 18800 B ceiling by
    # 660 B. The lane_setup.py --claim call shape is now literal in this
    # file, beside the select_issues.py call #1179 already put here -- a
    # measured tick paged tick-order.md and dispatch.md three times each
    # (66,441 B) hunting for exactly this shape before making one malformed
    # call. Nothing already in the file argued that point, so nothing was
    # cut to make room; the ceiling moves to 21000 B, ~10% headroom over the
    # new size.
    # Re-baselined for #1535: 19460 B became 20047 B -- two paragraphs, one
    # saying the rendered `prompt` is the whole spawn payload and no brief is
    # composed, one saying recon is the lane's own spawn rather than this
    # agent's. Ceiling unchanged; 953 B headroom.
    #
    # Re-baselined again for #1532, stacked on that: 20047 B -> 19911 B. The
    # registry paragraph -- `--claim` refuses without `--lane`, never claim on
    # a probe, a phantom record blocks `--derive-held` for hours -- came out
    # with the registry it was about. Both sides re-baselined from the same
    # 19460 B starting point, so this number is `wc -c` on the rebased file,
    # not 20047 minus this change's own delta. Ceiling unchanged; 1,089 B
    # headroom, and this is a net shrink against #1535's number.
    # #1499, first half: the measurement of whose context a tick actually
    # spends -- lanes 6% of context sent against 59% for the coordination
    # layer, one sub-manager at 289,239 tokens before dispatching anything.
    # The file said how to read cheaply and never why it mattered here.
    # 19911 B became 20629 B.
    #
    # #1499, second half, rebased on top of the first: the optional `COST:`
    # self-report and what a tick is expected to say about its own spend.
    # 20629 B became 21515 B, which is 515 B over the old 21,000 B ceiling, so
    # the CEILING MOVES to 21,800 B. The two halves landed as separate pull
    # requests into the same file and neither argued the other's point, so
    # there was nothing to cut. Weighed: this file is re-sent on every turn of
    # a tick that is already the most expensive spawn in the loop, so the raise
    # is paid where it hurts most -- against a tick that cannot report its own
    # spend and therefore cannot be measured at all, which is the thing #1499
    # exists to fix. 285 B headroom.
    # Re-baselined for #1544: 21515 B became 20680 B. Select+claim+dispatch-
    # render moved into a new spawn (agents/tick-dispatch.md) that renders
    # the developer-lane `Agent(...)` calls without making them; this file
    # now spawns it, pastes what it renders, and no longer states the
    # select_issues.py/lane_setup.py call shapes or the fill-to-three
    # derivation inline. Ceiling unchanged; net shrink, 1120 B headroom.
    # Re-baselined for #1567: 20680 B became 21469 B -- the `respawned-for-cost`
    # carve-out, which a tick decides at the moment a lane comes back red and so
    # cannot be left only in the phase file it would have to go and read first.
    # Budget unchanged; 331 B headroom.
    # Re-baselined for #1544 step 2: 21469 B became 21993 B. The CI-wait
    # fourth shape's steps 1-2 now spawn `oss:tick-review` and translate its
    # `REVIEW:` report instead of calling `pr_green.py` and reasoning about
    # the wait inline; step 3 (the hand-back shape itself) is unchanged,
    # since the scheduler still resumes this file, never the spawn. Ceiling
    # moves to 22300 B: the replacement block, trimmed twice, still nets
    # larger than the block it replaced, because it also has to state what
    # the spawn's three report states mean for this file's own decision --
    # weighed against holding `ci-green.md`'s wait procedure and
    # `review.md`'s >24,000 B checklist out of this file's own context for
    # the rest of every tick that reaches this shape, which is the entire
    # point of #1544.
    # Re-baselined in the same lane's own self-review round: 21993 B became
    # 22184 B after two reviewers found the same real gap this file's own
    # step 2 needed to state -- that `oss:tick-review` files/comments/writes
    # a below-bar line itself, so this file never needs to redo it.
    # Re-baselined on the maintainer's own review return: 22184 B became
    # 22298 B -- step 2's own call description now says `oss:tick-review`
    # waits one call per pull request, not one for the whole batch, matching
    # the fix in `agents/tick-review.md`'s own step 1 (pr_green.py's real
    # contract cannot verdict more than one named pull request per call).
    # Ceiling raised 22300 -> 22900 in the same maintainer review, and the
    # headroom is itself the subject: 2 B is a tripwire rather than a budget.
    # The next lane to touch this file for any reason -- a typo, a renamed
    # script path -- goes red on arrival, and CLAUDE.md's own rule then makes
    # it write a weighed sentence for a one-line edit, which is a whole extra
    # review cycle bought for nothing. Weighed against leaving it: this file
    # grew 1,618 B across #1544's three rounds and has no further growth
    # planned, so 602 B is roughly one more paragraph, not a licence.
    # That tripwire fired, exactly as intended, on #1544 steps 3-4: 22298 B
    # became 24111 B -- the CI-wait shape's step 2 now names `oss:tick-merge`
    # for a `ready-to-merge` decision, and "Report back" now spawns
    # `oss:tick-accounting` to compose and validate the tick's own handback
    # draft before this file pastes it. Nothing already here argued for
    # cutting either addition: the merge authority reasoning and the "it
    # cannot send the message for you" limit are both load-bearing findings
    # this diff had to state, not restatable-shorter prose. Ceiling moves to
    # 24700 B, ~590 B headroom -- the same tripwire posture as before, not a
    # wider budget.
    "agents/sub-manager.md": (24111, 24700),
    # #696: the releaser agent -- a fresh-context spawn holding tag-and-publish
    # authority, delegating the six gates to commands/release.md rather than
    # restating them (per #673's lesson about two documents drifting).
    # Re-baselined for #1014: 9215 B on disk against a stale 8691 declared
    # baseline.
    # Raised for #1041: 9215 B became 10713 B, past the 9560 B ceiling. The
    # addition gives the releaser a fourth report state, RELEASE: paused,
    # the same shape #818 already gave a sub-manager reaching a CI wait --
    # observed three times in one release closing on an unkeepable "I'll
    # resume once CI reports back" instead. Nothing already in the file
    # argued that point, so there was nothing safe to cut to make room;
    # the ceiling moves to 11800 B, ~10% headroom over the new size.
    # Re-baselined in the same lane's own self-review round: 10713 B became
    # 10985 B after a reviewer spawn found the GATE: field's prose ("not
    # optional busywork") contradicted scripts/release_handback.py, which
    # treats it as optional. Budget unchanged; still under it.
    # Re-baselined for #1162: 7053 B became 7218 B -- a one-line pointer at
    # skills/manager/phases/ci-green.md (#1162), the shared CI-green read
    # sub-manager.md also now points at. Budget unchanged; 582 B of headroom
    # remains.
    "agents/releaser.md": (7218, 7800),
    # #1414: new file. `/oss:run`'s own scheduler used to read six command
    # files directly in its own long-lived session (setup, scaffold,
    # install-audit, triage, curate, changelog) -- exactly the erosion #695
    # built the sub-manager/releaser split to prevent, one layer over. One
    # generic spawn, reused across all six rather than six near-identical
    # wrappers, since none differ in shape -- only in which file to read.
    # Budgeted from the day it was added, the same posture #1389 already
    # takes for `commands/run.md`. Re-baselined in the same lane's own
    # self-review: 4554 B became 5154 B after a content-invariant test
    # found this file missing the untrusted-input clause every document
    # that can read issue/PR/comment text must carry -- `triage.md` reads
    # exactly that while this spawn is following it. Ceiling moved to
    # 5700 B, ~10% headroom over the new size.
    # Re-baselined for #1425: 5154 B became 5162 B -- the curate report
    # shape now names a fourth outcome, `defer`, alongside promote/merge/
    # decline, matching the fourth outcome curate.md itself gained. Ceiling
    # unchanged; comfortably under it.
    "agents/scheduler-step.md": (5162, 5700),
    # #1457: new file. `/oss:run`'s own step 1 used to run `doctor.sh`
    # inline and chase every WARN/FAIL in the scheduler's own long-lived
    # session -- fine for a scripted repair, but a line that needs
    # investigation (a stale clone HEAD, a rate-limit mystery across
    # pollers) then lands permanently in that session's context, the exact
    # erosion #1414 already closed for the six commands/run/*.md sub-steps
    # via agents/scheduler-step.md. This agent is the same move for the one
    # step 1 that still ran the hunt by hand. Budgeted from the day it was
    # added, the same posture #1389 and #1414 already take for a new file.
    "agents/doctor.md": (6064, 6700),
    # #1499: new file. A developer lane used to start with thirty
    # orientation reads it then carried for three hundred turns; measured
    # on one three-issue lane, 134.4M context tokens against 65.8M for the
    # same shape briefed from a read-only recon spawn's summary (the recon
    # itself cost 0.7M). This agent is that spawn: locate, never design,
    # die with the context. Budgeted from the day it was added.
    # Re-baselined for #1535: 3936 B became 4121 B -- the caller moved. A lane
    # spawns its own recon and keeps the summary where it is used; a dispatcher
    # may still spawn one for part 5 (the lane file set) alone, which it needs
    # before the lane exists, until #1532 retires the registry. "Report back"
    # is rewritten in the same diff -- it still told this agent its output gets
    # pasted into a developer brief, contradicting the intro two screens above
    # it -- so it now says who reads which part, since the spawn is told
    # neither. 3936 B -> 4348 B. Ceiling unchanged; 52 B headroom, which is
    # tight: the next edit here pays for itself or raises the ceiling.
    # #1542: the frontmatter now says the lane spawns this first thing, and
    # drops the claim that dispatch needs the file set "while the registry
    # still needs it" -- the registry was retired by #1532. 4348 B became
    # 4350 B. Ceiling unchanged, 50 B of headroom left.
    "agents/recon.md": (4350, 4400),
    # #1544: new file. `oss:sub-manager` used to read the board, rank it and
    # reason about dispatch fill inline, in the same context that goes on to
    # review, merge and account for the whole tick -- one sub-manager was
    # measured at 289,239 tokens before it had dispatched a single lane
    # (#1499). This agent holds only the select+claim+dispatch-render step:
    # `select_issues.py`, `lane_setup.py --claim`, and the fill-to-three
    # judgement `dispatch.md` already argues, moved into a throwaway
    # context. It does not spawn developer lanes itself -- see the file's
    # own "Why this file exists" section for why that boundary is
    # deliberate. Budgeted from the day it was added, the same posture
    # #1414 and #1499 already take for a new file.
    # #1546: the documented `lane_setup.py --claim` call gained `--phrase`,
    # `--subagent-type` and `--model`, plus three lines saying that without the
    # first two it renders nothing at exit 0. 6302 B became 6696 B. Ceiling
    # unchanged; 204 B headroom.
    # Re-baselined for #1544 steps 3-4: 6696 B became 6829 B -- the "Why this
    # file exists" sentence, stale since step 2 shipped and now doubly stale
    # once steps 3-4 (this diff) shipped too, is fixed to say all four steps
    # exist as their own spawns rather than claim steps 2-4 are still unsplit
    # (trap.d/1544.tick-dispatch-why-section-now-overstates-what-stays-
    # unsplit.md, filed against #1544 step 2, named this exact fix). Ceiling
    # unchanged; 71 B headroom.
    # Re-baselined for #1579: 6829 B became 6876 B -- the --claim call dropped
    # --lane, which only ever fed the claim receipt's own unread [lane] block,
    # plus one sentence saying so. Ceiling unchanged; 24 B headroom.
    "agents/tick-dispatch.md": (6876, 6900),
    # #1544 step 2: new file. `oss:sub-manager` used to call `pr_green.py
    # --wait` and then read `skills/manager/phases/review.md`'s checklist
    # (together over 24,000 B) inline, in the same long-lived context that
    # goes on to merge and account for the whole tick. This agent holds only
    # the wait-then-review step: it is handed the pull request number(s)
    # already open this tick, waits on CI itself, and applies `review.md`'s
    # checklist -- including the report-for-filing/below-bar routing -- in
    # a throwaway context, then dies. It does not merge and does not write
    # the tick's own handback (#1544's steps 3-4), the same boundary
    # `agents/tick-dispatch.md` draws around steps 2-4. Budgeted from the
    # day it was added, the same posture #1414, #1499 and #1544 step 1
    # already take for a new file.
    # Re-baselined in the same lane's own self-review round: 7110 B became
    # 8741 B after two spawned reviewers (Explore, oss:auditor) independently
    # found the same real gap -- the "filing an issue, commenting on one" was
    # withheld in the same sentence review.md assigns it to whoever is doing
    # the review, leaving no-op handling for report-for-filing/below-bar
    # items -- plus a genuine forging risk in "carried verbatim" with no
    # quoting convention (unlike tick-dispatch.md's nonce-wrapped payload),
    # and a mixed-batch report shape review.md's own routing table never
    # named. All three were real findings on a brand-new file, so nothing
    # here argued for cutting rather than fixing.
    # Re-baselined on the maintainer's own review return: 8741 B became
    # 10697 B. pr_green.py's real contract is "one call resolves at most one
    # named pull request" (`scan()` stops at the first non-pending; `--wait`
    # returns on the first actionable one or reports every name pending) --
    # this file's step 1 previously documented a single call over the whole
    # batch as though it verdicted every pull request, which it cannot. Step
    # 1 now documents N sequential per-pull-request calls, states the N*T
    # worst-case wall-clock cost this creates explicitly, and "Why this file
    # exists" now says outright that the caller's own `Agent(...)` blocks
    # for the whole of that wait. Nothing here argued for cutting length to
    # avoid stating a real cost. Ceiling moves to 11200 B, ~5% headroom.
    "agents/tick-review.md": (10697, 11200),
    # #1544 steps 3-4: two new files. `oss:sub-manager` used to merge on green
    # and assemble its own state-file entry and `TICK:` handback inline, in
    # the same long-lived context that dispatch and review had already been
    # carved out of. `agents/tick-merge.md` holds the confirm-gated merge and
    # its post-merge obligations (`skills/manager/phases/merge.md`, >15,000 B)
    # for one pull request named `ready-to-merge`; `agents/tick-accounting.md`
    # runs the tick's `oss_state.py --decision` call and the cohort/intake/
    # plugin-identity derivations that feed it, and drafts the validated
    # `TICK:` block -- it cannot send that block, since `tick_handback.py`
    # classifies only the sub-manager's own final message, so the sub-manager
    # still pastes what it drafts. Budgeted from the day each was added, the
    # same posture #1414, #1499 and #1544 steps 1-2 already take.
    # Re-baselined for #1571: 5905 B became 7058 B, ceiling 6300 -> 7300 B. The
    # file shipped stating merge.md's gates in prose and giving the spawn no call
    # that establishes any of them -- it is handed a bare pull request number, and
    # its first documented action was the confirm-gated merge itself. Gate 3
    # caught it before this spawn had ever run once. The new step 0 is the two
    # reads plus the could-not-merge arm, placed ahead of the merge because the
    # file is read top-down by an agent that acts as it reads. Nothing here was
    # cut for it: every other paragraph in this file is an obligation that
    # survives the merge (the read-back, the assignee release, the Closes #N
    # verification, the default-branch recheck), and a gate that runs before the
    # write cannot be paid for by weakening the checks that run after it.
    "agents/tick-merge.md": (7233, 7300),
    "agents/tick-accounting.md": (7219, 7700),
}


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"agent_budgets: no .git found walking up from {here}")


def check() -> list[dict]:
    """One result per budgeted path -- 'ok', 'over' or 'missing'.

    'missing' is a third state on purpose: a budgeted file that is not on
    disk is not "under budget", it is a fact nobody chose, and answering
    'ok' for it would be exactly the absence-read-as-clean this repo is
    named after.
    """
    root = repo_root()
    results = []
    for rel, (baseline, budget) in BUDGETS.items():
        path = root / rel
        if not path.exists():
            results.append(
                {
                    "path": rel,
                    "state": "missing",
                    "size": None,
                    "budget": budget,
                    "baseline": baseline,
                }
            )
            continue
        size = len(path.read_bytes())
        state = "over" if size > budget else "ok"
        results.append(
            {
                "path": rel,
                "state": state,
                "size": size,
                "budget": budget,
                "baseline": baseline,
            }
        )
    return results


if __name__ == "__main__":
    import json

    print(json.dumps(check(), indent=2))
