"""CLAUDE.md's own size budget (#1556).

`CLAUDE.md` is loaded whole on every session of every agent in the loop --
scheduler, sub-manager, releaser, every developer lane -- and #1556 found it
had none of its own: `scripts/agent_budgets.py` covers `agents/*.md`,
`scripts/skill_phases.py` covers `skills/manager/**`,
`scripts/command_budgets.py` covers `commands/tick.md` and `commands/run.md`,
and nothing covered `CLAUDE.md` itself. `tests/test_agent_definition_budget_
491.py` says so explicitly: "`skills/manager/SKILL.md` and `CLAUDE.md` are
read by the same mechanism but are not agent definitions in that sense." At
the time #1556 was filed CLAUDE.md measured 95,439 B, 2.2x the ceiling on
`skills/manager/SKILL.md` (44,800 B) and larger than every other single
document in the loop; a same-day cut (commit cb75d5c5, citing the same
finding) brought it to 32,621 B before this module landed, well under
`skills/manager/phases/dispatch.md` (55,195 B) and several other files --
so neither claim holds against the file's current size. What #1556 asked
for and this module supplies is unchanged by that cut: a ceiling and a
test, so growth back toward the old number is visible rather than silent.

This module is the missing fourth. Same shape as the other three
deliberately -- one dict, one `check()`, one `missing`/`ok`/`over` verdict --
so `tests/test_baseline_matches_disk_1014.py`'s existing comparison (declared
baseline vs. actual bytes on disk) folds this in with the same three lines
the other four already use, rather than inventing a second mechanism.

`CLAUDE.md` is curated by hand (`CLAUDE.md`'s own "Working here" section),
and its own third editing exception already covers this case: "a change
whose subject *is* this file". A crossing here is reported the same way
every other budget crossing is -- replace, don't append, or raise the
ceiling in the same diff with a sentence saying what was weighed -- it is
not a mandate to shrink, and it does not relax the hand-curation rule.
"""

from __future__ import annotations

from pathlib import Path

# repo-relative path -> (bytes measured when the budget was set, budget
# bytes incl. ~10% headroom), same convention as agent_budgets.BUDGETS.
BUDGETS: dict[str, tuple[int, int]] = {
    # Re-baselined for #1518/#1520: 32621 B became 33419 B -- this branch's
    # own table-row updates to agents/developer.md's and dispatch.md's
    # budget-table entries (scripts/agent_budgets.py, scripts/skill_phases.py)
    # landed on top of #1556's declared baseline, which #1556 could not have
    # seen since it merged first. Budget unchanged; comfortably under the
    # 35900 B ceiling.
    #
    # Re-baselined again for #1519/#1395/#581: 33419 B became 33441 B --
    # this lane's own "ours" ownership-table row gained one entry
    # (outbound/README.md, #1395), the only change to this file in that
    # diff. Budget unchanged; comfortably under the 35900 B ceiling.
    # Re-baselined for #1567: 33441 B became 34266 B -- the dispatch.md ceiling
    # raise and its weighed sentence, under the third editing exception (a lane
    # whose own diff moves a budgeted file's row). Budget unchanged.
    # Re-baselined for #1544 step 2 and its review-return fix-up: 34266 B
    # became 34987 B -- the same third exception, across three rows this
    # diff's own agent/skill files moved (agents/sub-manager.md,
    # agents/tick-review.md, skills/manager/SKILL.md) plus their own
    # narrative sentences. Budget unchanged; comfortably under the ceiling.
    # Re-baselined for #1544 steps 3-4: 34987 B became 36705 B, past the
    # 35900 B ceiling -- two new agent-budget rows (agents/tick-merge.md,
    # agents/tick-accounting.md), sub-manager.md's own row and ceiling
    # raised again, three new Layout lines (tick-review.md was already
    # missing from that block; tick-merge.md and tick-accounting.md are
    # new), all under the third editing exception. Ceiling moves to
    # 37500 B, ~2% headroom.
    # Re-baselined for the v0.36.0 release commit's "What is not proven yet" marker
    # rewrite (the release session's own editing exception): 36705 B became
    # 37500 B, landing exactly at the existing ceiling. Ceiling unchanged --
    # no headroom left; the next marker rewrite that grows the section will
    # need to raise it.
    # Re-baselined for #1583, the third editing exception (a lane whose own
    # diff moves a budgeted file's table row): one new agent-budget row
    # (agents/lane-report.md), agents/developer.md's own row and ceiling
    # raised, and the developer phase-split table's report.md row removed,
    # all with their own weighed sentences. 37500 B became 39066 B, past the
    # ceiling with no headroom left over from the last raise. Ceiling moves
    # to 40200 B, ~3% headroom.
    # Re-baselined in the same lane's own self-review round: 39066 B became
    # 39630 B -- the lane-report.md ceiling raise and its own weighed
    # sentence, under the same third editing exception.
    # Re-baselined again in the same round: 39630 B became 39879 B --
    # the lane-report.md ceiling row and its history paragraph updated a
    # second time for the auditor-finding fix.
    # Re-baselined a third time, the mandated #1047 second-pass round:
    # 39879 B became 39999 B, the lane-report.md row/history updated once
    # more. Ceiling unchanged; 201 B headroom.
    # Re-baselined for the v0.37.0 release commit's "What is not proven yet" marker
    # rewrite (the release session's own editing exception): 39999 B became
    # 40085 B. Ceiling unchanged; 115 B headroom.
    # Re-baselined for #1586, the third editing exception: agents/developer.md's
    # own row and ceiling raised (a literal, pinned oss:recon call, #1586's own
    # subject), plus this row's own several rewrites converging on the new
    # size. 40085 B became 41489 B, past the old 40200 B ceiling. Ceiling
    # moves to 42000 B, ~1.2% headroom -- wider than the usual re-baseline
    # margin because this row is self-referential (its own digits are part
    # of what it measures) and a tight margin here means a second pull
    # request just to fix the row.
    # Re-baselined for #1600, the third editing exception: agents/sub-manager.md's,
    # agents/tick-merge.md's and agents/tick-accounting.md's own rows updated for
    # the CURATE: reporting mechanism the diff adds, plus this row's own rewrites
    # converging on the new size. 41489 B became 42787 B, past the old 42000 B
    # ceiling. Ceiling moves to 43300 B, ~1.2% headroom, the same self-referential
    # margin the #1586 note above explains.
    # Re-baselined again in the same lane's own self-review round: 42787 B became
    # 43913 B, past the 43300 B ceiling. A spawned reviewer found the tick-merge.md
    # mechanism's own citation unsupported and its read path missing; fixing it,
    # plus naming the same CURATE: fact in a second checklist in sub-manager.md a
    # reviewer found still silent about it, grew this row's own several rewrites
    # again. Ceiling moves to 44300 B, ~1% headroom, the same self-referential
    # margin as every prior raise of this row.
    # Re-baselined for #1614, the third editing exception: agents/tick-accounting.md's
    # own row and ceiling raised three times in the same lane -- once for the literal
    # oss_state.py --decision call the issue itself asked for, twice more across two
    # self-review rounds after reviewers found that call still incomplete (first the
    # --tick-cost-* group, then --lane-fill-window/--lane/--lane-window/--intake-why)
    # -- plus this row's own rewrites converging on the new size each time. 44280 B
    # became 46225 B, well past the old 44300 B ceiling. Ceiling moves to 46300 B,
    # ~0.2% headroom -- tighter than the usual self-referential margin because three
    # passes each added their own paragraph to this same section.
    # Re-baselined for #1619, the second editing exception: the token-economy
    # paragraph's 2026-09-14 reading was rewritten with a current one, re-derived
    # (not trusted) with `loop_cost_report.py` against both claude-oss and
    # claude-supertool, and the old paragraph's implied before-and-after was
    # replaced with an explicit statement that the two windows are shaped
    # differently, plus this row's own self-referential rewrite converging on
    # the final size. 46225 B became 47801 B, past the old 46300 B ceiling.
    # Ceiling moves to 47900 B, ~0.2% headroom.
    # Re-baselined for #1616, the third editing exception: ten agents/*.md rows in
    # the Agent definitions table updated (baseline only for eight, ceiling too for
    # recon.md and tick-dispatch.md, each gaining the identical one-line "## Trap"
    # trigger pointing at trap.d/README.md), plus this row's own rewrites converging
    # with #1619's own change on the merged size. 47801 B became 49347 B, past the
    # 47900 B ceiling. Ceiling moved to 49400 B, ~0.1% headroom -- the same narrow
    # self-referential margin every prior raise of this row gives.
    # Re-baselined for #1624, the third editing exception: agents/doctor.md's own
    # row and ceiling raised for the HEAD-check/commit disposition the repaired arm
    # was missing, plus this row's own rewrites converging on the new size. 49347 B
    # became 49671 B, past the 49400 B ceiling. Ceiling moves to 49750 B, ~0.15%
    # headroom -- the same narrow self-referential margin every prior raise gives.
    # Re-baselined again in the same lane's own self-review round: agents/doctor.md's
    # own row and ceiling raised a second time (a reviewer found a known `on-other`
    # HEAD state routed through the "could-not-tell" bucket, fixed in that file),
    # plus this row's own rewrites converging on the new size. 49750 B became
    # 50032 B, past the 49750 B ceiling. Ceiling moves to 50100 B, the same narrow
    # self-referential margin.
    # Re-baselined for #1629, the third editing exception: the "Command files have
    # a size budget too" section's false claim that the harness never discovers
    # commands recursively was corrected there, in commands/run.md's own dispatch
    # and release prose, and in the Layout table's picker line; commands/run.md's
    # own row and ceiling raised in scripts/command_budgets.py; this row's own
    # rewrites converged on 50670 B in isolation, from the same 49347 B base #1624
    # started from.
    # Merged: #1624 and #1629 landed from that same base in parallel lanes;
    # rebasing #1624 onto #1629's already-merged branch combines to 51783 B, past
    # the 50100 B ceiling #1624's own self-review round had set. Ceiling moves to
    # 51900 B, ~0.23% headroom -- the same narrow self-referential margin every
    # prior raise of this row gives.
    # Re-baselined at the v0.38.0 release, the release session's own first exception:
    # the "What is not proven yet" marker rewritten inside this release commit, its
    # own growth tracking the gate-3 finding count (seven distinct across two rounds
    # this time, versus five last release) rather than settling. 51783 B became
    # 54831 B across two chased-then-widened ceiling drafts; final ceiling set at
    # 55200 B, ~0.7% headroom, wide enough to absorb this comment's own bytes
    # without a third chase.
    # Re-baselined for #1622, the third editing exception: `agents/tick-review.md`'s
    # own row and ceiling raised (four times, across two review rounds), plus this row
    # and weighed sentence recording it, updated to match each time. 54831 B became
    # 57816 B, past the 55200 B ceiling. Ceiling moves to 58100 B, ~0.45% headroom.
    # Re-baselined for #1642/#1643: agent budget rows and one weighed sentence
    # updated for the mutation-receipt guard added to agents/auditor.md and
    # agents/release-auditor.md, plus agents/developer/review.md's own row for
    # its shell-variable-to-file fix. 57816 B became 58495 B, past the 58100 B
    # ceiling. Ceiling moves to 58600 B, ~0.2% headroom.
    # Re-baselined again in the same lane's self-review round: an auditor
    # finding moved all three snapshot paths from /tmp to a worktree-local
    # path, raising agents/developer/review.md's own ceiling and this row's
    # weighed sentence. 58495 B became 58794 B, past the 58600 B ceiling.
    # Ceiling moves to 59000 B, ~0.3% headroom.
    # Re-baselined for #1655: agents/lane-report.md's own row updated (a new
    # optional pr_body.closes.declines field), plus this row and weighed
    # sentence. 58286 B became 59518 B, past the 59000 B ceiling. Ceiling
    # moves to 59700 B, ~0.3% headroom.
    # Re-baselined for #1649, the third editing exception: agents/doctor.md's own
    # row and ceiling raised for the on-default branch-protection gate, plus this
    # row's own rewrites converging on the new size. 58794 B became 58939 B.
    # Ceiling unchanged; comfortably under it.
    # Re-baselined again in the same lane's own self-review round: 58939 B became
    # 59739 B, past the 59000 B ceiling. agents/doctor.md's row and ceiling raised
    # a second time (a spawned reviewer found the branch-protection instruction
    # named a function with no runnable invocation, and that a naive import of it
    # is circular), plus this row's own rewrites converging on the final size.
    # Ceiling moves to 59900 B, ~0.3% headroom -- the same narrow self-referential
    # margin every prior raise of this row gives.
    # Re-baselined a third time in a required second-pass round (fix_commit_scope.py
    # flagged the self-review fix commit itself): 59739 B became 60338 B, past the
    # 59900 B ceiling. agents/doctor.md's row and ceiling raised a third time -- an
    # auditor spawn found the on-default templates hardcoded the literal branch
    # name `main` rather than the resolved default_branch value -- plus this row's
    # own rewrites converging on the final size. Ceiling moves to 60500 B, the same
    # narrow self-referential margin.
    # Merged: fix/1655 x fix/1649 landed from the same 58794 B base in parallel
    # lanes -- #1655 raising the ceiling to 59700 B for the lane-report.md field,
    # #1649 raising it further to 60500 B across three doctor.md rounds. Merging
    # origin/main into fix/1655 combines both histories; the row is re-measured
    # against the merged CLAUDE.md rather than added by hand: 62037 B, past the
    # 60500 B ceiling. Ceiling moves to 62300 B, headroom sized to absorb this
    # paragraph's own bytes.
    # Re-baselined for #1656: 61256 B became 62041 B (a new superseded_by_pr
    # field, and its trail through three budgeted files), past the 62300 B
    # ceiling was avoided at the time by ~0.7% headroom -- see agents/
    # sub-manager.md, agents/lane-report.md and skills/manager/phases/
    # handback.md's own rows for the mechanism. Ceiling raised to 62500 B in
    # the same lane's own self-review round.
    # Merged: fix/1656 x fix/1655 (the latter already carrying the fix/1649
    # merge above). Both chains forked from the same 58286 B base; git's own
    # merge combined agents/lane-report.md's two additions without a textual
    # conflict. Re-measured against the actual merged CLAUDE.md rather than
    # added by hand: 66796 B, past both branches' own ceiling. Ceiling moves
    # to 67000 B, ~0.25% headroom, sized to absorb this paragraph's own
    # bytes.
    # Re-baselined at the v0.40.0 release, the release session's own first
    # exception: the "What is not proven yet" marker rewritten inside this
    # release commit -- a new delta range whose cross-check disagreement was
    # resolved and named, gate 3 needing only one round this time (0
    # findings, versus seven across two rounds last release), a re-derived
    # gate-1 leg count, and two new paragraphs (gate 2's parked-PR reading,
    # re-derived rather than taken on trust; the checklist-skew annotation)
    # -- plus this row's own rewrites converging on the final size.
    "CLAUDE.md": (70751, 71000),
}


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"claude_md_budget: no .git found walking up from {here}")


def check() -> list[dict]:
    """One result per budgeted path -- 'ok', 'over' or 'missing'.

    'missing' is a third state on purpose, same reasoning as
    `agent_budgets.check()`: a budgeted file that is not on disk is not
    "under budget", it is a fact nobody chose, and answering 'ok' for it
    would be exactly the absence-read-as-clean this repo is named after.
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
