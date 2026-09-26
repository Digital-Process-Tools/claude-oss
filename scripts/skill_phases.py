"""Where the manager loop's prose lives, and what each piece of it costs.

`skills/manager/SKILL.md` is loaded whole by `Skill(manager)`, which
`commands/tick.md` and `commands/release.md` both open with. Unlike an agent
definition it is not re-read per turn from disk -- it enters the session's
context once and is then paid for on every turn of that session at cache-read
price. At 122,423 B that was ~31k tokens standing in context for the whole of
every tick and every release, whether or not the session ever reached the
phase a given paragraph governs. #491 budgeted the agent definitions and said,
in as many words, that the manager skill was out of its scope; nothing counted
this file at all.

So the loop's prose is split in two:

- the **spine**, `SKILL.md`: what governs a decision the loop takes every
  tick, plus one directive per phase and a pointer to that phase's file;
- the **phases**, `skills/manager/phases/*.md`: the argument behind each
  phase's rules -- the incident it was written for, the measurement, the
  thing that was tried and rejected -- read at the moment the loop enters
  that phase.

**The split is not a licence to skim.** A phase file that is not read is a
rule that did not run, and a rule that did not run renders exactly like a
rule with nothing to say -- this plugin's own defect class, pointed at its
own documentation. The spine therefore asks each phase to state whether it
read its file, in the same three states everything else here uses: `read`,
`not-read` with a reason, or `could-not-read`. Nothing in this module can
observe that; what it can observe is the half that is on disk.

Three questions, one row each:

- **size against a budget** -- `ok` / `over` / `missing`, the same shape and
  the same reasoning as `scripts/agent_budgets.py`, whose `repo_root` this
  module reuses rather than copying. `missing` is load-bearing: a declared
  phase file that is not on disk is not "under budget".
- **referenced** -- does the spine name this path? A phase file the spine
  never names is unreachable, because the loop reads the spine and nothing
  else until the spine sends it somewhere. `None` means the question could
  not be asked at all (the spine itself was unreadable), and it must never
  render as `True`.
- **what it governs** -- declared here beside the budget, so the index in
  the spine and the set on disk have a third party they both answer to.

And one question about the set rather than about a file: **is there a phase
file on disk that this module does not declare?** `scripts/manager_docs.py`
derives the loop's documents from disk, so the two views can be compared, and
an `undeclared` row is the mirror of `missing` -- a phase file nobody budgeted,
which is how the whole measurement quietly stops covering its subject again.
Reporting only the declared paths would answer "every file I know about is
fine", which is true of an empty declaration too.

Budgets are the measured size plus ~10% headroom, exactly as #491 sets them:
enough to land one justified paragraph without reddening the diff that adds
it, not enough to make growth free. Crossing one means replacing something
or raising the number here in the same diff with a sentence saying what was
weighed. This module cannot judge whether a paragraph earns its size; that
stays a human call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_budgets import repo_root  # noqa: E402
from manager_docs import documents  # noqa: E402

#: The always-loaded half.
SPINE = "skills/manager/SKILL.md"

#: repo-relative path (POSIX) -> (bytes measured when the budget was set,
#: budget bytes incl. ~10% headroom, what the file governs).
DOCUMENTS: dict[str, tuple[int, int, str]] = {
    # Re-baselined downward (#958): the ranking table and the upstream-filing
    # section moved out to phases/findings.md, 62,829 -> 54,751 B. The budget
    # comes down with the measurement rather than staying at 64,600 B, because
    # a ceiling left 9,849 B above the file is a saving that can be spent
    # again without anybody choosing to -- which is the same invisibility the
    # budgets exist to remove. ~10% headroom over the new size, as #491 sets
    # them.
    # Re-baselined downward again (#960), second round of the same split: the
    # pre-flight and dispatch order went to dispatch.md, the platform band to
    # review.md, cadence and the loop-doctrine argument to accounting.md.
    # 54,751 -> 42,604 B; 62,829 B before #958, so -32.2% across the two.
    # Same reasoning as #958's raise-nothing rule: the ceiling follows the
    # measurement down, or the saving is spendable without a decision.
    # Re-baselined for #1014: `check()` only ever compares measured size
    # against `budget` (the ceiling), never against `baseline`, so this
    # number had drifted from disk (42867 B) with nothing to notice --
    # confirmed by a dedicated comparison, `tests/test_baseline_matches_
    # disk_1014.py`, added in the same diff. Budget is unchanged; the file
    # was already comfortably under it.
    # Re-baselined for #1029: 44358 B on disk against a stale 42867 declared
    # baseline -- #1026 grew this file (#976's push-to-main rule, #1017's
    # worktree-reap fix) without touching this table. Budget unchanged; the
    # file is still comfortably under it (2542 B headroom).
    # Re-baselined for #1037: 44679 B on disk against a stale 44358 declared
    # baseline -- the new tick-order.md row above and its accompanying
    # pointer sentence grew this file. Budget unchanged; comfortably under it.
    # Re-baselined for #1069: 45046 B on disk -- the claim/label call-site
    # rewrites (dispatch_rank.py/issue_claim.py/preflight_check.py/
    # fleet_label.py folded into select_issues.py/lane_setup.py) grew this by
    # 367 B. Budget unchanged; comfortably under it.
    # Re-baselined again for #1069's own self-review round: 45046 B became
    # 45059 B after two more bare-mention fixes an auditor spawn found
    # (`preflight_check.py`/`dispatch_rank.py` with no `scripts/` prefix).
    # Budget unchanged.
    # Re-baselined a third time (maintainer review): 45059 B became 45029 B
    # -- the dispatch table's --label cell moved from four named flags back
    # to positional arguments (fleet_label.py's own old shape), a net
    # shrink even after the mode-selecting --label token. Budget unchanged.
    # Re-baselined DOWN for #1136: 45029 B became 40700 B. The rationale was cut
    # per .claude/jit-context/paths/00-manual/md-is-a-manual-not-a-rationale.md --
    # `Who decides`, `Operational hazards` and every per-phase directive block are
    # untouched. Ceiling comes down with the measurement (#958, #960).
    # Re-baselined for #1162: 40700 B became 41261 B -- the "CI green" directive
    # block and the new phase-file table row. Budget unchanged; comfortably
    # under it.
    SPINE: (
        # Re-baselined for #1083: 41261 B became 41367 B -- the op table's
        # own `Filing` row still stated the pre-#1083 unconditional
        # attach-the-label rule ("every time"), which directly contradicted
        # accounting.md's own new provenance directive; a self-review found
        # it and it was corrected here rather than left standing.
        # Re-baselined for #1190's own self-review round: 41367 B became
        # 41601 B -- the CI-wait bullet under "Operational hazards" still
        # stated #818's "always hand back" rule as the whole answer,
        # contradicting the new decision procedure agents/sub-manager.md
        # gained the same round. Budget unchanged; comfortably under it.
        # Re-baselined for #1275's own self-review round: 41601 B became
        # 41738 B -- the "report-for-filing" summary sentence still claimed
        # "the three receipts", stale the moment review.md gained a fourth
        # (a trap.d/ fragment for a non-blocking row). Budget unchanged;
        # comfortably under it.
        # Re-baselined for #1391: 41738 B became 41739 B -- `user-invocable`
        # (HYPHENATED; the frontmatter key Claude Code actually documents,
        # not the underscored `user_invocable` an earlier draft of this fix
        # mistakenly pinned, which the harness silently ignores) set to
        # false so the spine no longer publishes into the slash picker as
        # /oss:manager; it is a library loaded by commands/tick.md and
        # commands/release.md via Skill(manager), never an entry point.
        # Budget unchanged; comfortably under it.
        # Re-baselined for #1394: 41739 B became 42837 B -- the new "Inbound,
        # before anything new" directive block and its table row point a tick
        # at skills/manager/phases/inbound.md before dispatch. Budget
        # unchanged; comfortably under it.
        # Re-baselined for #1410 self-review: 42837 B became 42893 B -- the
        # cohort-freeze sentence in "Closing a tick" now says the freeze is
        # the release's own script rather than a maintainer's hand, closing a
        # stale-prose finding a self-review spawn caught. Budget unchanged;
        # comfortably under it.
        # Re-baselined for #1532: 42893 B became 42577 B -- the op table's
        # two `--derive-held`/`--against` probe rows collapsed into one
        # read row with the retired flags named as retired.
        # Re-baselined for #1544 step 2 self-review: 42577 B became 42670 B --
        # the "Operational hazards" bullet describing the sub-manager's CI
        # wait still said it calls `pr_green.py --wait` directly, which #1544
        # step 2 moved into a spawn (`oss:tick-review`). Budget unchanged;
        # comfortably under it.
        # Re-baselined for #1579: 42670 B became 42649 B -- the `--claim`
        # call's own row dropped `--lane`, same fix as the phase files.
        # Budget unchanged.
        # Re-baselined for #1555 (self-review, Explore reviewer): 42649 B
        # became 42749 B -- the "AND registers the lane" claim in *Run a
        # fleet, not a queue* was stale since #1532; `--claim` writes only
        # the GitHub assignee now. Budget unchanged.
        # Re-baselined for #1682: 42749 B became 42904 B -- the filing op
        # table row now also names deriving `labels.priority`/
        # `labels.lane_other`, restructured in the same lane's own
        # self-review round to stop "plus labels.priority and
        # labels.lane_other" reading as scoped to the same "own initiative
        # only" clause as `labels.filed_by_loop`. Comfortably under the
        # 44800 B ceiling; ceiling unchanged.
        # Re-baselined for #1691: 42904 B became 42777 B -- a third,
        # word-for-word copy of the dead "triager is the board" sentence
        # (found by a spawned reviewer during self-review) removed from the
        # "Delegating" paragraph, keeping the still-live sentence beside it
        # about an unresolved `subagent_type`. Ceiling unchanged.
        # Re-baselined for #1707: 42777 B became 42862 B -- the Filing op
        # table row now states the omit-if-missing rule for
        # `labels.priority`/`labels.lane_other` inline, matching what
        # review.md already says, instead of stating attachment
        # unconditionally. Ceiling unchanged.
        # Re-baselined for #1724: 42862 B became 44338 B -- one canonical
        # classifier-denial rule (retry once, report either way, never
        # reword the call) replaces three inconsistently-worded copies in
        # tick-order.md, merge.md and commands/release.md, plus a
        # one-sentence distinction from the neighbouring "do the step
        # yourself" bullet, which governs a different actor. Comfortably
        # under the 44800 B ceiling; ceiling unchanged.
        # Re-baselined for #1751: 44338 B became 45209 B -- the same rule
        # narrowed to a Bash command-string denial only, never a
        # content-classification denial ("Instruction Poisoning", "Create
        # Public Surface") and never a non-Bash Agent/Task spawn, plus a
        # new clause against a parent agent re-executing what its child was
        # denied -- three observed misapplications the unscoped wording had
        # licensed. Ceiling moves to 46000 B, ~1.7% headroom.
        # Re-baselined again in the same lane's own self-review round: two
        # reviewers independently found the new "lane_setup.py --release
        # (an assignee release, same three files)" clause false -- that
        # call appears in none of the three named files, and its real call
        # site (agents/tick-merge.md) carried no #1724/#1751 pointer at
        # all. Corrected to name agents/tick-merge.md directly. 45209 B
        # became 45215 B. Ceiling unchanged; comfortably under it.
        # Re-baselined a third time, required second-pass round
        # (fix_commit_scope.py flagged the self-review fix commit itself):
        # a reviewer found the same bullet's closing "not three separately
        # worded ones" left stale once the fix above made it a four-item
        # list. Corrected to "not four". 45215 B became 45214 B. Ceiling
        # unchanged.
        45214,
        46000,
        "the loop itself: what is decided every tick, and where each phase's rules live",
    ),
    # Raised (#725): measured 26,052 B against the prior 26,100 B budget -- 48
    # B of headroom, and a lane in this same tick had already been forced to
    # place a new directive in SKILL.md instead of here solely because of that
    # margin (see CLAUDE.md's "The manager skill is a spine plus one file per
    # phase" section, the paragraph beside this table, for the receipt).
    # A split was weighed and declined: dispatch.md's content -- fleet size,
    # lane disjointness, bundling, what every brief carries -- is one subject
    # in one section, not two phases wearing one name, and a fresh split is a
    # larger, separately-reviewable change this issue does not warrant.
    # Re-baselined silently was declined too, per this file's own rule that a
    # raise carries a sentence about what was weighed. This is the file's
    # third budget change; the margin should be re-measured at the next one
    # rather than assumed still adequate.
    # Raised again (#798, #799): measured 29,456 B against the prior 28,700 B
    # budget. Two maintainer decisions land in this one file -- the dispatch
    # order's selection rule and the three-issue lane default -- and both belong
    # where a lane is actually assembled rather than in the spine, which is
    # where the previous raise's own margin had already forced one directive to
    # go. Paid for partly by cutting: two sentences of this addition were
    # trimmed as restating principles CLAUDE.md already argues at length, which
    # recovered 240 B of the 996 B overage. The rest is new argument -- the six
    # rows' rationale, why companions are not re-ranked, and the three short-lane
    # reasons -- and trimming further would have removed the reasoning rather
    # than the words. A split was weighed and declined again for #725's reason:
    # this is still one subject, and a fresh phase file plus its spine directive
    # block is a larger change than either decision warrants. Fourth budget
    # change; #725 asked for the margin to be re-measured rather than assumed,
    # and this is that measurement -- ~10% headroom over the new size.
    # Raised again (#866): measured 33,036 B against the prior 32,400 B budget --
    # the citation requirement for a declined dispatch is a correctness addition
    # with nothing safe to cut to pay for it in the same diff, the same reasoning
    # every prior raise in this file gives. Fifth budget change.
    # Raised again (#880): measured 37,253 B against the prior 36,400 B budget --
    # #878 landed between this lane's own measurement and its rebase, consuming
    # almost all of the file's remaining headroom (33,036 -> 36,104 B) before
    # #880's own addition (the one-dispatch-per-tick rule, trimmed twice to
    # 923 B) pushed it over by 853 B. Not paid for by cutting: nothing in this
    # file's existing argument was judged safe to trim without a separate,
    # reviewed decision about which paragraph to shorten. This raise desyncs
    # CLAUDE.md's own budget table (tests/test_claude_md_phase_budget_table_725.py)
    # until CLAUDE.md -- held by open PR #883 at the time of this raise -- is
    # free to receive the matching row; that test is expected to be red on this
    # branch and is reported as such rather than silently left unexplained.
    # Sixth budget change.
    # Raised (#960): measured 45,990 B against the prior 41,000 B budget. The
    # spine's whole `Deciding what to build` section -- the pre-flight probe and
    # the dispatch order -- moved in here, which is where a lane is actually
    # assembled and where a session that never dispatches should not pay for it.
    # Nothing was cut to pay for it: this is relocated argument, not new
    # argument, and trimming it in the same diff would have hidden which bytes
    # moved and which were dropped. Seventh budget change for this file.
    # Raised (#1016): measured 52601 B against the prior 50600 B budget --
    # 10 B of headroom left before this raise, following #725's own precedent
    # where a 48 B margin already forced a misplaced directive once (see
    # CLAUDE.md's own note beside this table). #1020's `--stack-on` paragraph
    # is what pushed it over: it documents a flag that had already landed
    # (#1006/#1009) with no brief, phase file or agent definition naming it,
    # so there was nothing to cut to pay for it -- the addition is the fix,
    # not padding. Also folds in #1014's own baseline re-measurement (see
    # that comment's note): declared baseline was 45990, disk read 50590
    # before #1020's own edit landed. Eighth budget change for this file;
    # ~10% headroom over the new size.
    # Re-baselined for #1022: 53490 B on disk against a stale 52601 declared
    # baseline -- #1022's own eighth-checklist-item edit grew this file.
    # Budget unchanged; comfortably under it either way.
    # Re-baselined for #1036/#1037: 54270 B on disk against a stale 53490
    # declared baseline -- the #1036 select_issues.py directive and the #1037
    # step-5 pointer update both landed in this file. Budget unchanged;
    # comfortably under it.
    # Raised for #1084: 58344 B on disk against the prior 57900 B ceiling, a
    # 444 B overage. New subsection states the four (really five) cases for
    # whether a pending vs red default branch should block dispatch, merge or
    # release -- a rule this repo was following by habit rather than by
    # instruction. Too small an overage to be worth trimming something else
    # to absorb, so the ceiling moved with ~10% headroom over the new size
    # rather than cutting anything.
    # Re-baselined for #1084's own self-review round: 58344 B became 58392 B
    # after two small precision fixes to the new subsection's cross-reference
    # wording (radar's board-member row is established at tick-order.md's
    # step 4, not inside "What ends a tick" itself). Budget unchanged.
    # Re-baselined for #1069: 58392 B became 58947 B -- the six claim/label/
    # rank/preflight call-site rewrites (the family collapsed to two entry
    # points, #1069) grew this file by 555 B. Budget unchanged; comfortably
    # under it. Re-baselined again in the same lane's own self-review round:
    # 58947 B became 58993 B after four more bare-mention fixes an auditor
    # spawn found (`issue_claim.py`/`dispatch_rank.py`/`preflight_check.py`
    # with no `scripts/` prefix, invisible to the prose guard's own Tier 1
    # regex). Budget unchanged.
    # Re-baselined a third time (maintainer review): 58993 B became 58916 B
    # -- --label's two worked examples moved from four named flags back to
    # positional arguments, matching fleet_label.py's own old call length
    # plus the one unavoidable --label mode-selector token. A net shrink.
    # Budget unchanged.
    # Re-baselined DOWN for #1136: 58916 B became 51277 B, a 54% cut to the
    # selection band (14240 B to 6601 B). That band was written when a session
    # drove selection by hand across four scripts; #970 composed them into
    # select_issues.py, #1068 added groups and #1129 gave grouping a file set it
    # could derive, and the prose was never cut back to match. A phase file is an
    # operator's manual for the tools its phase runs -- why three issues per lane
    # beats four belongs beside _GROUP_TARGET = 3, not here, and each incident
    # stays recorded in its own issue. The ceiling comes down with the
    # measurement rather than staying at 64200 B, for the reason #958 and #960
    # already give for their own re-baselines: a ceiling left far above the file
    # is a saving spendable again without anybody choosing to.
    "skills/manager/phases/dispatch.md": (
        # Re-baselined for #1083/#1178: 52772 B became 53168 B -- the
        # `--board`-vs-default-mode stdin contract, stated once here rather
        # than left ambiguous next to the true "takes no input" sentence
        # about the other mode. Budget unchanged; comfortably under it.
        # Re-baselined again in the same lane's own self-review round:
        # 53168 B became 53485 B -- the first version of that sentence
        # claimed a wrong-shaped `--board` payload always fails with a
        # stdin-parse error; verified against the running script it can
        # instead exit 0 with a silently degraded receipt, or crash with an
        # unrelated traceback, and the sentence now says so.
        # Re-baselined for #1200: 53485 B became 53209 B -- the
        # stdin-contract sentence is gone; `--board` fetches its own board
        # now, the same route the default mode uses, so there is no
        # exception left to describe. Budget unchanged.
        # Re-baselined for #1198: 53209 B became 54117 B -- the four-word
        # short-lane REASON passage now names `--claim --group-state STATE`
        # (#1153) as the normal, mechanical derivation path, alongside
        # `--short-reason`'s continued role as the explicit override for the
        # unmapped `candidates` state. Budget unchanged; comfortably under.
        # Re-baselined for #1374: 54117 B became 53938 B -- two stale
        # "eleven-row findings table" mentions (a hardcoded row count, wrong
        # the moment a twelfth row was added) were corrected to drop the
        # count rather than update it to thirteen and go stale again the
        # next time a row is added. Budget unchanged; comfortably under it.
        # Re-baselined for #1409: 53938 B became 55309 B -- a new paragraph
        # after the verbatim supertool blockquote states that the blockquote
        # is wrong as written inside a worktree of a managed repo that is
        # supertool's own checkout, and points at the new
        # `doctor.supertool_invocation` detection rather than editing the
        # blockquote itself. Budget unchanged; comfortably under it.
        # Re-baselined for #1499: 55309 B became 56678 B -- a paragraph
        # spawning oss:recon before each brief, and a ninth brief element
        # naming where its output goes. Budget unchanged; 722 B headroom.
        # Re-baselined for #1530: 56678 B became 56696 B -- the group's own
        # bound restated as the shared lane label rather than file adjacency.
        # Re-baselined for #1535, on top of that: 56696 B -> 56754 B. Eight of
        # the nine brief elements are retired (each was a restatement of
        # agents/developer.md, which every lane holds on every turn), replaced
        # by the two-fact spawn payload and the composed-prompt schema; the
        # supertool blockquote stays, for a spawn whose own definition does not
        # carry the write route. The recon section is rewritten in the same
        # diff: the lane spawns its own, and only the `## Lane file set` read
        # survives on this side, until #1532 retires the registry that needs
        # it.
        #
        # #1532 is that retirement, stacked here: 56754 B -> 54898 B. The
        # held-set derivation, its `--against` fallback and the five-state
        # `availability` verdict chain they fed are gone, replaced by a shorter
        # note saying what answers the question now, plus this change's own
        # self-review round rewriting the *Claim before you spawn* paragraph,
        # which still named five claim states and a deleted docstring. #1530
        # and #1532 both re-baselined from the same 56678 B, so this is
        # `wc -c` on the rebased file rather than either side's arithmetic.
        #
        # +297 B on top of that, in the same change: #1535 left a
        # dispatcher-side recon use standing "only until #1532 lands", on the
        # stated grounds that `--claim` needs `--lane`. #1532 removed that
        # requirement, so the paragraph's REASON is false while the use itself
        # is still worth having (guard lookup, `--suggest-companions`). It is
        # corrected rather than deleted -- dropping a surface that landed
        # hours earlier is the maintainer's call. Weighed against replace-
        # don't-append: the correction is shorter than the paragraph it
        # replaces would have been if left and footnoted, and a false stated
        # reason in the phase file a dispatcher actually follows is the
        # expensive kind of stale prose. Budget unchanged; 2,205 B headroom.
        # Re-baselined for #1518: 55195 B became 56050 B -- the
        # agent-unreachable paragraph gained a sibling stating that a
        # task-notification carrying one present-tense sentence and no
        # report path is a lane that stopped, not one that finished, naming
        # the harness's own auto-mode Bash classifier outage as the observed
        # cause; read the task's output file before re-dispatching. Budget
        # unchanged; 1,350 B headroom.
        # Re-baselined in the same lane's own self-review round: 56050 B
        # became 56712 B -- a reviewer spawn found "read its last tool
        # calls" named no real mechanism (no per-task output-file artifact
        # is documented anywhere else in this repo, and the phrase read as
        # invented). Corrected to name the harness's own `output-file`
        # metadata field on a task-notification, and to grep it for the
        # classifier's own refusal wording rather than reading it whole --
        # the harness's own guidance on receiving a task-notification
        # already says not to Read/tail that file, since it is a full JSONL
        # transcript. Budget unchanged; 688 B headroom.
        # Re-baselined for #1567: 56712 B became 58022 B, and the ceiling went
        # from 57400 B to 58500 B -- the resume rule's own cost argument had
        # priced only the fresh spawn, and a red lane at 421,672 was measured
        # spending 15,558,821 tokens across 38 turns of follow-up. The carve-out
        # and the fourth dispatch state it names do not fit the 688 B that were
        # left. Weighed: a first draft ran 1,800 B and was cut to 1,310 B by
        # merging its three paragraphs into two and dropping the comparison
        # lanes' figures, which live in the issue. Cutting further would have
        # taken the measurement itself, which is the only thing that makes the
        # carve-out arguable rather than a preference, or the #978 SendMessage
        # paragraph beside it, which is a live trap two sub-manager spawns have
        # already hit. This file is the loop's largest phase file and is read on
        # every tick that dispatches, so the raise is ~2.5% rather than the usual
        # ~10%.
        # Re-baselined for #1579: 58022 B became 57948 B -- three --claim call
        # shapes dropped --lane, which only ever fed the claim receipt's own
        # unread [lane] block. Ceiling unchanged.
        # Re-baselined for #1555: 57948 B became 58094 B -- the `lane-collision`
        # disposition dropped from #970/#1036's own directive paragraph (retired
        # by #1528/#1530, never recomputed since), replaced with a one-sentence
        # pointer to how an overlap is judged instead. Ceiling unchanged.
        # Re-baselined for #1691: 58094 B became 56845 B -- two dead rules
        # deleted: the "triager is the board" agent-definition sentence and
        # the "One dispatcher-side use survives" oss:recon spawn paragraph,
        # both prose for a dispatch step #1544 already moved to
        # oss:tick-dispatch, which is granted no Agent tool and so could
        # never run either. Ceiling unchanged.
        56845,
        58500,
        "delegating: the dispatch order, fleet size, lane disjointness, bundling, what every brief carries, and when to stack a lane on a sibling branch instead of default_branch",
    ),
    # Re-baselined for #1014: 19369 B on disk against a stale 18864 declared
    # baseline. Budget unchanged; comfortably under it either way.
    # Re-baselined for #1069: 19369 B became 19598 B -- the release call
    # (issue_claim.py --release folded into lane_setup.py --release, the
    # mirror of --claim) grew by 229 B. Budget unchanged; comfortably under it.
    "skills/manager/phases/handback.md": (
        # #1103: on UNVALIDATABLE, compare the report's optional plugin_root
        # against the sub-manager's own current ${CLAUDE_PLUGIN_ROOT} and
        # attribute a difference to a mid-tick plugin update. 16347 became
        # 17116, then 17249 after self-review softened "a difference means"
        # to "a real difference is evidence" and named trivial spelling
        # differences (case, trailing separator, slash vs backslash) to
        # ignore first. Ceiling unchanged.
        # #1499: read the report's optional `cost` block -- over_threshold
        # is a trap.d finding, a non-measured state is carried into the
        # handback, an absent key is a compliance question. 17249 became
        # 17922. Ceiling unchanged, 78 B of headroom left.
        # #1532: 17922 B became 17924 B -- the release call now names the
        # assignee it releases rather than "the lane record AND the
        # assignee". Ceiling unchanged, 76 B of headroom left.
        # Raised for #1656: 17924 B became 18944 B, past the 18000 B ceiling
        # by 944 B. A report naming `superseded_by_pr` -- a lane's decline
        # made actionable rather than ending in prose -- needs its own
        # paragraph: release the issue as normal, then fold the named pull
        # request into this tick's own review set so it gets a real review
        # pass instead of aging unseen forever. Nothing already here argued
        # a weaker case for its size, so nothing was cut to make room;
        # ceiling moved to 20900 B, ~10% headroom over the new size.
        # Re-baselined in the same lane's own self-review round: 18944 B
        # became 19297 B -- a reviewer found the new paragraph never named
        # its own residual limit (a superseding pull request no lane ever
        # named is not caught here either), unlike the sibling paragraph
        # right above it, which does name that limit for a closed-elsewhere
        # pull request. Ceiling unchanged; ~8% headroom remains.
        19297,
        20900,
        "a lane reported back: reading the report, pushing, opening the pull request",
    ),
    # Raised (#960): measured 13,992 B against the prior 12,800 B budget -- the
    # spine's cross-platform band moved in, being what a reviewer audits a diff
    # against rather than something every tick needs loaded.
    "skills/manager/phases/review.md": (
        # Re-baselined for #1047: 10353 B became 10829 B. A new bullet on
        # the maintainer's own closed checklist -- checking
        # scripts/fix_commit_scope.py against a fix-for-a-finding commit
        # the report is silent about -- names the maintainer-side backstop
        # for the same gap agents/developer/review-return.md's own new
        # section closes on the developer side. Ceiling unchanged;
        # comfortably under it.
        # Re-baselined for #1275's self-review round: 10829 B became
        # 11390 B. A self-review round found the three-receipts list still
        # defaulted a non-blocking finding to a new issue, so the receipt
        # list gained a fourth entry (a trap.d/ fragment) and a rank-first
        # instruction. Ceiling unchanged; comfortably under it.
        # Re-baselined for #1682: 11390 B became 11869 B. The filing
        # instruction attached `labels.filed_by_loop` alone -- a loop-filed
        # blocking finding landed with no lane and no priority, invisible to
        # dispatch until the next triage sweep, which cannot run while the
        # finding it carries blocks a release. Now derives priority from
        # `labels.priority`'s first entry and lane from `labels.lane_other`
        # (this repo declares no `labels.lane_patterns` to derive one from
        # the finding's own files). Ceiling moves to 12000, ~1.1% headroom.
        11869,
        12000,
        "reviewing a returned diff, and what an issue body filed out of one looks like, when a fix-for-a-finding needs its own pass",
    ),
    # Raised for #1374: 12570 B on disk against the prior 12400 B ceiling, a
    # 170 B overage. The new `overexposes` row and its accompanying paragraph
    # answer the `Blocks a release?` column with a stated condition rather
    # than a bare yes/no -- a v0.59.0 claude-supertool release audit found a
    # secret written wide then narrowed a line later, and none of the eleven
    # existing rows fit an instance whose blocking verdict genuinely depends
    # on whether the file outlives the writing process or the host is
    # shared. Nothing already in the file argued that point, so nothing was
    # cut to make room; ceiling moved to 13800 B, ~10% headroom over the new
    # size, the same terms as every other re-baseline in this table.
    # Re-baselined for #1374's own self-review round: 12570 B became 13093 B --
    # the embargo column for `overexposes` was made conditional too (matching
    # the blocking column, rather than a bare "yes"), after an auditor spawn
    # found the bare "yes" broke tests/test_embargo_routing.py's invariant
    # that embargo is a subset of blocking; plus a precision sentence
    # distinguishing this row from ships-local-state's own disagreement.
    # Ceiling unchanged; still comfortably under the 13800 B budget.
    #
    # Raised for #1705: 13093 B became 14195 B, past the old 13800 B ceiling.
    # The dependency-filing section named the destination repository as the
    # scope for `labels.priority`/`labels.lane_other` but never for
    # `labels.filed_by_loop`, unlike the same-repo instructions in
    # SKILL.md/review.md/accounting.md -- confirmed four for four (#1679,
    # #1681, #1682, #1683) landing on their destination board correctly
    # labelled except for that one. The new paragraph states the label comes
    # from the *destination*'s own declaration, never the filing session's
    # own `.oss.json`, and names the existing `_infer_filed_by_loop_label`
    # matching convention and `gh-labels:repo:OWNER/NAME` as the route to it
    # rather than inventing a new mechanism. Nothing already in this section
    # argued a weaker case for its size, so the ceiling moves with it.
    "skills/manager/phases/findings.md": (
        14195,
        14400,
        "ranking a finding: the twelve classes, the blocking and embargo columns, routing by row (#1275) including a conditional row (#1374), and filing on a dependency's own board -- and, since #1705, which repository's own label declarations govern that filing",
    ),
    # Raised for #1275: 9326 B became 11222 B, past the old 10300 B ceiling by
    # 922 B. The new "Routing a finding" section states where a ranked finding
    # goes once it is ranked -- filed as an issue for a blocking or unranked
    # row, a trap.d/ fragment for everything else -- closing the gap #1275
    # named: 21 of 30 open issues carried filed-by-loop, because nothing
    # routed a non-blocking finding anywhere but the tracker. Ceiling moved to
    # 12400 B, ~10% headroom over the new size, rather than trimming anything.
    # Re-baselined for #1029: 14455 B on disk against a stale 13198 declared
    # baseline -- #1026 grew this file (#976's push-to-main rule, #1017's
    # worktree-reap fix) without touching this table. Budget unchanged; the
    # file is still under it, though only by 45 B (worth a fresh headroom
    # raise the next time this file grows, out of scope here).
    # Raised for #1085/#1056: 16671 B on disk against the prior 14500 B
    # ceiling, which #1029's own note already flagged as due. Two additions,
    # not one: #1085's merge policy (green and mergeable means merge, no
    # pre-merge rebase absent a real reason) and #1056's fix to the #1007
    # worktree HEAD-comparison guard, whose git-worktrees-first fallback
    # could never fire because that op never emits a commit SHA. Neither
    # paragraph could be cut to make room for the other -- one is a new
    # policy, the other closes a data-loss guard that was silently off --
    # so the ceiling moved with ~10% headroom over the new size rather than
    # trimming either down.
    # Re-baselined for #1085/#1056's own self-review round: 16671 B became
    # 17234 B after fixing a wrong issue citation (the rerun rule "just
    # below" is #389's, not #1004's -- #1004 is an unrelated release-marker
    # edit) and a hardcoded, repo-specific CI fact (the new policy bullet
    # named this repo's own tests.yml trigger shape as though it held for
    # every managed repo; now stated as a per-repo fact to check, with the
    # repo's own file named as one instance rather than a name to expect
    # elsewhere) surfaced by self-review. Budget unchanged.
    # Re-baselined for #1091's CI leg: the literal substring "merging on
    # green" in the #1085 policy bullet collided with test_command_
    # references.py's ACTS_THE_LOOP_TAKES boundary check (a phase file is
    # concatenated after SKILL.md's own stop-boundary marker, and that
    # enumerated act may not appear on that side). Reworded to "a green
    # merge"; 17234 B became 17250 B. Budget unchanged.
    # Re-baselined for #1162: 13985 B became 14230 B -- one paragraph pointing
    # the "fully green" bullet at ci-green.md's own subject rather than
    # restating it. Budget unchanged; comfortably under it.
    # Re-baselined for #1394: 14230 B became 14621 B -- the never-auto-merge
    # line now points an external-contributor PR at phases/inbound.md's own
    # classification instead of leaving it as a dead-end sentence. Budget
    # unchanged; comfortably under it.
    # Re-baselined for #1394's own maintainer review: 14621 B became 14776 B
    # -- the same ready-to-merge -> green-and-mergeable rename, plus one
    # sentence stating why the old name was a verdict. Budget unchanged.
    "skills/manager/phases/merge.md": (
        # Re-baselined for #1532: 14776 B became 14715 B -- the post-merge
        # release bullet no longer describes the lane record's TTL or the
        # prune that used to clear it for you; there is no longer any
        # mechanism that does, which the bullet now says outright.
        # Re-baselined for #1467: 14715 B became 15385 B -- a curate-authored
        # pull request (head branch matching `^curate/`) joins the
        # never-auto-merge list, with a paragraph saying why it needs its own
        # marker: it is authored by the same account as every other loop PR,
        # so `author_association` cannot tell it apart the way an external
        # contributor's PR is told apart. Ceiling unchanged; 15 B headroom.
        # Re-baselined for #1571: 15385 B became 16285 B, ceiling 15400 -> 16400
        # B. Gate 3's round-one audit of the v0.36.0 delta found this file
        # stating two gates -- external-contributor, and a `^curate/` head
        # branch -- as rules with no read attached, which was free while merging
        # lived inside `oss:sub-manager` (it already held a board read carrying
        # both) and stopped being free the moment #1544 split merging into a
        # spawn handed a bare pull request number. The addition names the two
        # reads and points at `inbound_triage.classify_pr` rather than
        # re-translating GitHub's association vocabulary a second time. Weighed
        # against cutting: the #1467 curate paragraph below it is the incident
        # that put the `^curate/` gate here at all, and the #1394 paragraph
        # under that is the one an external-contributor PR is held by -- cutting
        # either to pay for a read they both depend on trades the rule for the
        # measurement instead of having both.
        # Re-baselined for #1602: 16380 B became 15596 B. The `^curate/`
        # never-auto-merge row and its #1467 rationale paragraph come off --
        # a curate-authored pull request now merges on green like any other,
        # per the maintainer decision that the gate produced a pull request
        # neither merged nor read. Only one gate (external-contributor) is
        # still a fact to read rather than recall, so the "two of those
        # gates" sentence now says one. Ceiling unchanged; comfortably under
        # it.
        # Re-baselined for #1724: 15596 B became 16082 B -- a denied merge
        # now names SKILL.md's canonical classifier-denial rule instead of
        # only "do not route around it", and the command-string framing a
        # sub-manager misread as retry license now says explicitly that it
        # is not. Ceiling unchanged; comfortably under it.
        16082,
        16400,
        "merging: the gates, the call itself, and what is still owed after green",
    ),
    # New for #1162: the pr_green.py wait and its #1086 substring trap used to
    # live only in agents/sub-manager.md, so a releaser landing gate 3's own
    # blocking fix had no instruction and no trap for the exact failure #1086
    # already paid for. Shared here rather than copied into agents/releaser.md
    # too, per CLAUDE.md's rule against a fact that lives in two places. ~10%
    # headroom over the measured 2454 B, same terms as every other row.
    "skills/manager/phases/ci-green.md": (
        # Re-baselined for #1190's own self-review round: 2454 B became
        # 2646 B -- a one-sentence pointer noting a sub-manager's own
        # WAIT-OBSERVABLE additionally folds in fleet occupancy, since a
        # releaser has no fleet to report on. Budget unchanged.
        # Raised for #1458: 2646 B became 2761 B, past the 2700 B ceiling
        # by 61 B. The new sentence states that a leg a later run of the
        # same check name superseded is excluded from `red`, matching
        # `gh-pr:N:status` (pr_green.py disagreed with it before this fix).
        # Nothing already in the file argued that point, so nothing was
        # cut to make room; ceiling moved to 3050 B, ~10% headroom over
        # the new size.
        # Re-baselined for #1554: 2761 B became 2988 B -- the shown
        # canonical `pr_green.py` call example now carries `--timeout N`,
        # reconciling it with `agents/sub-manager.md`'s own call shape,
        # which the two loop documents previously disagreed about.
        # Comfortably under the 3050 B ceiling; ceiling unchanged.
        2988,
        3050,
        "the pr_green.py wait, its four states, and the #1086 substring trap -- shared by a sub-manager merging and a releaser landing gate 3's own fix",
    ),
    # New for #1394: the loop had no owner anywhere for work that arrives from
    # outside -- an issue nobody filed on our behalf, an external pull
    # request, or a comment. This file classifies each into a closed set of
    # outcomes (six refusal reasons, four PR states, answered/needs-answer)
    # and states the boundary explicitly: it surfaces, #1395's queue acts.
    # ~10% headroom over the measured 6262 B, same terms as every other row.
    # Re-baselined for #1394's own maintainer review: 6262 B became 6533 B --
    # `ready-to-merge` renamed to `green-and-mergeable` (a returned string
    # that names the one act merge.md forbids absolutely is a verdict, not a
    # measurement). Budget unchanged; comfortably under it.
    # Re-baselined for #1436: 6533 B became 6799 B. The "What this buys the
    # statusline" section still said the unruled-issue/unreviewed-pull-
    # request count was "left for a lane that can measure it" -- but
    # `statusline.inbound_reading`/`_inbound_field` already exist (#1406,
    # landed in the same delta this stale sentence survived). Rewritten to
    # name what actually measures it now. Budget unchanged; still under it.
    "skills/manager/phases/inbound.md": (
        6799,
        6900,
        "classifying what arrived from outside: refusing an issue with a stated reason, an external pull request's readiness, and an unanswered comment -- never performing the act itself (#1394)",
    ),
    # Re-baselined for #1014: 10381 B on disk against a stale 10195 declared
    # baseline. Budget unchanged; comfortably under it either way.
    # Re-baselined for #1043: 10381 B became 11037 B -- gate 3's disposition
    # (round + verdict + blocking -> proceed/stop-tag/carry-forward) is now
    # computed by scripts/gate3_disposition.py rather than re-derived from
    # prose each release, after a releaser misread the round-two
    # carry-forward rule as applying to round one and shipped over a
    # round-one findings verdict. Budget unchanged; still under it.
    # Re-baselined for #1158: 8930 B became 9170 B -- has_blocking gained a
    # third state (BLOCKING_UNKNOWN / None -> could-not-decide) alongside
    # True/False, so gate3_disposition.py's own paragraph here now names it.
    # Budget unchanged; still comfortably under it.
    # Re-baselined for #1077: 9170 B became 9425 B -- gate 5's version-site
    # sweep gained one sentence naming CLAUDE.md's own currency marker as a
    # step the sweep does not catch, pointing at commands/release.md's own
    # gate 4 for the mechanics. Budget unchanged; still under it.
    # Re-baselined for #1246: 9425 B became 9685 B -- gate 1 gained a pointer
    # sentence naming that a push-triggered run alone does not satisfy it in a
    # repo whose own CI runs a reduced push matrix, with the mechanics left in
    # commands/release.md's own gate 1 (the single source, per #321's rule
    # for gate 3). Budget unchanged; still under it.
    # Raised for #1266 (landed independently, same file): 9425 B became
    # 9918 B, past the 9800 B ceiling by 118 B. `v0.27.0` was tagged and
    # published before its own release commit's CI run had even started, and
    # that run concluded RED -- gates 1-6 verify the default branch before
    # the commit is written, and nothing verified the commit's own content.
    # The new paragraph names this as a seventh, unnumbered check and points
    # at commands/release.md for the mechanics, the same pointer shape gate 3
    # already uses. Too small an overage to be worth trimming something else
    # in the same file to absorb, so the ceiling moved to 10900 B, ~10%
    # headroom over the new size, rather than cutting anything.
    # Re-baselined in the same lane's own self-review round: 9918 B became
    # 10035 B -- two reviewer findings fixed in place (the exit-code list
    # undercounted release_ci_wait.py's four outcomes at three, and the new
    # paragraph was ordered after the tag-push verification it is actually a
    # precondition for). Comfortably under the 10900 B ceiling; unchanged.
    # Re-measured after merging #1246 and #1266 together (both landed the
    # same tick, each adding independent prose to this file): 10035 B became
    # 10295 B. Ceiling unchanged at 10900 B; still comfortably under it.
    # Raised (#1681): gate 2's one-line "Nothing in flight is mid-review" now
    # names scripts/release_gate2.py -- a three-state clear/blocked-by:N/
    # could-not-tell call, mirroring gate3_disposition.py -- after two
    # releaser runs on the same open PR reached opposite gate-2 verdicts four
    # hours apart with nothing about the PR itself changed. 10295 B became
    # 11212 B; ceiling moves to 12300 B, ~10% headroom.
    "skills/manager/phases/release.md": (
        11212,
        12300,
        "cutting a release: the six gates and what the tag does and does not deliver",
    ),
    # Raised (#960): measured 22,237 B against the prior 16,600 B budget. Two
    # relocations, both about closing a tick: the cadence section, and the loop
    # doctrine's argument (the #209 incident and the #337/#477/#565 state-file
    # mechanics), whose directives stay in the spine. A separate phase file for
    # the second was weighed and declined -- "when does the loop stop" and "how
    # does this tick close" are one subject, and a seventh phase file would add
    # its own spine directive block and header, which is the duplication cost
    # the split already pays once per file.
    # Re-baselined for #1014: 22741 B on disk against a stale 22237 declared
    # baseline. Budget unchanged; comfortably under it either way.
    # Re-baselined for #1037: 22779 B on disk against a stale 22741 declared
    # baseline -- the two step-1 pointer updates landed in this file. Budget
    # unchanged; comfortably under it.
    # Re-baselined for #1069: 22779 B became 22789 B -- two dispatch_rank.py
    # mentions renamed to select_issues_rank.py in the same call-site rewrite.
    # Budget unchanged; comfortably under it.
    "skills/manager/phases/accounting.md": (
        # Re-baselined for #1083: 17705 B became 18549 B -- the
        # `filed_by_loop` attach directive now turns on provenance (the
        # loop's own initiative) rather than on which call site typed the
        # issue up, so a co-decided issue is never tagged even when the loop
        # files it. Budget unchanged; comfortably under it.
        # Raised for #1122: 18549 B became 20894 B, past the 19500 B ceiling
        # by 1394 B. The new paragraph states which cohort's count the
        # release-commit marker may cite -- the previous release's, already
        # fully frozen, never the current release's own not-yet-frozen one --
        # closing the gap where v0.25.0's marker cited cohort-21's count
        # inside the commit written before cohort-21's own freeze ran, and
        # the two numbers (30 cited, 32 applied) disagreed. Nothing already
        # in the file argued that point, so nothing was cut to make room;
        # ceiling moved to 23000 B, ~10% headroom over the new size.
        # Re-baselined in the same lane's self-review round: 20894 B became
        # 21569 B after a reviewer spawn found the new rule left "settled
        # count" ambiguous between the recorded freeze decision and a fresh
        # recount -- fixed by naming the recorded `froze <cohort> at N`
        # decision as the one to quote. Comfortably under the 23000 B
        # ceiling; ceiling unchanged.
        # Re-baselined for #1220: 21569 B became 22430 B, across four CI-driven
        # rounds -- 22110 B, +296 B fixing a wording inconsistency between this
        # file and commands/release.md over what `--at` takes, +22 B prefixing
        # the bare scripts/cohort_citation_order.py path with
        # ${CLAUDE_PLUGIN_ROOT}/ (test_script_path_resolution_647.py, 12/18
        # legs red), +2 B quoting that same reference
        # ("${CLAUDE_PLUGIN_ROOT}/...") so a plugin root containing a space
        # does not word-split (test_phase_files_plugin_root_quoting_751.py) --
        # a pointer to the new mechanical ordering check,
        # scripts/cohort_citation_order.py. Comfortably under the 23000 B
        # ceiling; ceiling unchanged.
        # Re-baselined for #1264: 22430 B became 22700 B -- one sentence naming
        # the new `declined` citation state cohort_citation_order.py gained,
        # so this paragraph does not go stale the moment a release marker
        # legitimately declines to cite a cohort. Comfortably under the
        # 23000 B ceiling; ceiling unchanged.
        # Re-baselined for #1303: 22700 B became 22987 B -- one sentence in
        # Cadence naming the #1155 threshold route now activated for
        # curate_route_threshold. Comfortably under the 23000 B ceiling;
        # ceiling unchanged.
        # Raised for #1386: 22987 B became 23564 B, past the 23000 B ceiling
        # by 564 B. The Cadence section's own triage paragraph used to state
        # that the last-triaged read is enforced but nothing consumes it --
        # true when written, and the gap #1386 closes: a sub-manager cannot
        # act on the reading itself (it dies with its own context at the end
        # of its tick and cannot count ticks or releases across spawns), so
        # scripts/triage_trigger.py is read by the scheduler instead, at the
        # `RELEASE: released` handback in commands/tick.md. The paragraph now
        # points there rather than restating a second copy of when the
        # trigger fires. Nothing already in the file argued that point, so
        # nothing was cut to make room; ceiling moved to 25900 B, ~10%
        # headroom over the new size.
        # Re-baselined for #1410: 23564 B became 25243 B -- the cohort freeze
        # is now a script the release runs (scripts/cohort_freeze_record.py),
        # not a maintainer's hand; this section states the new call and its
        # three states in place of the old by-hand instruction and the manual
        # oss_state.py two-route CLI example. Comfortably under the 25900 B
        # ceiling; ceiling unchanged.
        # Re-baselined for #1515: 25243 B became 25651 B -- the could-not-
        # freeze hand-remedy paragraph was replaced (cohort_freeze.py now
        # creates the missing label itself under --execute), and a self-
        # review finding fixed a second, stale "maintainer's own act, by
        # hand" sentence in the Cadence section. Comfortably under the
        # 25900 B ceiling; ceiling unchanged.
        # Re-baselined for #1682: 25651 B became 25792 B -- the numerator
        # paragraph now names `labels.priority`/`labels.lane_other` beside
        # `labels.filed_by_loop`. Comfortably under the 25900 B ceiling;
        # ceiling unchanged.
        # Re-baselined for #1707: 25792 B became 25892 B -- the same
        # paragraph now states the omit-if-missing rule for those two keys,
        # matching review.md. 8 B of headroom left under the 25900 B
        # ceiling; the next edit to this file pays for itself or raises the
        # ceiling.
        25892,
        25900,
        "closing a tick: the cohort freeze, the intake ratio, and what a tick costs to carry",
    ),
    # New for #1037: `commands/tick.md` used to inject its own numbered steps 1-6
    # plus "What ends a tick" into the scheduler's context on every tick, though
    # only a sub-manager's own context ever executes them -- the same shape #695
    # already measured and split for the manager skill, one file over. Moved
    # here wholesale (39119 B), no content dropped; ~10% headroom over the
    # measured size, same terms as every other row.
    # Re-baselined for #1069: 39329 B became 39490 B -- the dispatch_rank.py/
    # preflight_check.py/issue_claim.py/fleet_label.py call sites rewritten
    # for select_issues.py/lane_setup.py's own two-entry-point shape. Budget
    # unchanged; comfortably under it.
    # Re-baselined again (maintainer review): 39490 B became 39460 B -- the
    # --label worked example moved from named flags to positional arguments.
    # Budget unchanged.
    "skills/manager/phases/tick-order.md": (
        # Re-baselined for #1178: 33032 B became 33334 B -- the same
        # `--board`-vs-default-mode stdin clarification dispatch.md gained,
        # stated at this file's own call site. Budget unchanged;
        # comfortably under it.
        # Re-baselined again in the same lane's own self-review round:
        # 33334 B became 33532 B -- the same wrong-shaped-payload
        # correction dispatch.md's own re-baseline note describes.
        # Re-baselined for #1200: 33532 B became 33371 B -- the identical
        # stdin-contract removal dispatch.md's own re-baseline note
        # describes. Budget unchanged.
        # Re-baselined again in the same lane's own self-review round:
        # 33371 B became 33396 B -- a reviewer found "the two shared no
        # input contract" read as the opposite of what #1178 found (the
        # two modes did NOT share one); reworded for clarity. Budget
        # unchanged.
        # Re-baselined for #1137: 33396 B became 34266 B -- a new paragraph
        # documenting the classifier's own retry convention for
        # oss_state.py/agent_role.py calls, and agent_role.py's own CLI now
        # names a real disk-write/unlink failure rather than folding it into
        # "not a git repository". Budget unchanged; comfortably under it.
        # Re-baselined for #1394: 34266 B became 34816 B -- step 3 gained a
        # paragraph pointing at the new phases/inbound.md file, since inbound
        # work outranks the loop's own findings the same way an unmerged PR
        # or a red default branch already does. Budget unchanged.
        # Re-baselined for #1409: 34816 B became 34905 B -- the short-lane
        # reason list gained a fifth word, declined-for-cause (#1407).
        # Budget unchanged; comfortably under it.
        # Re-baselined for #1508: 34905 B became 35539 B -- step 2's heal now
        # arms the default-branch poller filtered (only=went_green,went_failed)
        # before the bare radar, and the "no poller to heal" prose that
        # predated supertool #2024 is corrected. Budget unchanged; 461 B left.
        # Re-baselined for #1532: 35539 B became 35308 B -- the registry
        # paragraph and the `--claim` requires `--lane` rule went with the
        # registry, and step 3 no longer claims to derive a held set.
        # Re-baselined for #1579: 35308 B became 35268 B -- the --claim call
        # dropped --lane, which only ever fed the claim receipt's own unread
        # [lane] block. Ceiling unchanged.
        # Re-baselined for #1555 (self-review, Explore reviewer): 35268 B
        # became 35480 B -- the step 2 paragraph still described a
        # `lane-collision` check `select_issues_overlap.py`/
        # `select_issues_companions.py` no longer perform, retired by
        # #1528/#1530. Ceiling unchanged.
        # Re-baselined for #1724: 35480 B became 35518 B -- the
        # classifier-denial paragraph now points at SKILL.md's single
        # canonical rule instead of restating it, net larger by one short
        # pointer sentence. Ceiling unchanged; comfortably under it.
        35518,
        36000,
        "a sub-manager's own order of operations: steps 1 through 6 of a tick, and what ends one",
    ),
}


def _spine_text(root):
    """The spine's text, or ``None`` when it could not be read.

    ``None`` rather than ``""`` on purpose: an empty string references
    nothing, which is indistinguishable from a spine that names no phase
    files -- and the caller has to be able to tell "the spine does not name
    it" from "nobody could ask".
    """
    try:
        return (root / SPINE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check():
    """One row per declared document.

    ``state``: ``ok`` | ``over`` | ``missing``.
    ``referenced``: ``True`` | ``False`` | ``None`` (the spine was unreadable,
    so the question went unasked -- never rendered as referenced).
    """
    root = repo_root()
    spine = _spine_text(root)
    rows = []
    for rel, (baseline, budget, governs) in DOCUMENTS.items():
        path = root.joinpath(*rel.split("/"))
        if rel == SPINE:
            referenced = True
        elif spine is None:
            referenced = None
        else:
            referenced = rel in spine
        try:
            size = len(path.read_bytes())
        except FileNotFoundError:
            rows.append(
                {
                    "path": rel,
                    "state": "missing",
                    "size": None,
                    "budget": budget,
                    "baseline": baseline,
                    "governs": governs,
                    "referenced": referenced,
                }
            )
            continue
        rows.append(
            {
                "path": rel,
                "state": "over" if size > budget else "ok",
                "size": size,
                "budget": budget,
                "baseline": baseline,
                "governs": governs,
                "referenced": referenced,
            }
        )
    rows.extend(_undeclared_rows(root))
    return rows


def _undeclared_rows(root):
    """A row per phase file on disk that `DOCUMENTS` does not declare.

    `state` is `undeclared`: it is on disk, so it is not `missing`, and it has
    no budget to be `over`. `referenced` is still answered, because a phase
    file the spine names and nobody budgeted and one nothing names at all are
    different problems.

    A tree with no phases directory contributes nothing rather than raising:
    that is the `missing` rows' answer to give, and giving it twice would say
    the same absence in two vocabularies. An *unreadable* phases directory
    (#571) is different from a missing one and is reported as its own row --
    `state: unreadable` -- rather than silently folded into "no undeclared
    files found", which is what an empty `on_disk` would otherwise look like.
    """
    try:
        on_disk, unreadable = documents(root)
        on_disk = on_disk[1:]
    except RuntimeError:
        # `documents()` raises this when `spine.is_file()` says the spine
        # is not a file -- the ordinary case is a genuinely absent spine,
        # already reported by that document's own `missing` row in
        # `check()`'s main loop. `is_file()` also folds a stat failure
        # (e.g. `PermissionError` on a parent directory) into the same
        # `False`, and `check()`'s own spine `read_bytes()` call only
        # catches `FileNotFoundError` -- so that narrower case reaches
        # here after `check()` has already raised uncaught, rather than
        # after a `missing` row was emitted. Out of scope for #589: it
        # predates this fix and is not the fold this issue is about.
        return []
    except OSError as exc:
        # `documents()` itself could not be asked, rather than answering
        # with an `unreadable` message in its own return value (#571's own
        # shape, handled below) -- this must still surface as `unreadable`,
        # not fold into "no undeclared files found" (#589).
        return [
            {
                "path": "skills/manager/phases",
                "state": "unreadable",
                "size": None,
                "budget": None,
                "baseline": None,
                "governs": None,
                "referenced": None,
                "detail": str(exc),
            }
        ]
    rows = []
    for message in unreadable:
        rows.append(
            {
                "path": "skills/manager/phases",
                "state": "unreadable",
                "size": None,
                "budget": None,
                "baseline": None,
                "governs": None,
                "referenced": None,
                "detail": message,
            }
        )
    for path in on_disk:
        rel = path.relative_to(root).as_posix()
        if rel in DOCUMENTS:
            continue
        try:
            size = len(path.read_bytes())
        except FileNotFoundError:
            # Listed a moment ago, gone now: a sibling process's own
            # transient control file (#1250) or anything else that vanished
            # in the window between the `iterdir()` above and this read --
            # `test_skill_phase_split.py`'s own real-root create-then-delete
            # control files raced exactly this window against a concurrent
            # xdist worker's `check()` call and reddened CI with this same
            # `FileNotFoundError` (#1293). Reporting on a file that is
            # already gone is neither `undeclared` (this scan cannot show it
            # exists) nor `missing` (nothing declared it, so nothing is
            # unmet) -- there is nothing left to say about it this pass, and
            # the very next call answers correctly for whatever is actually
            # still on disk.
            continue
        spine = _spine_text(root)
        rows.append(
            {
                "path": rel,
                "state": "undeclared",
                "size": size,
                "budget": None,
                "baseline": None,
                "governs": None,
                "referenced": None if spine is None else rel in spine,
            }
        )
    return rows


if __name__ == "__main__":
    import json

    print(json.dumps(check(), indent=2))
