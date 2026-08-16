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
