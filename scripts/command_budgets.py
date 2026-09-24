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
    # Re-baselined for #985: this row had already drifted to 52,090 B by the
    # time #985 re-measured it (grown past the 48,465 B baseline in #1001's
    # own diff, unnoticed because `check()` only compares against `budget`,
    # never against `baseline` -- a real gap #985's own review round found
    # and named as `misreports`, not a defect this commit's diff introduced).
    # Re-measured rather than left stale, with ~10% headroom restored.
    # Re-baselined for #1037: steps 1-6 and "What ends a tick" moved out to
    # `skills/manager/phases/tick-order.md` (see skill_phases.py), because
    # only a sub-manager's own context ever executed them -- 52,090 B fell to
    # 16,294 B. The budget comes down with the measurement rather than
    # staying at 57,300 B, the same reasoning #958 and #960 already give for
    # skill_phases.py's own re-baselines: a ceiling left far above the file
    # is a saving spendable again without anybody choosing to.
    # Re-baselined for #1048: 17426 B on disk against a stale 16294 declared
    # baseline -- the could-not-classify re-ask-first paragraph and a
    # self-review fix (two stale "below" cross-references pointing at
    # content #1037 moved out of this file) landed here. Budget unchanged;
    # comfortably under it.
    # Raised for #1041 (self-review round of #1119/#1041/#1043): 17899 B
    # became 18276 B, past the 17900 B ceiling with 1 B of headroom left.
    # The releaser paragraph here still said "one of three states, never a
    # TICK: handback, and nothing classifies it" after agents/releaser.md
    # gained a fourth (`paused`) state and scripts/release_handback.py was
    # added to classify it -- a reviewer spawn caught the contradiction.
    # Nothing already in the file argued that point, so there was nothing
    # safe to cut in its place; the ceiling moves to 20100 B, ~10% headroom
    # over the new size.
    # Re-baselined for #1349: 18276 B became 19645 B, then 20177 B in the
    # same lane's own self-review round -- past the 20100 B ceiling by
    # 77 B. Step 7's `work-started` handling used to read a sub-manager's
    # task-notification as "the tick is over" and spawned a second
    # sub-manager on it -- but a task-notification firing is not the same
    # fact as that agent's turn having ended permanently, since the same
    # spawn can notify more than once. The new paragraph says "keep
    # working" can mean the same sub-manager continuing, and names a
    # check to tell that apart from a genuinely finished one before
    # spawning a fresh oss:sub-manager. A self-review reviewer spawn
    # caught the first draft naming a nonexistent `ListAgents` tool (not
    # granted to any agent in this repo, not used anywhere else in it)
    # and leaving no case for a `SendMessage` probe that neither refuses
    # nor replies -- fixed by reusing the file's own existing
    # SendMessage-refusal idiom (the same one the could-not-classify
    # re-ask a few lines above already relies on) and naming all three
    # outcomes (refusal, reply, unresolved) explicitly. Nothing already
    # in the file argued either point, so nothing was cut to make room;
    # the ceiling moves to 22200 B, ~10% headroom over the new size.
    # Re-baselined by #1386/#1402: 20177 B became 21917 B for the scheduler's
    # own new step reading a releaser's `RELEASE: released` handback and
    # calling `scripts/triage_trigger.py`. Ceiling unchanged.
    # Re-baselined for #1421: 21917 B became 21939 B, anchoring the self-read
    # instruction at line 11 (`supertool 'read:commands/tick.md:OFFSET:
    # LIMIT'`) to `${CLAUDE_PLUGIN_ROOT}/commands/tick.md` -- the same
    # cwd-relative gap #1419/#1420 already fixed for commands/run.md's six
    # scheduler-step spawns, live only when tick.md is reached from
    # commands/run.md's dispatch step rather than harness-injected directly.
    # Ceiling unchanged; still comfortably under it.
    # Raised for #1436: 21939 B became 22271 B, past the 22200 B ceiling by
    # 71 B. The `--triage-recorded` call at step 6 (added by #1386) could not
    # actually run as written -- it is an attachment to `--decision`, not its
    # own mode flag, and `oss_state.py`'s argparse refuses it alone. The fix
    # attaches it to a real `--decision "triage sweep recorded" --at ...`
    # call and adds one explanatory sentence naming why. Too small an
    # overage to be worth trimming something else in the same file to
    # absorb, so the ceiling moves to 24500 B, ~10% headroom over the new
    # size, rather than cutting anything.
    # Re-baselined for #1431: 22271 B became 22275 B -- the "if .oss.json is
    # missing" remedy now says "/oss:run setup" rather than the dead bare
    # "/oss:setup" form. Ceiling unchanged; comfortably under.
    # Re-baselined for #1508: 22275 B became 22444 B -- step 7's paused
    # resume names the poll-timer as the arm, since the per-PR pollers
    # exclude checks_succeeded by design. Ceiling unchanged.
    # Re-baselined for #1499: 22444 B became 22424 B -- step 7's paused-resume
    # paragraph now says checks_succeeded is delivered on the channel, not
    # excluded (dropped from INITIAL_EXCLUDE, the asymmetry against
    # checks_failed was never argued for). Ceiling unchanged.
    # Re-baselined for #1550: 22424 B became 23328 B -- the post-release
    # triage step dispatches the identical oss:triager agent
    # commands/run/triage.md's own sweep does, producing the identical
    # five-part report, so it carried the identical cohort-burndown/
    # findings-routing gap and needed the identical fix (found by review,
    # not the issue's own stated scope). Ceiling unchanged, comfortably
    # under.
    # Re-baselined for #1550 (CI fix): 23328 B became 23649 B -- the
    # --detail JSON added to the executed ```bash block used unresolved
    # <N>/<M> placeholders, which #1436's own gate-3 test extracts and
    # runs verbatim (tests/test_gate3_r1_1436.py's
    # test_tick_mds_own_call_shape_actually_runs), breaking CI on 4 of 10
    # legs with "--detail is not valid JSON". Moved the --detail example
    # out of the executed fence into prose describing how to attach it
    # with real values. Ceiling unchanged, comfortably under.
    "commands/tick.md": (24194, 24500),
    # #1389: the new two-verb entry point. It stays deliberately thin -- it
    # diagnoses (step 1), decides via `scripts/next_action.py` (step 2), and
    # for every branch other than the ordinary dispatch cadence it points at
    # an existing command file's own procedure rather than duplicating it, the
    # same "read the phase file when you reach it" shape `agents/developer.md`
    # already uses for its own late phases. Budgeted from the day it was
    # added, unlike `tick.md`, which grew unbudgeted for years first (#940).
    # Re-baselined by #1389's own follow-up (the picker consolidation): 4365 B
    # became 4784 B naming the six commands moved to `commands/run/*.md` and
    # why `commands/release.md` did not move with them. Ceiling unchanged.
    # Raised for #1414: 4784 B became 6646 B. The scheduler used to read
    # six command files and `commands/release.md` directly in its own
    # long-lived session -- exactly the erosion #695 built the sub-manager
    # split to prevent, one layer over, and the four-state `next_action.py`
    # shape this file parsed (`due`/`nothing-due`/`could-not-decide`/
    # `unsafe`) no longer matches #1405's `rank()` output at all. Every
    # sub-step now names a spawn (`oss:scheduler-step` for the six generic
    # ones, `oss:releaser` for release, unchanged for dispatch) instead of
    # "read and follow" prose, and step 2 documents `rank()`'s ordered
    # candidates plus the `--record-skip` CLI for a deliberate deviation.
    # Nothing already in the file argued either point, so nothing was cut
    # to make room; the ceiling moves to 7300 B, ~10% headroom over the
    # new size.
    # Re-baselined in the same lane's own self-review: 6646 B became 6810 B
    # after test_picker_demotion_1389.py's own regression test required
    # every one of the six demoted files' literal paths to appear, not the
    # `<name>` placeholder the first draft used in the shared spawn example.
    # Ceiling unchanged; still comfortably under it.
    # Re-baselined once more in the same lane's own second self-review round:
    # 6810 B became 7162 B, making each of the five remaining generic
    # sub-steps (scaffold, install-audit, triage, curate, changelog) its own
    # literal `Agent(...)` line rather than one shared example a reader had
    # to adapt by hand -- an Explore reviewer found the shared form let the
    # file drift back to "read and follow" prose for four of the five while
    # the required literal paths stayed present, with nothing to notice.
    # Ceiling unchanged; still comfortably under it.
    # Raised once more, same self-review round: 7162 B became 8041 B. The
    # `--take` CLI (#1414's own follow-up finding: `rank()` must never arm a
    # receipt merely for being read, only an explicit commitment may) needed
    # documenting in step 2 alongside `--record-skip`, since the ordinary
    # case -- taking `candidates[0]` -- now needs a `--take` call before the
    # corresponding spawn, not only the deviation case. Nothing already in
    # the file argued that point, so nothing was cut to make room; the
    # ceiling moves to 8900 B, ~10% headroom over the new size.
    # Re-baselined for #1419: 8041 B became 8173 B, anchoring the six
    # scheduler-step Agent spawn prompts to ${CLAUDE_PLUGIN_ROOT} instead of
    # a cwd-relative path that only resolved inside this repo's own
    # checkout. Ceiling unchanged; still comfortably under it.
    # Re-baselined for #1421: 8173 B became 8233 B. The `## dispatch`
    # section's own read of `commands/tick.md` was the seventh site of the
    # same shape #1419/#1420 fixed for the six scheduler-step spawns above,
    # missed there because it named the target with the pronoun "it" rather
    # than a literal path -- now anchored to
    # `${CLAUDE_PLUGIN_ROOT}/commands/tick.md` the same way. Ceiling
    # unchanged; still comfortably under it.
    # Re-baselined for #1425: 8233 B became 8400 B. One sentence after the
    # curate spawn line states its standing authority directly -- decides
    # on its own, its pull request is the review -- so the spawn never has
    # to infer that from the absence of an instruction to stop and ask.
    # Ceiling unchanged; still comfortably under it.
    # Re-baselined DOWN for #1457: 8717 B became 8246 B. Step 1's own
    # inline WARN/FAIL chase (run doctor.sh, then two hand-written bullets
    # for "ours to repair" vs "not ours") replaced with a spawn of the new
    # agents/doctor.md, the same move #1414 already made for the six
    # commands/run/*.md sub-steps -- a line that needs investigation no
    # longer sits permanently in this session's own context. Replacing
    # rather than appending shrank the file; ceiling unchanged.
    # Re-baselined for #1549: 8246 B became 8855 B. One paragraph added to
    # the scaffold/install-audit/triage/curate/changelog section, stating
    # plainly that a pull request one of those steps just opened is not this
    # session's to wait on -- return to step 2 immediately rather than
    # blocking on that PR's own CI. curate/triage/inbound are doubly safe via
    # step 2's own --take-armed repeat-suppression receipt; scaffold/
    # install-audit/changelog carry no such receipt because they are never
    # next_action.py sources at all, reachable only by forced $ARGUMENTS, so
    # there is nothing for step 2 to re-select there either (self-review
    # finding, Explore reviewer: the first draft of this paragraph implied
    # the receipt covered all five). Ceiling unchanged, comfortably under it.
    # 8855 B became 8863 B (second-pass self-review, Explore reviewer): step
    # 2's own text still said the receipt was a no-op for inbound/release,
    # stale since #1433 added inbound to the same mechanism -- now says
    # release only, directly beside the paragraph this commit just wrote
    # naming inbound as one of the three armed sources.
    # Re-baselined for #1629: 8899 B became 9489 B. The scaffold/install-audit/
    # triage/curate/changelog section's claim that the harness "discovers slash
    # commands from top-level commands/*.md only, never recursively" was false
    # -- the six commands/run/*.md files are reachable directly as
    # /oss:run:setup and so on, confirmed against a live session's own skill
    # listing (#1629's own "Observed" section). Corrected in place, plus the
    # `## release` section's stale claim that commands/release.md's picker
    # placement was a deliberate, settled #1389 decision -- the maintainer's
    # follow-up comment on #1629 retires that note.
    # 9489 B became 9586 B (self-review, two rounds): a first-pass reviewer
    # flagged the release section's 145/50 reference count as unreproducible
    # against a git grep run on this diff's own tree, where the diff's own new
    # mentions of "commands/release.md" (this file, the changelog fragment,
    # this very comment) inflate the count to 149/51; "corrected" to 146/50 by
    # excluding some but not all of those self-references. A second-pass
    # reviewer caught that the fix was wrong: 145/50 was the real, exactly
    # reproducing count all along, measured at e92b0b85 (the commit before
    # this branch touched anything) -- the only count not contaminated by the
    # diff's own self-reference, the same trap CLAUDE.md's own budget row
    # documents. Restored to 145/50, sourced explicitly against that commit
    # rather than "the tree" so a future re-measurement does not fall into the
    # same trap. Nothing already in the file argued either point, so nothing
    # was cut to make room; the ceiling moves to 10600 B, ~10% headroom over
    # the new size.
    # Re-baselined for #1649: 9586 B became 9612 B -- the step 1 doctor spawn
    # pinned to run_in_background: false, the one bare Agent(...) call #1586's
    # own fix elsewhere did not reach. Ceiling unchanged; comfortably under it.
    # Re-baselined again in the same lane's own self-review round: 9612 B
    # became 9632 B -- the relay vocabulary line gained the new
    # could-not-repair: outcome, one of two docs a reviewer found still
    # enumerating only three states. Ceiling unchanged; comfortably under it.
    # Re-baselined for #1687: step 1 now names how a `repaired:` line naming
    # a branch gets pushed and turned into a pull request (never waited on --
    # the ordinary dispatch/review/merge cadence picks it up). 9632 B became
    # 10380 B. Ceiling unchanged, ~2% headroom.
    "commands/run.md": (10380, 10600),
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
