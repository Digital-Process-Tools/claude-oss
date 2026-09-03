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
    "agents/developer.md": (47819, 52600),
    "agents/auditor.md": (14329, 15800),
    "agents/release-auditor.md": (17857, 19700),
    "agents/triager.md": (17702, 19500),
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
    "agents/sub-manager.md": (14032, 15400),
    # #696: the releaser agent -- a fresh-context spawn holding tag-and-publish
    # authority, delegating the six gates to commands/release.md rather than
    # restating them (per #673's lesson about two documents drifting).
    "agents/releaser.md": (8691, 9560),
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
