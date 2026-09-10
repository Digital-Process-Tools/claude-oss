# Commands

**`/oss:run` is the one to type.** It diagnoses the repo on every start, repairs
what is ours, decides what is needed now (setup, release, curate, triage, or
the ordinary dispatch below) and acts on it, falling through to `/oss:tick`'s
own procedure when nothing more urgent is due. `bin/oss-workspace` opens every
session on it.

**The picker itself shows only some of these** (#1389). `/oss:run`,
`/oss:doctor`, `/oss:tick` and `/oss:release` are real top-level commands
under `commands/*.md`, discovered by the plugin harness. `setup`, `scaffold`,
`triage`, `curate`, `changelog` and `install-audit` moved to
`commands/run/*.md` -- a directory the harness never scans, so they are no
longer picker entries at all. Each is still reachable as `/oss:run <step>`
(the forcing override) or by reading its file directly; neither is a bare
`/oss:setup`-style invocation any more. `manager` (a skill, not a command)
does not appear either, per #1391's `user-invocable: false`.

| Command | Picker entry? | What it does |
| --- | --- | --- |
| `/oss:run` | yes | Run the repo. Diagnoses, decides what this repo needs now, and acts on it -- or dispatches, the ordinary cadence. Type it once. |
| `/oss:tick` | yes | One pass of the maintainer loop: board, decide, delegate, review, merge on green. |
| `/oss:run setup` | no -- override only | Probes the repo and writes `.oss.json`. Measures; never assumes — a version site is a file read and found to carry a version, and every label that matched no pattern is named. |
| `/oss:run scaffold` | no -- override only | Adds the missing repo furniture. Never overwrites; shows before it writes. Reports what it will not do: create a label, guess a required-check count, or generate a test workflow. Its receipt reads both halves of the board question, so a repo it scaffolded before the preset was added — tiers registered, no route to the op that reads them, and unreachable by a template fix because `.supertool.json` is never replaced — is reported rather than called clean. |
| `/oss:run triage` | no -- override only | One triage sweep — priority, lane, milestone, the clusters one change would fix, the cohort burn-down with the limit it was counted under, and what the board is lying about. |
| `/oss:run changelog` | no -- override only | Checks changelog fragments, or folds them for a release. |
| `/oss:release` | yes | Gates, version sites, tag, and — where `.oss.json` says so — the GitHub Release, notes and all. |
| `/oss:doctor` | yes | Config, dependencies, clone, worktree root, state file, which watch channel and radar board this repo resolves to, whether a `pre-push` hook's push budget was ever raised above supertool's 300s default, and whether the merge call can skip supertool's publish-confirm gate. Also reports default branch protection, clone HEAD drift, and worktree-reap permission (#759, #763, #787), and which copy of this plugin answered the invocation (compared by content and by declared schema version, not by manifest version alone), where a defect in this plugin itself would get filed, whether `./supertool` points at this plugin's own checkout, whether the supertool that answers here carries the ops this plugin's own commands and briefs actually name — with `could not ask` kept distinct from `they are all there` — whether a SECOND configured MCP server also resolves to the claude-channel consumer script (a socket collision `channel:health` can only report as `CANNOT DETERMINE` from inside a session, never diagnose — #810), and three lines about the machine itself — interpreter architecture, CPU topology, worker sizing. Exits 0 always; see `commands/doctor.md` for what each line means. |
| `/oss:run install-audit` | no -- override only | Is this install complete — the plugin, its declared dependencies, and what the human still has to do, answerable with no `.oss.json` in hand: is it present, valid, *and committed*; do declared dependencies resolve at a version this plugin's scripts can read; does the label vocabulary the triager needs exist; would re-scaffolding change the owned files. Exits 0 always; see `commands/run/install-audit.md`. |
| `/oss:run curate` | no -- override only | Curate the traps logged in `trap.d/` into jit-context rules — promote, merge or decline, one fragment at a time. |
