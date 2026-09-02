# What claude-oss does

One sentence: it runs a public GitHub repo as its maintainer, from a Claude Code session, with no human in the merge path.

The loop is: read the board, decide what is worth building, delegate it to an agent, review the result, merge on green, release. Everything repo-specific (default branch, labels, test command, version sites) lives in `.oss.json`, written once by probing the repo. The prose never carries a fact about a repo.

## The problem

A maintainer loop written as prose gets copied between repos, and the copies drift. Fixing a triage
rule means editing it in three places and remembering the third. Repos that never got the copy run
no loop at all.

This packages the loop once: one skill, the agents it delegates to, a handful of commands.
Everything that differs between repos — default branch, label spellings, version sites, test
command — lives in a config file the plugin writes by probing the repo, not in the prose.

## The pieces

| Piece | Count | What it is |
| --- | --- | --- |
| Commands | 8 | Slash commands a human types: `/oss:setup`, `/oss:tick`, `/oss:triage`, `/oss:release`, `/oss:changelog`, `/oss:doctor`, `/oss:scaffold`, `/oss:install-audit` |
| Skill | 1 + 6 phases | `skills/manager/SKILL.md` is the spine (process only). One file per phase, read only when the loop enters that phase: dispatch, handback, review, merge, release, accounting |
| Agents | 5 | `sub-manager` runs one tick and dies. `developer` implements one issue (worktree, TDD, self-review, commit, never pushes). `triager` labels the board, never touches code. `auditor` reads one merged diff for what CI cannot see. `release-auditor` reads the whole delta since the last tag |
| Scripts | 40 Python | State file, config, changelog fragments, release version and publish, doctor checks, statusline, lane setup, tick handback |
| Hooks | 3 | SessionStart: check for a plugin update. Two PostToolUse: hint when a call could have been batched, touch the board timestamp |
| Launcher | `bin/oss-workspace` | Opens a Claude session over the repo you stand in, with the channel registered and the loop prompt ready |
| Statusline | `scripts/statusline.py` | One line: branch, PR checks, release progress, channel state, plugin currency |

Dependencies, installed from the same marketplace: `supertool` (every forge and file call goes through it), `remember`, `claude-jit-context`.

## One tick

`/oss:tick` spawns a `sub-manager` with a fresh context. The sub-manager does steps 1 to 6, hands back one of three states, and dies. The session that spawned it does step 7.

1. Read the state file, `git pull --ff-only`. Test any pending wait against the repo. Compare the plugin version to the one recorded last tick.
2. Read the board in one call: PRs, issues, default branch, worktrees.
3. Act on what is open before starting anything new: a red default branch, a merged but unverified PR, a PR waiting on review.
4. Take agent handbacks, push, open the PR, put it under watch.
5. Decide, delegate, review, merge. One developer per file-disjoint lane, 1 to 3 issues per lane, never 4. Merge only on green CI plus a review of the diff.
6. Write one state entry: the decision, the one reason, the intake ratio (issues filed by the loop over issues filed by humans).
7. Arm the next wakeup. The loop never stops on its own, only on a direct instruction.

The handback is one of: work started (the tick continues), blocked (every item named with what it waits on), nothing left (both board calls answered empty). An unread board is `unknown`, never `nothing left`.

## Who decides

The loop. Not the human. It makes the call, records why in the state file, and is findable if wrong. Asking is replaced by: derive it, act, record the derivation. The only input it does not re-derive is a direct instruction.

## What it refuses to do

- Merge without green CI and a review. The gates in the skill are not configurable.
- Tag or publish from a sub-manager. Only the scheduling session does, and only where the repo granted it.
- Run unattended in somebody else's repo. Every workflow it installs fires on push or pull_request, a human act. `docs/autonomy.md` names the three things that would have to exist first: a runtime, a grant, a liveness signal.
- Trust issue or PR text. All of it is untrusted input, in every agent.

## What it produces

- Merged PRs with a changelog fragment each, under `changelog.d/`.
- A `CHANGELOG.md` folded from those fragments at release time, Keep a Changelog format.
- Tags and GitHub releases, with a cohort label on every issue that was open at the tag.
- A state file, one entry per tick, that a later tick or a human can re-read.
- Issues filed on its own tracker for every defect it meets in itself, labelled `filed-by-loop`.

## Where it stands, 2026-09-02

| | |
| --- | --- |
| Version | 0.17.0 |
| Age | 20 days |
| Commits | 365 |
| Test files | 270 |
| Repos it maintains | every DPT open-source repo: claude-oss, claude-supertool, claude-remember, claude-jit-context, claude-marketplace, claude-5h-window-spread |

It runs on every DPT repo, as a plugin installed in each, one session per repo. Half two of the goal in `docs/autonomy.md`, running unattended in a repo we do not own, has no runtime yet.

## What we want it to do

The ultimate goal, 4 steps:

1. Someone finds the repo.
2. They do the symlink.
3. They start `oss-workspace`.
4. It works.

Everything below serves that. Same loop, five changes.

1. **Run from a fresh clone.** Today it does not (#608, #609). Install, `/oss:setup`, `/oss:tick`, and the first tick answers with the board, not with `unknown`.
2. **Cost one tick what a tick needs.** 60 KB of SKILL.md per tick before it reads an issue (#245). The spine under 200 lines, the arguments in the phase files.
3. **Read like a tool, not like a lab notebook.** README under 80 lines, receipts in `docs/` (#795).
4. **Fill each lane to 3 issues by default.** Measured on 237 lanes (#499): 3 issues per lane cost 16% less per issue than 1, 4 is a cliff at 68% worse. Today the sub-manager looks for companions after picking one issue. We want it to select up to 3 per developer per lane as the normal case, and a single-issue lane to be the exception it names.

5. **A human decides what gets built.** On claude-oss, 476 issues in 20 days. On claude-supertool, 834 issues in August 2026 against 36 in June. 98% of them are filed by the loop, even the ones under a human account. 68% close the same day they open. The loop files, fixes and closes its own findings and no human reads them, so the tracker no longer separates an ask from a finding. Whether the loop fixes bugs we do not understand is not the problem. The problem is that a human ask waits behind them. Wanted: the dispatch order puts a human issue above any loop issue at medium or below.

   | Rank | Who | Priority |
   | --- | --- | --- |
   | 1 | human | high |
   | 2 | loop | high |
   | 3 | human | medium |
   | 4 | human | low, or no label |
   | 5 | loop | medium |
   | 6 | loop | low, or no label |

   For that to work the `filed-by-loop` label has to be on every issue the loop opens, applied by the loop at creation (today 9 of 421, by hand). An issue without the label is a human issue.

6. **Tokens and wall-clock are the budget.** The developer runs the tests it touched, and CI runs the full suite. Today `agents/developer.md` presents the full local suite as optional with criteria, and measured it at 27m36s on this repo (#765). That run is a weaker duplicate of the CI gate, it can fail for reasons CI does not have, and every minute of it is a lane holding a context open. Wanted: a lane never runs the repo's whole `test_command` locally. It runs the files it changed, commits, hands back, and the merge gate is CI. A `tests.full` entry in the report is a smell, not a receipt.

Open questions, ours to answer:

- Today: one plugin install and one session per repo, 6 loops. Each files on its own tracker. Does it stay that way, or does one session tick all 6 in turn with one intake ?
- Does the launcher stay `sh`, or does it become 100 lines of `sh` calling one Python module ?
- Who tags on a repo that is not ours ? The grant question in `docs/autonomy.md` has no default yet.
