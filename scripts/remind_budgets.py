"""Size budgets for jit-context `remind`-mode bodies (#1584 part two).

A `remind` rule is delivered on every match, never deduped, because jit's dedup key is
`session_id` and a spawned agent inherits its parent's -- so a rule that must reach a
subagent has to be `remind`, and then pays its full body on every match for the life of
every agent that trips it. #1584 measured this against one machine's logged history:
18 `remind` rules averaging 2,639 B each, against 3 `block` rules averaging 1,556 B --
the corpus is inverted against its own economics, since the mode that fires most often is
also the one carrying the largest bodies.

`.claude/jit-context/paths/00-manual/md-is-a-manual-not-a-rationale.md` already states the
rule ("the measurement that justified a constant belongs beside the constant; the incident
belongs in its own issue") but its own `match:` did not cover `.claude/jit-context/**`
before #1584 extended it -- the rule about not paying for narrative on every turn had never
applied to the corpus re-sent most. This module is the missing budget, same shape as
`agent_budgets.py` / `skill_phases.py` / `command_budgets.py` / `claude_md_budget.py`
deliberately, so `tests/test_baseline_matches_disk_1014.py`'s existing drift comparison
folds this in with the same three lines the other four already use.

Only the five bodies #1584 shrank in its own pass are budgeted here. A `remind` body added
later, or one of the remaining large siblings recon found outside this five
(`a-write-outside-supertool-meets-no-validator.md`, `release-publish-execute-denied.md`,
`stacked-pr-cleanup-recovery.md`, `sub-manager-hand-polls-ci.md`), is not yet covered --
left for a follow-up sweep rather than guessed at here, since #1584's own body says explicitly
that a lane picking this up should decide deliberately whether to widen the sweep, not narrow
its own review scope by assumption.
"""

from __future__ import annotations

from pathlib import Path

# repo-relative path -> (bytes measured when the budget was set, budget bytes incl.
# ~10% headroom), same convention as agent_budgets.BUDGETS.
BUDGETS: dict[str, tuple[int, int]] = {
    # Shrunk for #1584: 2205 B became 771 B -- two incident narratives (#1532, #1530)
    # compressed to one directive sentence each plus the citation, the clean case #1584's
    # own body used as the worked example.
    ".claude/jit-context/tools/00-manual/exit-sensitive-pipe-to-head-tail.md": (
        771,
        900,
    ),
    # Shrunk for #1584: 7652 B became 3248 B -- nine distinct sub-rules, each compressed
    # to a directive-plus-citation bullet, incident narrative left in its own issue number.
    # This was the single largest remind body in the corpus (36% of all jit injection per
    # #1584's own measurement) and the one worth the most per byte cut.
    ".claude/jit-context/tools/00-manual/ci-evidence-is-about-one-commit.md": (
        3248,
        3600,
    ),
    # Shrunk for #1584: 4167 B became 2586 B -- six sub-rules compressed the same way.
    ".claude/jit-context/tools/00-manual/waiting-on-a-status-line.md": (2586, 2850),
    # Shrunk for #1584: 2528 B became 1705 B.
    ".claude/jit-context/tools/00-manual/refused-bash-call-is-all-or-nothing.md": (
        1705,
        1900,
    ),
    # Shrunk for #1584: 3009 B became 2128 B.
    ".claude/jit-context/tools/00-manual/supertool-payload-forms.md": (2128, 2350),
    # Shrunk for #1584: 2815 B became 2079 B.
    ".claude/jit-context/tools/01-oss/tree-snapshot-compare.md": (2079, 2300),
}


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"remind_budgets: no .git found walking up from {here}")


def check() -> list[dict]:
    """One result per budgeted path -- 'ok', 'over' or 'missing'.

    'missing' is a third state on purpose, same reasoning as the other budget
    modules: a budgeted file that is not on disk is not "under budget", it is a
    fact nobody chose, and answering 'ok' for it would be exactly the
    absence-read-as-clean defect this repo is named after.
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
