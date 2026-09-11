# Open the workspace

How a maintainer session starts: what `bin/oss-workspace` sets up before `claude` runs. It always
opens the same command, `/oss:run` -- picking what to do next is that session's own job now, not
the launcher's (#1389/#1390/#1392; see *Job 2 moved*, below).

`.claude/jit-context/paths/00-manual/launcher-prompt-selection.md` is the rule for editing the file;
this is the whole shape in one place, so it is read rather than re-derived from 2,153 lines of shell.

## The one job left, and the one that moved out

    1. Set the environment up correctly, and name every part of it that could not be established.
    2. (moved to /oss:run's own session) Choose the next normal action for this repo, given its state.

Job 1 is what the rest of this file describes: the channel registration, the symlink repoint, the
census, and the identity comparison. Job 2 used to be this file's product -- the whole reason job 1
existed was to feed it -- but nothing in `bin/oss-workspace` computes it any more. What job 1
produces now reaches only stderr and a fixed `prompt="/oss:run"`; the actual choice happens after
`exec`, inside the session that opens.

## What is built, and what is designed

| | state |
| --- | --- |
| The working directory is the selection; anything not a work tree is refused | built |
| A working python proved by sentinel, never by name | built (#330) |
| Plugin kept current synchronously, before the session opens | built (#753) |
| The launcher's own symlink repointed from the registry, never from `$0` | built (#753, #289) |
| Watch-channel name declared, else derived, one validation gate for both roads | built (#191, #207, #230, #270) |
| The consumer asked whether it accepts the name, rather than a copied regex | built (#231, #618) |
| MCP server registered at local scope, re-pointed when it names a dead path | built (#621) |
| A second server resolving to the same consumer refuses the flag | built (#810) |
| Plugin identity compared against the last session on this machine | built (#626) |
| Prompt first, channel flag last | built |
| The session always opens on `/oss:run`, which decides for itself from there | built (#1389, #1390, #1392) |
| The readings the launcher computed reach the agent, not only stderr | **designed** |
| The Python behind the shell is a module with an entry point | **designed** |
| A launch is measured -- which prompt, how long, what was unknown | **designed** |
| Windows has a path in that is not `sh bin/oss-workspace` | **designed** (#330) |

**Removed, not just moved.** The pre-launch setup diagnostic and the `/oss:doctor` receipt route
(`built (#764)` / `built (#1064)` in an earlier version of this table) and the #1155 threshold
routes (`Job 2 reads more than one bit of repo state`, `A threshold route for triage, curate and
release`, `Precedence between routes, and a receipt on each`) all used to be rows here. Issues
#1389, #1390 and #1392 deleted the code they described from this file entirely rather than leaving
it running alongside `/oss:run`'s own copy -- see *Job 2 moved*, below.

**Nobody outside this repository's author has been observed running it.** Same gap as `CLAUDE.md`'s
*What is not proven yet*, reached from the launcher's side.

## The shape

One shell script, `exec`ing one command.

    bin/oss-workspace  ->  environment established, unknowns reported, one prompt chosen
    exec claude PROMPT [--dangerously-load-development-channels server:oss-channel]

**Nothing survives the `exec` except the prompt and the flag.** Four env relay groups
(`OSS_WORKSPACE_MCP_*`, `OSS_WORKSPACE_CENSUS_*`, `OSS_WORKSPACE_MCP_LIST_*` (#1372),
`OSS_WORKSPACE_CHANNEL_ARM_TARGET` (#1307)) are set before the `exec` and unset again on the last
line before it: a reading left in the environment would go on answering all session. **Since #1392
removed this file's own synchronous `doctor.sh` call, none of the four currently has a live
consumer** -- the diagnostic that used to read them now runs from inside `/oss:run` instead, so
treat a relay here as dead plumbing pending #1432, not as something a session downstream can rely
on (`.claude/jit-context/paths/00-manual/launcher-prompt-selection.md` carries the same note).

## The steps

### Band A -- Resolve (1-5)

1. **Walk `$0`'s symlinks** for the plugin root. `${self%/*}` is tried against `/` and `\` -- under
   Git Bash the POSIX strip removes nothing.
2. **Refuse without `claude` or `git`.**
3. **Refuse anything not a git work tree**, then `cd` to its top level. The directory *is* the
   selection; this opens their repo, never the plugin's checkout.
4. **Choose the opening prompt.** No decision left here (#1389/#1392): `prompt="/oss:run"`, set
   once and never reassigned. `/oss:run` is where "what does this repo need now" is actually
   answered, from inside its own session -- see *Job 2 moved* below.
5. **Find a working python by running it** -- `print(42)`, not by name. Windows ships a `python`
   that exists, opens a store page and runs nothing.

### Band B -- Set up (6-11)

6. **Update the plugin, synchronously.** `plugin_update.py --print-state`: `updated` / `current` /
   `off` / `could-not-check` / unparseable. `updated` no longer moves `$prompt` (#1392): it is
   reported on stderr and `/oss:run` still opens, diagnosing the tree it just moved to on its own
   first turn.
7. **Repoint `~/.local/bin/oss-workspace`** from `installed_plugins.json`'s record for this project,
   never from `$plugin_root` or the link's own target.
8. **Radar tiers declared?** Three states, from `.supertool.json`.
9. **Resolve the watch-channel name.** Declared (four answers plus a short-argv fifth), else derived
   from `.oss.json`'s `repo` (five answers), then one validation gate both roads pass through. The
   consumer is then *asked* whether it accepts the name and whether anything ever spawned on it.
10. **Register the MCP server.** Find the consumer, read `claude mcp get`, compare command and args,
    re-point a dead path, refuse the flag without `bun` or an unverifiable registration.
11. **Census the consumer.** Two servers on one socket is worse than no board.

### Band C -- Report (12)

12. **Did the plugin change since the last session on this machine?** Against
    `${XDG_CACHE_HOME:-$HOME/.cache}/oss-workspace/last-plugin-identity` -- a fact about the
    machine's install, so one file serves every repo. Reported, never routed on.

**#1392 removed the two steps that used to sit here.** The pre-launch setup diagnostic
(`bash scripts/doctor.sh --root "$repo_root"`) and the `/oss:doctor`-route receipt built on top of
it both used to run synchronously in this shell, deciding from outside whether the opening prompt
should divert. Both dissolve into `/oss:run` itself (#1389/#1390): it runs the identical diagnostic
on every start, from inside the session that can actually repair what it finds, rather than this
file reading a verdict it cannot act on and picking a different prompt around it.

### Band D -- Hand off (13-14)

13. **Unset the four relays.**
14. **`exec claude "$prompt" "$CHANNEL_FLAG" "server:oss-channel"`.** Prompt **first**, variadic flag
    **last**: `claude` reads only its first positional as the prompt, and a positional after the flag
    is read as one of its values and refuses the launch. **With any argument, the prompt is not
    appended** and the reason is stated.

## The rules the steps converge on

**Every unknown gets a name, and no unknown renders as a pass.** 67 stderr sites hold this: a
skipped diagnostic, an unreadable registry, an unparseable state word and a crashed probe each say
what is now unknown.

**Report, never refuse.** Three refusals only -- no `claude`, no `git`, not a work tree -- each a
fact about whether the tool can run. Everything else opens the session: a maintainer whose config is
broken needs a session to fix it in.

## What this deliberately does not do

**No `/reload-plugins` after the update.** Step 6 is synchronous and pre-`exec`, so the session never
held the old registry. `plugin_update.py`'s own `--print-state` comment (around its `main()`, the
`--print-state` block) says the same and is why the launcher composes its own sentence instead of
using the receipt's `detail` -- cited by name rather than by line number, which this same diff
already moved once by adding the `--caller` argv parsing above it. The case that does need it -- an
update landing
under a running session via `hooks/session-start-update.sh` -- opens after this file has `exec`ed.
Issue #1154 fixed the instance where doctor printed the reload advice anyway: step 6 now passes
`--caller launcher`, `plugin_update.update()` writes it onto the receipt as `document["caller"]`,
and `doctor.check_auto_update` reads it back -- `"launcher"` never claims `/reload-plugins` will do
anything for the session reading it; anything else (an older receipt, or the hook's own call, which
never passes `caller`) keeps the original advice.

**No transcribed rule.** Name acceptance asks the consumer; the census asks `doctor.py`. A copied
`NAME_RE` is a second rule that drifts.

**No summarising a bad verdict to its word.** Once not `ok`, the whole report is relayed: `not
checked` is a third state that reads as clean.

## Job 2 moved

This file used to carry a whole section here -- `scripts/workspace_routes.py`'s threshold table,
called from the launcher itself once the two tooling-facing routes above (setup, plugin update)
had both declined to move `$prompt`. #1389/#1390/#1392 deleted that call from `bin/oss-workspace`
entirely, along with the pre-launch setup diagnostic and its `/oss:doctor`-route receipt (Band C,
above) -- **job 2, deciding what this repo needs now, is no longer this file's job at all.**

The launcher's own job 2 is now trivial: open the session on `/oss:run`, unconditionally, and let
that session do the deciding from inside a context that can also act on what it finds. The real
successor to this section lives in `commands/run.md`, not here:

- **Step 1** runs the identical setup diagnostic this file used to run before `exec`
  (`scripts/doctor.sh`), but from inside the `/oss:run` session, which can repair what is ours and
  report what is not rather than only relaying a verdict to a launcher that cannot act on it.
- **Step 2** calls `scripts/next_action.py --root . --json`, whose `rank()` composes the same
  `scripts/workspace_routes.py` threshold routes this section used to describe (`triage_route_
  threshold`, `curate_route_threshold`, `release_route_threshold`, `ROUTES = ("release", "triage",
  "curate")` for precedence, the `over`/`under`/`could-not-count` third state, the #1064-style
  receipt so a route does not re-fire on an unchanged signature) alongside an `inbound` source and
  the `setup`/`unsafe` cases the two tooling routes above used to cover on their own. See
  `commands/run.md` for the full shape -- `unsafe` refuses, `due` (`setup`, when there is no
  `.oss.json` yet) spawns and re-asks, `ranked` orders every candidate rather than picking one
  silently, and `nothing-due` falls through to the ordinary dispatch cadence
  (`skills/manager/phases/tick-order.md`).

**The launcher must not become a second scheduler**, and moving job 2 out of it entirely is the
sharper version of that same rule this section used to state about precedence alone: tick ordering
stays in `skills/manager/phases/tick-order.md`, route ordering now stays in `next_action.py`, and
this file's only remaining say over what runs first is *always `/oss:run`*.

## Still open

- **Job 2 -- now `next_action.rank()`, not this file -- still does not read a red or pending
  default branch, a green PR waiting to merge, or lanes already running.** Real states, different
  first commands, no standing count -- explicitly out of scope for the threshold shape it inherited
  from #1155, and still undesigned.
- **The launcher's own diagnostic run is gone, not just its routing.** #1392 moved `doctor.sh`
  entirely into `/oss:run`'s own first turn (`commands/run.md` step 1), so there is no longer a
  pre-`exec` reading to throw away or a `/oss:doctor` divert to hand it to -- the whole "measured
  once here, re-run again once the session opens" duplication this bullet used to describe is gone
  along with the code that caused it.
- **A mid-session plugin update leaves a stale registry and nothing acts on it.** Open for every
  hand-started `claude`; symptom is `Agent type not found`. The remedy string exists in
  `plugin_update.py` and `doctor_check_auto_update.py`; nothing reads the `updated` state after the
  fork and tells the running session.
- **The Python is inlined in shell, so nothing imports it.** 2,153 lines, roughly half of them
  comment, tested only end-to-end (21 test files, ~288 KB, as of this writing -- both numbers drift
  and are worth re-measuring rather than trusting). `pick-the-work.md`'s rule is *everything below
  the entry point is a module, not a command*. A `scripts/workspace_launch.py` behind a shell shim
  would make each band a function.
- **Nothing measures the launch** -- not which prompt, not how long, not how many unknowns (the
  prompt is fixed now, so "which prompt" no longer varies, but the rest still applies). The one
  measurement is prose: eight runs, macOS 15.3.2 arm64, 2026-08-29, ~1.3 s without the diagnostic and
  ~3.2 s with it -- both numbers taken before #1392 moved the diagnostic out of this file, so
  re-measure rather than trust them for what `bin/oss-workspace` does today. The route receipts
  this bullet used to point at (#1064's shape, generalised by #1155) moved with job 2 into
  `next_action.py`/`oss_state.py`'s own `workspace_route_check`, in this repo's `state_file` -- no
  longer a launcher fact at all.
- **The report has no ranking.** 67 stderr sites of equal weight; a launch reporting a dozen unknowns
  reads like one reporting none. No summary line saying what will open and what is unknown.
- **Windows has no front door.** `ln -sf` is POSIX-only with no equivalent (#330); the file is
  extensionless, on no Windows `PATH`, and the remedy is `sh bin/oss-workspace`. The channel also
  needs `bun`. *Two minutes to installed* is measured on one platform.
