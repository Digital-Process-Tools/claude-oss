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
    "agents/developer.md": (75194, 82800),
    "agents/auditor.md": (14329, 15800),
    "agents/release-auditor.md": (17857, 19700),
    "agents/triager.md": (17702, 19500),
    # Baseline raised twice, both times for the same reason: a review
    # finding was a correctness fix with nothing safe to cut to pay for it
    # in the same diff. (7450, 8200) -> (8578, 9450): the OSS_AGENT_ROLE
    # mechanism did not survive across Bash tool calls, and "tag, publish"
    # overstated what the code-level withholding covers. (8578, 9450) ->
    # (9918, 10900): the marker was write-only and blocked a legitimate
    # release forever after a dead sub-manager's leftover file -- the
    # marker-expiry and explicit-clear steps this fixes are load-bearing,
    # not padding.
    "agents/sub-manager.md": (9918, 10900),
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
