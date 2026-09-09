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
    "agents/developer.md": (41227, 44100),
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
    "agents/triager.md": (15488, 16600),
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
    "agents/sub-manager.md": (17104, 18800),
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
