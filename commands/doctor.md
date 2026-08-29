---
description: Diagnose this repo's oss setup — config, dependencies, clone, worktree root, state file, watch channel, radar board.
allowed-tools: Bash
---

Run the diagnostic and relay its output verbatim:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh" --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

**`--plugin-root` is not redundant with the path in front of it**, and dropping it silently
downgrades one line to its third state. The launcher resolves the script from that path either
way; the flag is the *invocation* saying which copy it resolved, which is a fact no script can
observe about itself. Without it the run cannot tell "this is the copy the harness answers
commands from" from "this is wherever somebody happened to run a script", and it says so.

Add `--root <path>` to point it at a repo other than the one you are standing in. The flag wins over
`CLAUDE_PROJECT_DIR`, and when the two disagree the run says so and names the tree it did **not**
look at — that disagreement is how a well-formed answer about the wrong repository reaches someone.
A `--root` that is not a directory is a `FAIL` line, not a crash: the run continues and every
config-dependent check below reports itself unmeasured.

Do not summarise away any line. Each is one of three states:

- `OK` — checked, and fine.
- `WARN` — the check ran and could not answer, or found a gap that is not fatal.
- `FAIL` — checked, and broken.

A `WARN` is not a pass. If the output ends in `VERDICT: could not run`, the diagnostic itself did not
execute — say that plainly rather than reporting the repo as healthy, because nothing was measured.

**`not checked` is the third state, and it is not a clean result.** A line reading
`clone: not checked -- .oss.json was not found` means that check never ran. Five of them say it:
`clone`, `worktree_root`, `state_file`, `CI enforcement` and `owned files`. Relay them as gaps in
the measurement, not as findings about the repo — the config they would have been measured against
was absent, so nothing below them is evidence either way. `clone` and `worktree_root` are paths on
one person's disk and live in the untracked `.oss.local.json`, not in the committed `.oss.json`, so
that is the file to look in when one of them is wrong.

If `.oss.json` is missing, the fix is `/oss:setup`. Offer it; do not run it unasked — **unless** the
report also says `the enclosing clone was not searched`. That line means the run was pointed at a
tree it was not standing in, so the clone was never consulted and a worktree's config could be
sitting there untouched. Re-run from inside the tree before offering to write anything.

If instead the report says `.oss.json read from the enclosing clone`, nothing is wrong: you are
standing in a worktree and the config lives in the clone, which is where it belongs. Do not write a
second one.

## The `plugin copy` and `plugin copy scope` lines — which copy answered, not which is installed

Two lines, directly under `oss plugin version`, and they exist because that version line **cannot**
answer the question people read it as answering. The manifest version does not move between
releases, so an installed copy sitting at the tag and a clone a whole cycle past it declare the same
number — measured 2026-08-16, where the same agent report validated `ok` against one and
`schema_version: expected 1, got 2` against the other, both at `0.5.0`. Any check written as *do the
versions agree* answers `yes` in the healthy case and the skewed one alike (#262).

So the comparison is over **content**: every file under `agents/`, `commands/`, `scripts/` and
`skills/`, plus `.claude-plugin/plugin.json`, hashed with CRLF folded to LF. A difference that is
only line endings is deliberately invisible; a difference in what a command says or what a script
does is not.

**`plugin copy scope`** — what this invocation established:

- `OK … named <root>, and that is the tree doctor.py ran from` — the invocation carried
  `${CLAUDE_PLUGIN_ROOT}`, so the copy below is the one the harness resolved this command from.
- `WARN … names <a>, but doctor.py ran from <b>` — a flag or an environment variable disagreeing
  with the file that actually executed. The tree that ran is the one reported; the attestation is
  not evidence about it. **`/oss:doctor` cannot produce this state**: the launcher resolves the
  script from `${CLAUDE_PLUGIN_ROOT}` and the command passes the same variable, so the two agree by
  construction. It fires for a hand invocation naming a root, and for a script run out of one
  checkout inside a session that exported `CLAUDE_PLUGIN_ROOT` pointing at another — which is the
  ordinary shape of running a worktree's `doctor.py` from a maintainer session.
- `WARN … not established` — nobody named a root, so the copy below is inferred from the script's
  own location. That is the ordinary state of `python3 scripts/doctor.py` run by hand, and it is a
  gap in the measurement rather than a fault in the repo. Do not relay it as a finding about the
  code.

Every one of the three ends with the same sentence, and it is the half that closes #248: **this is
one command's copy, and nothing here says which copy answered any other command or skill in this
session.** A command's text is resolved once, at invocation, and stays in the turn for its whole
length — `/reload-plugins` moves the registry and does not move text already injected. A session can
therefore hold a registry at one version and instructions from another, and this line reports one
command, not the session. Reading it as a session-wide clearance is the same defect one layer up.

**`plugin copy`** — what the comparison found. Six states:

- `OK … are identical over N compared file(s)` — the copy that answered and the checkout being
  diagnosed carry the same bytes.
- `WARN … SKEW — … differ in K of N compared file(s): …` — they do not, and the line names the
  files and the version that hid it. **This is a report, not a refusal, and that is deliberate**:
  disagreement is the normal state for the whole window between a merge and a release, so a check
  that refused to run here would be switched off within a week. What it buys is that a stale filing,
  a report refused by an older schema, or a procedure step that silently is not there stops being
  five unrelated puzzles.
- `OK … answered from the checkout being diagnosed` — you are diagnosing the plugin's own clone and
  the script ran out of it. There is no installed-copy/clone split to report.
- `OK … not a checkout of this plugin` — the ordinary case in a managed repo. The repo has no
  `.claude-plugin/plugin.json`, or declares a different plugin, so there is nothing to compare
  against. Reported rather than left silent, because a comparison that was never made and one that
  found nothing print the same thing otherwise.
- `WARN … could not be determined … so nothing was compared` — a manifest that would not read or
  would not parse on either side. The third state: not clean, not a skew.
- `WARN … could not be answered — N path(s) could not be read` — the walk could not enter part of a
  tree, so the files it did compare match and the ones it could not see are unknown. Never relay
  this as identical.

**What to do with a `SKEW`.** Nothing in the repo is broken by it. What it changes is what you may
trust: any plugin prose quoted from the running session may be text this clone no longer contains,
which is exactly how #240 was filed against a sentence removed a release earlier. Quote from the
clone at a named sha before filing anything about this plugin's own documents.

## The `interpreter architecture`, `cpu topology` and `worker sizing` lines

Three lines about the machine this process is running on rather than the repository, so they
answer on a repo that has never run `/oss:setup`. They exist because both facts were decisive
in an incident and neither was printed anywhere (#367).

**`interpreter architecture`** — three states, and the third is the point:

- `OK … running natively (host architecture arm64)` — the process architecture is the host's.
- `WARN … running under binary translation (host architecture arm64)` — Rosetta 2, or its
  equivalent. Measured on the machine this was filed from: roughly **3x on interpreter startup
  and 3.4x on the CPU cost of a subprocess spawn**. This loop is subprocess-shaped, so it is
  the dominant term, and the remedy is a native `python3` rather than anything in the repo. It
  is a performance fact, not a fault: nothing is broken and everything is slow, which is why it
  goes unseen for months.
- `OK … was NOT probed` — no probe is implemented for this platform, so nothing was attempted
  and nothing will be until somebody writes one. **Do not read this as native.** `platform.machine()` cannot answer the question and neither
  can `uname -m` from a subprocess: an emulated process is shown the *emulated* architecture and
  so is everything it spawns, so the comparison is one number against itself. The probe used on
  macOS is the `sysctl.proc_translated` flag, read in-process; Linux (qemu-user) and
  Windows-on-ARM have no equivalent this script reads, so both report the gap rather than
  clearing the machine.
- `WARN … was NOT probed -- sysctl.proc_translated could not be read (errno N)` — a probe that
  **does** exist here, ran, and did not answer. Same sentence, different level, and the
  difference is the whole point.

**Why those last two are two states.** They were one, reported at `WARN`, for exactly one round
of CI. That made `VERDICT: ok` unreachable on every Linux and Windows leg forever — which does
not add a finding, it removes a signal: a verdict that always reads `usable with gaps` can no
longer carry a real WARN, so every genuine gap on those platforms is masked by a permanent one.
That is this repo's own defect class pointed at the verdict line rather than at a check, and it
is a bigger absence than the one the WARN was reporting.

So a gap that is **unobservable in principle here** is named on an `OK` line and does not spend
the warning count — the shape `agent_dispatch` already uses in this file, where whether a session
can dispatch to an agent is unreadable by any script and is stated on the line rather than
converted into a permanent warning. A probe that **exists and failed** keeps its `WARN`, because
it has a cause worth chasing. Neither line ever contains the word *native*, and a test pins that.

The earlier version of this paragraph said that if the standing WARN proved to be noise, the thing
to change was the probe and not the state. **That was wrong, and CI is what showed it.** It framed
the choice as WARN-or-silence when a third shape already existed one screen up in the same file;
and it cannot be carried out anyway — Windows has a real probe available (`IsWow64Process2`), but
every Linux qemu-user self-detection worth having is a heuristic that fails toward *clean*, which
is a confident wrong answer and strictly worse than a named gap.

**`cpu topology`** — the logical core count, split into performance and efficiency cores where
the platform exposes it (macOS does; the line says so explicitly when it does not, rather than
omitting half the sentence, which reads the same as a machine whose split nobody looked for).
Three states of its own, and the third is separate on purpose: `OK … N logical core(s) -- P
performance + E efficiency`; `OK … reports no performance/efficiency core split`; and `WARN …
whether they are split … could NOT be determined`, when the `hw.nperflevels` probe ran and did
not answer. The second and third are one sentence apart and mean opposite things — the second
says the count below sizes against uniform cores, the third says nobody established that.
`WARN` too when no core count could be determined at all.

**`worker sizing`** — what `pytest -n auto` would request **here**, and where that number came
from. It is a transcription of xdist's own order: `PYTEST_XDIST_AUTO_NUM_WORKERS` first, then
psutil's *physical* core count, then `os.sched_getaffinity(0)`, then `os.cpu_count()`. Two
things it is there to say. The cap exists and is read before any core is counted, which you
have to know is there; and on a machine with an efficiency-core split the number exceeds the
performance cores, while **several agents running suites concurrently each size against the
whole machine without seeing each other** — the doctor cannot count the other agents, and does
not pretend to. `WARN` when the count is unknown; the count is never invented as 0 or 1.

## The `watch channel` line

One line, twelve states, and none of them is a claim about which pollers are running. It compares
three places — a `watch_name` in this repo's `.supertool.json`, `SUPERTOOL_WATCH_NAME` in the
environment this run inherited, and the `repo` in `.oss.json` that `bin/oss-workspace` derives a
name from (#191) — and reports which channel the repo resolves to. The name derives a
socket and a poller-slot directory held by exactly one process, so repos resolving to one name share
one fleet while each board renders as its own. That is the whole reason the line exists: the shared
case and the private case are otherwise indistinguishable from inside either repo.

- `OK … and they match` / `declared in .supertool.json and nothing is exported over it` — fine.
  Neither says the fleet is private; nothing here enumerates pollers, and `supertool 'channel:health'`
  is what answers delivery.
- `OK … bin/oss-workspace exports a name derived from it` — nothing declared and nothing exported,
  but `.oss.json` carries a `repo`, so a session this launcher opens gets a socket of its own. It
  covers sessions the launcher opens and nothing else: a `claude` started by hand in the directory
  exports nothing and lands on the shared default.
- `WARN … binds the SHARED default socket` — nothing declared, nothing exported, and nothing to
  derive from. This used to read `OK … Nothing is broken`, and it was measured saying exactly that
  on a repository where five events were read, five forwarded, zero dropped and none delivered
  (#191). One process holds that socket, the first one wins, and the loser is never told. The line
  names which of six reasons applied — no `.oss.json`, one this process could not read, one that read
  and parsed and is not an object, one with no `repo`, one whose `repo` the validator refuses, or a
  validator that would not import — because the remedies differ. The second and third are separate
  since #216: a mode and a shape are not the same errand.
- `OK … so this is the export bin/oss-workspace makes for this repo` — an export with no
  declaration beside it, and it is **exactly** what `.oss.json`'s `repo` derives to. Since #192 this
  is the ordinary state of every managed repo, and it used to render as the accusation below.
- `WARN … it is not what .oss.json's repo derives to` — the filed case (#150), now earned by a
  comparison rather than inferred from an absence. A hand-copied `.claude/settings.local.json` puts
  one name into several repos, and each of them then reports a fleet that is not its own.
- `WARN … whether this is the export bin/oss-workspace derives … is unknown` — an export is set and
  there is no `.oss.json`, or it cannot be read, or it read and parsed and is not an object, or it
  carries no `repo`, or its `repo` is one the validator refuses, or the validator would not import —
  so there is nothing to compare against. Not answered as copied, which would accuse on no evidence,
  and not as derived, which would clear on none. The line names which of the six it was, and since
  #216 "could not read it" and "read it, and it is the wrong shape" are two of them.
- `WARN … declared in .supertool.json, exported as SUPERTOOL_WATCH_NAME and the two differ` — the
  export wins for pollers spawned here, so this repo's declaration is not in effect.
- `WARN … op blocks … declare N distinct names` — `bin/oss-workspace` exports none of them rather
  than picking. Leave one.
- `WARN … SUPERTOOL_WATCH_SOCK … is set, which overrides the name entirely` — deliberate on
  supertool's side, because that path is what a running poller already captured. It still means the
  comparison above decides nothing, so it is not reported as agreement.
- `WARN … .supertool.json is there and could not be read` — the read or the parse failed. Not
  `declares none`: that reads as a repo on the default channel, and it is not one.
- `WARN … .supertool.json is not an object` / `` `ops` in .supertool.json is not an object`` — the
  file **was** read and it did parse; only its shape is wrong. Reported separately from the line
  above since #216, where both shapes said *could not be read* and sent the reader to permissions, a
  lock or an encoding rather than to the document. Two failure states exist because they have
  different remedies, so collapsing them costs exactly what having them buys. `scaffold.check_radar`
  has always answered this shape correctly; it is `doctor` that was wrong, and the fix went here.

**No name is ever printed** — the declaration, the export, both places to look, and nothing the
diagnosed repo wrote. The remedy is always in one of the two places the line names.

The plugin does not configure this. `.oss.json` describes a repo's release and review process and a
watcher socket is neither, and `.supertool.json` already carries the name to supertool's own ops
with no plumbing. Do not offer to write the name into `.oss.json`; there is nowhere for it to go.

**One thing neither line establishes**, and it is the half that decides delivery: *which process*
holds the socket. `supertool 'channel:health'` performs a socket-holder probe and reports its own
limit in as many words — *"NOT established: that the configured server is the one holding this
socket. Two channel-capable servers would satisfy both halves apart."* That was the live state in
#191: events read, forwarded and discarded, with nothing red anywhere. The diagnostic declines the
question rather than guessing at it — answering it needs `lsof`, `ps`, a walk up a process tree and
the harness's own server name, none of which exist on every platform and none of which doctor is a
reliable child of — and it prints the decline rather than leaving it in a comment.

## The `radar board` line

The channel and the board are two questions (#191). The channel line above says *where* events would
go; this one says whether anything ever puts one there. Two halves have to hold and each is silent
about the other: a tier has to be **registered** in `ops.radar.radar_tiers`, and the op reading it
has to be **routed** here by the `watch` preset. A repo with neither renders exactly like a healthy
one — a session opens, `watches` shows a fleet, `channel:health` says FORWARDING, and nothing has
ever published. That question lived until now as one line of session-start stderr from
`bin/oss-workspace`, matched by a `grep` that also hits the word inside an unrelated key.

- `OK … registers a board and a route to it` — both halves. It reads one declaration: it does not
  run `radar`, does not reach a forge, and does not establish that any tier has ever emitted.
- `WARN … registers no tier` / `there is no .supertool.json here` — nothing publishes. The line
  carries the block to add.
- `WARN … does not enable 'watch'` — tiers are registered and the op has no route here, so they
  cannot run. Half a board is not a board.
- `WARN … presets … is absent or not a list of strings` — the third state for the route half.
  Answered neither as routed nor as unrouted, because `no-route` would send you to add a preset
  that may already be in effect.
- `WARN … is not an object` — a file somebody edited and broke, which is a different answer from a
  repo that registers none and has a different remedy.
- `WARN … could not be read` — the third state. Not `registers none`.

No tier name is ever printed. `.supertool.json` is contributor-writable in a managed repo, and a
tracked file must not get to write the diagnosis.

`/oss:scaffold` asks the registration half of this at scaffold time and names the same block; the
route half and the read-failure states are asked only here.

## The `channel MCP registration` line

The watch channel line above says *which name* this repo resolves to; the radar board line says
*whether a board is declared*. Neither asks whether any MCP server actually carries either into a
session — until #621, `grep mcp scripts/doctor.py` returned nothing, so a maintainer could get a
clean reading on both of those lines and still have no working channel, because the one thing that
carries it — a `claude mcp` registration pointing at `claude-channel/channel.ts` — was never asked
about here. `bin/oss-workspace:873-944` already asks it, at session-open, on stderr; this line asks
the same question where a maintainer running the diagnostic can actually see it.

- `OK … is registered pointing at … which exists` — the registration is real and the file it names
  is there. This confirms the registration and the file; it does not confirm the consumer starts,
  that `bun` is on PATH, or that anything is listening on the socket — the same limit the watch
  channel and radar board lines each carry about their own reads.
- `WARN … is not registered` — nothing carries the channel into a session. `bin/oss-workspace`
  registers it at session-open; the line also names the `claude mcp add` command directly.
- `WARN … which does not exist` — the registration outlives the file. `claude mcp get` answers 0
  for any configured server whether or not the file it names still exists, because the path
  `claude mcp add` stores is absolute and version-pinned and the plugin cache drops the old version
  directory on update. The remedy is `claude mcp remove … -s local` and opening a session again to
  re-register at the current path.
- `WARN … no Command or Args line could be read` — registered, but where it points could not be
  parsed (the shape a project-scope entry also prints). Not the same as absent: the comparison
  failed, the registration did not.
- `WARN … the filesystem would not say whether it exists` — the third state on the target check
  itself: a permission-denied ancestor or an unreadable path, reported as unknown rather than as
  confirmed gone.
- `WARN … so whether … is registered is unknown` — `claude` is not on PATH, or the call itself did
  not run. Never relayed as "not registered": that would claim an answer nobody was in a position
  to give.

This reads the registration only. It performs no registration and no removal — `bin/oss-workspace`
owns that — and it makes one real `claude mcp get` call per run, which is a fact about the machine
this diagnostic runs on, not about the repo being diagnosed.

## The `channel consumer pin` line

The registration line above confirms the pinned path *exists*; it never compares the *version* that
path is pinned to against the version supertool is actually installed at (#646). A pin left over
from an earlier update stays `OK` twice over — registered, and the file it names still there —
right up until the plugin cache drops that version's directory, at which point the registration that
looked healthy stops resolving with no warning beforehand. This line only runs when the registration
line above resolved to `registered`; every other registration state already has nothing to compare.

It asks the registration a second time rather than reusing the answer above: each check is testable
and stubbable on its own, the same pattern every sibling check in this file already follows, so this
line makes its own `claude mcp get` call. Two real calls per run, not one — accepted rather than
optimised away, because sharing one answer between the two checks was tried and reverted for
breaking that independence.

- `OK … matching the active install` — the pinned version and the active install agree.
- `WARN … SKEW …` — they differ. The line also says whether the two files are byte-identical,
  computed by hashing both rather than assumed: identical means the drift is cosmetic and
  re-registering is a convenience; not identical means the consumer actually running is not the one
  installed. **Not a hard failure** — a deliberate pin to an older copy is a legitimate choice, the
  same way `./supertool` pointing at a local checkout is one, and this only names it.
- `WARN … whether its pinned version matches the active install is unknown` — the third state: no
  `.claude-plugin/plugin.json` could be found walking up from the registered path, its version could
  not be read, no active version could be read to compare against, or neither parsed as a version.
  Never folds into `OK` — an unparseable pair is not evidence of a match.

The pinned version is read from the registered install's own manifest, found by walking up from the
registered path, rather than matched out of a path segment that happens to look like a version.

## The `dependency diagnostic` lines

`declared_dependencies()` already reports a version per dependency elsewhere in this run — that
answers "what is installed", not "is it working". Every declared dependency ships a diagnostic of
its own (`supertool`'s `doctor` op, `remember`'s and `claude-jit-context`'s versioned `doctor.sh` /
`jit-doctor.sh` scripts) and until #638 nothing here ever ran it. One line per declared dependency:

- `OK … <version>: <the dependency's own verdict line>` — its diagnostic ran and answered. The
  verdict is relayed verbatim, never re-derived — `claude-jit-context`'s documented exit codes (0
  nothing inert / 1 a layer the matcher can never load / 2 SKIPPED) are carried through rather than
  flattened into a boolean, and `remember`'s own trailing `VERDICT:` line (its script always exits 0
  by design, so the exit code alone is not the signal) is what is relayed.
- `OK … not installed` — an ordinary state, not a finding: nothing here says every declared
  dependency must be installed everywhere this runs.
- `WARN … could not run …` — installed, and still did not answer: no `supertool`/`bash` on PATH, its
  script is not where the install record says the dependency is, it timed out, or it exited outside
  its own documented contract. **Never folds into `OK`** — a diagnostic that gave up quietly must not
  read the same as one that reported clean.

Measured combined runtime on the machine this was written on is under 1s, so this runs on every
invocation rather than behind a flag or a slower clock.

## The `owned files` lines, and what to do about them

Owned files — `.oss/README.md`, `.oss/assemble_changelog.py`,
`.github/workflows/oss-changelog.yml` — are replaced wholesale by `/oss:scaffold`, so a fix
shipped here reaches a repo only when somebody re-runs that command there. These lines are
the only thing that tells a maintainer the re-run is worth doing, so read them as an answer
to that one question rather than as a tidiness report. Seven things they can say:

- **Nothing** — the copies match what the plugin ships today. There is no `owned files` line
  to relay.
- **`not in this repo. Run /oss:scaffold.`** — a gap. The repo was scaffolded before these
  files existed, or never scaffolded at all, and re-running writes them.
- **`absent on purpose`**, at `OK` rather than `WARN` — this repo already runs a changelog
  gate under another name, so `/oss:scaffold` declines the trio and will decline it again.
  Do **not** relay this as something to fix: the remedy for an ordinary gap is the command
  that produced this state, and a warning naming it would appear on every run of a correctly
  configured repo forever (#126). `/oss:scaffold --force-owned` is the only thing that
  changes it, and only a maintainer who checked the match by hand should pass it.
- **`would change what it does -- <names>`** — re-running changes behaviour, and the names
  are the regions: a YAML key path like `on.pull_request.types`, a Python definition, a
  Markdown heading. This is the one to act on. A repo scaffolded before the current release
  can have a changelog gate that is satisfied by *deleting* somebody's pending fragment, and
  this is the line that says so. Offer `/oss:scaffold --apply`.
- **`would change comments and prose only -- nothing it does changes`** — a real difference
  with no behavioural consequence. Worth mentioning; not worth interrupting anything for.
- **`could not be read` / `no comparison was made`** — the third state. Either the plugin's
  own copy was unreachable or theirs was, so **nothing was compared**. Never relay this as
  up to date. `/oss:doctor` can run under a plugin version different from the one that
  scaffolded the repo, and a check that cannot see our copy must not vouch for theirs.
- **`whether /oss:scaffold would write it could not be determined`** — the same third state,
  one question earlier. The file is absent and the gate check could not answer whether that
  is a gap or a decision, so it is reported as neither. This is not `absent on purpose`:
  scaffold also declines when it could not look, and a decline nobody took must never be
  relayed as a choice somebody made.

Two things the line deliberately does **not** say, because neither is measurable from inside
a managed repo: whether their copy is *older* than ours, and whether somebody *edited* it.
Nothing in the repo records which plugin version wrote the file, so those two are the same
observation and guessing between them means telling a maintainer to discard their own work.
The line describes the **effect of re-running**, which is true either way — and carries the
caveat that a deliberate edit goes with the re-run, because owned files are replaced
wholesale and the maintainer is the only one who knows whether they made one.

## The `jit rule layer` line — indexed is not read

`.claude/jit-context/*/01-oss/` is this plugin's own rule layer. The check above it answers *will
the matcher find these rows*; this one answers the question nobody asked until #119, which is
*does anything look in that directory at all*. For the whole life of the layer the answer was no:
`claude-jit-context` enumerated layers from a fixed list of four names in three hooks and `01-oss`
was not one of them, so every rule in it was written, indexed, reported clean — and read by nothing.

It is measured against the hook scripts of the installed version, not inferred from a version
number — and **against the hooks the runtime actually executes**, which is narrower than the files
under its install root and is the distinction the check turns on. A layer list living in the
dependency's own test fixtures satisfies nothing: it would read the same whether the hooks
enumerated `01-oss` or not, which is how this line came to be right by accident (#241). Four things
it can say:

- **`… names 01-oss in its layer list …`**, at `OK` — the rules are reachable. The list was found in
  a hook the dependency declares in its `hooks/hooks.json`, or in a file one of those `source`s.
  Anywhere else under the install root is not this state.
- **`… enumerates layers from a fixed list that does not include 01-oss …`**, at `WARN` — a real
  gap with a real consequence. Treat every rule in that layer as inert until an installed version
  fixes it. The fix belongs to `claude-jit-context`, not here, so there is nothing to run: this is
  a line to believe, not a line to act on. It clears itself on the next dependency update that
  carries the fix, which is why it is a `WARN` and not the permanent `OK`-with-a-caveat that
  `agent dispatch` carries.
- **`… could not be determined …`**, at `WARN` — nothing was measured, and **the line always names the
  reason** — read it rather than the verdict. Some are about reaching the dependency at all: it is
  not in the install record, its unpacked tree was not found, a hook file would not decode, or the
  hooks carry no fixed layer list. Others are about reaching its *hooks*, and they are distinct
  answers rather than one: it declares no hook manifest at all, so nothing separates a hook from a
  fixture; the `hooks` path its `.claude-plugin/plugin.json` declares is one this refuses to
  resolve — and it does **not** quietly fall back to the conventional location, because reading a
  file the plugin did not name is this check's own defect one directory over; the manifest would
  not parse; the manifest parsed and named nothing resolvable; or **a layer list was found, and
  only outside the hook set** — reported as the reason rather than dropped, because a string in a
  test fixture is evidence about the fixture and about nothing else. **That last reason is what this
  repository's own `doctor` prints today.** The no-fixed-list one is the expected shape of the
  upstream fix, so it too is *unknown* rather than a pass **or** a gap.

  Either terminal message may also end with `N path(s) under it could not be walked or read (…), so
  this did not see the whole tree`. That is a modifier, not a reason: it says the scan behind the
  sentence was incomplete, which is the difference between *looked everywhere and found nothing* and
  *could not look everywhere*.

  Do not relay any of these as a pass or as a gap — an incomplete scan never settles this question,
  and a scan that found the right string in the wrong file has not looked where it matters.
- **`this repo has no .claude/jit-context/*/01-oss/ …`**, at `OK` — nothing to read, so nothing to
  warn about. `/oss:scaffold` writes the layer if you want it.

Two of the warnings are about CI rather than about setup, and neither is cosmetic:

- **A `test_command` that no workflow runs.** Green then means the changelog was checked
  and the tests were not run — an absence that reads exactly like a pass on the merge
  screen. The fix is a workflow you write; the doctor will not write one.
- **A leftover `ci` block in `.oss.json`.** `ci.required_checks` was deleted in #113 and
  nothing reads it. The config still validates with it — a key going away must not break
  a repo that did nothing — but the number is dead, and a dead measurement on disk reads
  exactly like a live one. Delete the block. The leg count is read off the pull request
  it applies to, with `gh pr checks`, because nothing offline can produce it: a build
  matrix expands one job declaration into many, a reusable workflow declares nothing
  locally, an organisation- or app-level check never appears in `.github/workflows/` at
  all, and a run that has not happened declares nothing either.
