---
description: Diagnose this repo's oss setup — config, dependencies, clone, worktree root, state file, watch channel, radar board.
allowed-tools: Bash
---

Run the diagnostic and relay its output verbatim:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh"
```

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

## The `watch channel` line

One line, eleven states, and none of them is a claim about which pollers are running. It compares
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
  names which of three reasons applied — no `.oss.json`, an unreadable one, or one with no `repo` —
  because the remedies differ.
- `OK … so this is the export bin/oss-workspace makes for this repo` — an export with no
  declaration beside it, and it is **exactly** what `.oss.json`'s `repo` derives to. Since #192 this
  is the ordinary state of every managed repo, and it used to render as the accusation below.
- `WARN … it is not what .oss.json's repo derives to` — the filed case (#150), now earned by a
  comparison rather than inferred from an absence. A hand-copied `.claude/settings.local.json` puts
  one name into several repos, and each of them then reports a fleet that is not its own.
- `WARN … whether this is the export bin/oss-workspace derives … is unknown` — an export is set and
  there is no `.oss.json`, or it cannot be read, or it carries no `repo`, so there is nothing to
  compare against. Not answered as copied, which would accuse on no evidence, and not as derived,
  which would clear on none. The line names which of the three it was.
- `WARN … declared in .supertool.json, exported as SUPERTOOL_WATCH_NAME and the two differ` — the
  export wins for pollers spawned here, so this repo's declaration is not in effect.
- `WARN … op blocks … declare N distinct names` — `bin/oss-workspace` exports none of them rather
  than picking. Leave one.
- `WARN … SUPERTOOL_WATCH_SOCK … is set, which overrides the name entirely` — deliberate on
  supertool's side, because that path is what a running poller already captured. It still means the
  comparison above decides nothing, so it is not reported as agreement.
- `WARN … .supertool.json is there and could not be read` — the third state. Not `declares none`:
  that reads as a repo on the default channel, and it is not one.

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
number. Four things it can say:

- **`… names 01-oss in its layer list …`**, at `OK` — the rules are reachable.
- **`… enumerates layers from a fixed list that does not include 01-oss …`**, at `WARN` — a real
  gap with a real consequence. Treat every rule in that layer as inert until an installed version
  fixes it. The fix belongs to `claude-jit-context`, not here, so there is nothing to run: this is
  a line to believe, not a line to act on. It clears itself on the next dependency update that
  carries the fix, which is why it is a `WARN` and not the permanent `OK`-with-a-caveat that
  `agent dispatch` carries.
- **`… could not be determined …`**, at `WARN` — nothing was measured. The dependency is not in the
  install record, its unpacked tree was not found, a hook file would not decode, or the hooks carry
  no fixed layer list at all. That last one is the expected shape of the upstream fix, so it is
  reported as *unknown* rather than as a pass **or** as a gap. Do not relay any of these as
  either — an incomplete scan never settles this question.
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
