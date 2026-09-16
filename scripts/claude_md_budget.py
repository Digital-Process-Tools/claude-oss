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
    "CLAUDE.md": (44280, 44300),
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
