"""Per-command-file size budget (#940).

`agent_budgets.py` covers `agents/*.md`, `skill_phases.py` covers
`skills/manager/**`; `commands/*.md` was outside both, and grew unbudgeted
to the point of provable harm rather than just theoretical cost --
`commands/tick.md` doubled from 24,322 B (#583, 2026-08-31) to past 47,000 B
and, measured directly on this repository's own transcripts (#940's own
trap.d fragment), a sub-manager reading it with a bare `cat` gets back a
truncated preview rather than the file, then pays again to read it in
`sed -n` chunks -- ~11.9k tokens of pure duplication, held in context for
every remaining turn of the tick because the floor is re-sent on every one.

Same shape as `agent_budgets.py` deliberately, and its own module docstring
carries the fuller argument (turn-1 context, bytes x turns, why a script
cannot judge whether a paragraph earns its size) rather than repeating it
here -- it applies to `commands/*.md` with the same force, since every tick
reads whichever of these files it names.

Budget = the size measured when the budget was set, plus ~10% headroom,
same replace-don't-append terms as the other two tables: raise the number
in the same diff as a justified addition, with a sentence saying what was
weighed, or replace something to pay for it. Lowering a budget while a file
sits under it is always fine.
"""

from __future__ import annotations

from pathlib import Path

# repo-relative path (POSIX, matched by name against commands/*.md on disk) ->
# (bytes measured when the budget was set, budget bytes incl. ~10% headroom)
BUDGETS: dict[str, tuple[int, int]] = {
    # #940: 48,465 B measured the moment this table was added -- past #583's
    # 24,322 B reading and past the point a bare `cat` truncates for this
    # harness, confirmed directly rather than only cited (see the note now
    # at the top of the file itself). The budget is not raised to make room
    # for further growth; it is set at today's size so growth from here is
    # visible, the same posture #491 already takes for agents/*.md.
    "commands/tick.md": (48465, 53300),
}


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"command_budgets: no .git found walking up from {here}")


def check() -> list[dict]:
    """One result per budgeted path -- 'ok', 'over' or 'missing'.

    'missing' is a third state on purpose, the same reason `agent_budgets.
    check` carries one: a budgeted file that is not on disk is not "under
    budget", it is a fact nobody chose, and answering 'ok' for it would be
    the absence-read-as-clean this repo is named after.
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
