# Open the workspace

How a maintainer session starts: what `bin/oss-workspace` sets up before `claude` runs, and how it
picks the one command that session opens with.

`.claude/jit-context/paths/00-manual/launcher-prompt-selection.md` is the rule for editing the file;
this is the whole shape in one place, so it is read rather than re-derived from 1,946 lines of shell.

## The two jobs

    1. Set the environment up correctly, and name every part of it that could not be established.
    2. Choose the next normal action for this repo, given its state.

Everything in the file serves one of those two. **Job 2 is the product**; the channel registration,
the symlink repoint, the census, the identity comparison and the diagnostic exist to make one choice
correctly.

## What is built, and what is designed

| | state |
| --- | --- |
| The working directory is the selection; anything not a work tree is refused | built |
| A working python proved by sentinel, never by name | built (#330) |
| Plugin kept current synchronously, before the prompt is chosen | built (#753) |
| The launcher's own symlink repointed from the registry, never from `$0` | built (#753, #289) |
| Watch-channel name declared, else derived, one validation gate for both roads | built (#191, #207, #230, #270) |
| The consumer asked whether it accepts the name, rather than a copied regex | built (#231, #618) |
| MCP server registered at local scope, re-pointed when it names a dead path | built (#621) |
| A second server resolving to the same consumer refuses the flag | built (#810) |
| Plugin identity compared against the last session on this machine | built (#626) |
| The setup diagnostic run before the session, relayed whole when not `ok` | built (#764) |
| The `/oss:doctor` route carries a receipt, so a standing WARN stops re-firing | built (#1064) |
| Prompt first, channel flag last | built |
| Job 2 reads more than one bit of repo state | **designed** |
| A threshold route for triage, curate and release | **designed** |
| Precedence between routes, and a receipt on each | **designed** |
| The readings the launcher computed reach the agent, not only stderr | **designed** |
| The Python behind the shell is a module with an entry point | **designed** |
| A launch is measured -- which prompt, how long, what was unknown | **designed** |
| Windows has a path in that is not `sh bin/oss-workspace` | **designed** (#330) |

**Nobody outside this repository's author has been observed running it.** Same gap as `CLAUDE.md`'s
*What is not proven yet*, reached from the launcher's side.

## The shape

One shell script, `exec`ing one command.

    bin/oss-workspace  ->  environment established, unknowns reported, one prompt chosen
    exec claude PROMPT [--dangerously-load-development-channels server:oss-channel]

**Nothing survives the `exec` except the prompt and the flag.** The two env relays
(`OSS_WORKSPACE_MCP_*`, `OSS_WORKSPACE_CENSUS_*`) reach a subprocess *before* the exec and are unset
on the last line before it: a reading left in the environment goes on answering all session.

## The steps

### Band A -- Resolve (1-5)

1. **Walk `$0`'s symlinks** for the plugin root. `${self%/*}` is tried against `/` and `\` -- under
   Git Bash the POSIX strip removes nothing.
2. **Refuse without `claude` or `git`.**
3. **Refuse anything not a git work tree**, then `cd` to its top level. The directory *is* the
   selection; this opens their repo, never the plugin's checkout.
4. **First prompt decision.** `.oss.json` present -> `/oss:tick`; absent -> `/oss:setup`.
5. **Find a working python by running it** -- `print(42)`, not by name. Windows ships a `python`
   that exists, opens a store page and runs nothing.

### Band B -- Set up (6-11)

6. **Update the plugin, synchronously.** `plugin_update.py --print-state`: `updated` / `current` /
   `off` / `could-not-check` / unparseable. `updated` moves `$prompt` to `/oss:doctor`.
7. **Repoint `~/.local/bin/oss-workspace`** from `installed_plugins.json`'s record for this project,
   never from `$plugin_root` or the link's own target.
8. **Radar tiers declared?** Three states, from `.supertool.json`.
9. **Resolve the watch-channel name.** Declared (four answers plus a short-argv fifth), else derived
   from `.oss.json`'s `repo` (five answers), then one validation gate both roads pass through. The
   consumer is then *asked* whether it accepts the name and whether anything ever spawned on it.
10. **Register the MCP server.** Find the consumer, read `claude mcp get`, compare command and args,
    re-point a dead path, refuse the flag without `bun` or an unverifiable registration.
11. **Census the consumer.** Two servers on one socket is worse than no board.

### Band C -- Decide (12-14)

12. **Did the plugin change since the last session on this machine?** Against
    `${XDG_CACHE_HOME:-$HOME/.cache}/oss-workspace/last-plugin-identity` -- a fact about the
    machine's install, so one file serves every repo. Reported, never routed on.
13. **Run the setup diagnostic.** `bash scripts/doctor.sh --root "$repo_root"`. `doctor.py` exits 0
    always, so the last column-0 `VERDICT:` line is parsed and the status read only for whether it
    ran. Six arms: `ok`; `usable with gaps` / `not usable`; `could not run`; unrecognised; no VERDICT
    line; could-not-be-started (126 / 127 / other, named separately).
14. **Arm the `/oss:doctor` route, against a receipt.** On a real WARN or FAIL, and only while
    `$prompt` is `/oss:tick`. Receipt is the verdict word plus the plugin identity, via
    `oss_state.py`; arms when absent or either has moved. Every failure to compare **fails open**.
    Written only when it arms.

### Band D -- Hand off (15-16)

15. **Unset the two relays.**
16. **`exec claude "$prompt" "$CHANNEL_FLAG" "server:oss-channel"`.** Prompt **first**, variadic flag
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

## What job 2 should choose from

Designed, none of it built. Today's vocabulary is three words and two are reachable in a configured
repo. Each candidate route is a **standing count crossing a threshold**, and every count already
exists:

| when | route | counted by | 2026-09-06 |
| --- | --- | --- | --- |
| no `.oss.json` | `/oss:setup` | the file's presence | built |
| plugin moved, or the doctor verdict moved | `/oss:doctor` | `plugin_update.py`, the `VERDICT:` line | built |
| open issues with no `lane-*` or no `priority-*` | `/oss:triage` | `gh-labels:tally=`'s `no ... label` row | 1 of 33, 1 of 33 |
| fragments in `trap.d/` | `/oss:curate` | `trap_curate.py`, which already prints `N waiting` | 11 |
| fragments in `changelog.d/` | `/oss:release` | the count `release_version.py` reads | 19 |
| nothing above | `/oss:tick` | the default, and the only route that is work | built |

The command is `/oss:curate`, not `/oss:trap`.

Four constraints the two built routes did not have:

- **A threshold is a per-repo fact**, so it goes in `.oss.json` and never in shared code. An absent
  key means the repo does not want the route.
- **Every count needs a third state.** `11 waiting` and `could not read the directory` must not both
  render as under threshold. `over` / `under` / `could-not-count`, and the third neither routes nor
  goes silent.
- **Precedence must be decided**, because more than one fires: this repo is over the curate and the
  release threshold at once. Not whichever check ran first.
- **Each route needs #1064's receipt.** A count stuck over threshold is the shape of an unclearable
  WARN -- 11 uncurated traps would pin every session to `/oss:curate`.

**The launcher must not become a second scheduler.** It picks the first command of one session; tick
ordering stays in `skills/manager/phases/tick-order.md`. The test for a route is whether a maintainer
opening this repo today would type that command first.

## Still open

- **Job 2 reads one bit of repo state.** Both inputs to the choice are facts about the *tooling*.
  Not covered by the threshold shape above, and unresolved: a red or pending default branch, a green
  PR waiting to merge, lanes already running -- real states, different first commands, no standing
  count.
- **Everything measured is thrown away at the `exec`.** The doctor report goes to stderr; the route
  then hands the session `/oss:doctor`, which re-runs it. ~1.9 s of the ~3.2 s launch, paid twice,
  and the agent starts with nothing. The fix is a receipt the opening command reads.
- **A mid-session plugin update leaves a stale registry and nothing acts on it.** Open for every
  hand-started `claude`; symptom is `Agent type not found`. The remedy string exists in
  `plugin_update.py` and `doctor_check_auto_update.py`; nothing reads the `updated` state after the
  fork and tells the running session.
- **The Python is inlined in shell, so nothing imports it.** 1,946 lines: 949 code, 901 comment, ten
  Python heredocs, twelve interpreter spawns, tested only end-to-end by 17 files totalling 375 KB.
  `pick-the-work.md`'s rule is *everything below the entry point is a module, not a command*. A
  `scripts/workspace_launch.py` behind a shell shim would make each band a function.
- **Nothing measures the launch** -- not which prompt, not how long, not how many unknowns. The one
  measurement is prose: eight runs, macOS 15.3.2 arm64, 2026-08-29, ~1.3 s without the diagnostic and
  ~3.2 s with it. The only launcher fact on disk is the #1064 receipt, and it lands in the tick's own
  append-only history.
- **The report has no ranking.** 67 stderr sites of equal weight; a launch reporting a dozen unknowns
  reads like one reporting none. No summary line saying what will open and what is unknown.
- **Windows has no front door.** `ln -sf` is POSIX-only with no equivalent (#330); the file is
  extensionless, on no Windows `PATH`, and the remedy is `sh bin/oss-workspace`. The channel also
  needs `bun`. *Two minutes to installed* is measured on one platform.
