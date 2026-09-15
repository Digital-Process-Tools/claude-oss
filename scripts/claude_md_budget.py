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
    "CLAUDE.md": (32621, 35900),
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
