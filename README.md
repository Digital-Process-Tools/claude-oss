# claude-oss

> Run an open-source repo as its maintainer. Triage the tracker, delegate the work, review hard, merge on green.

![Version](https://img.shields.io/badge/version-0.7.0-orange)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![OS](https://img.shields.io/badge/os-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/license-Community-green)

---

## The problem

A maintainer loop written as prose gets copied between repos, and the copies drift. Fixing a triage
rule means editing it in three places and remembering the third. Repos that never got the copy run
no loop at all.

This packages the loop once: one skill, the agents it delegates to, a handful of commands.
Everything that differs between repos — default branch, label spellings, version sites, test
command — lives in a config file the plugin writes by probing the repo, not in the prose.

## Install

```
/plugin marketplace add Digital-Process-Tools/claude-marketplace
/plugin install oss@dpt-plugins
```

**Then run `/reload-plugins`, or restart Claude Code.** Plugin registrations are read once at
session start, and installing mid-session leaves the agent registry as it was.

That step is not cosmetic, because **its failure does not look like a missing step.** In a session
that installed the plugin and never reloaded, all seven `oss:` skills resolve and none of the four
`oss:` agents does — which reads as a plugin that is installed and working with a broken `agents/`
directory, and has already produced two wrong bug reports against this repo (#140). If a spawn comes
back `Agent type 'oss:...' not found`, reload before concluding anything about the files.

Installing pulls in `supertool`, `remember` and `claude-jit-context` automatically — they are
declared dependencies and resolve from the same marketplace.

## After cloning a repo you maintain

Install the launcher once, from this plugin's own checkout:

```
ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace
```

**That line is POSIX-only, and there is no Windows equivalent to substitute for it**
(#330). `bin/oss-workspace` is a `/bin/sh` script, so on Windows it runs under Git Bash
rather than cmd or PowerShell, and the `~/.local/bin` convention it links into is on no
Windows `PATH`. On Windows, run it from this checkout instead -- `sh bin/oss-workspace`
-- and `/oss:doctor` prints that as its remedy there rather than a command that would do
nothing.

Then, in any repo you maintain:

```
cd the-repo
oss-workspace
```

Without that symlink the launcher is only on the path it ships at, so run it as
`bin/oss-workspace` from this checkout.

That link is resolved once, against a directory a later release will not write to --
`$PWD` there is this plugin's own installed checkout, and a plugin manager's cache
layout is version-scoped. Nothing re-points the symlink on an update and nothing
checked it until now: a stale target that still exists behaves exactly like a current
one, silently. `/oss:doctor` now reports it, in `oss-workspace launcher: ...`, in six
states -- matched; a skew naming both versions; not on PATH at all; **part of PATH could
not be read, so whether it is reachable is unknown rather than absent** (#333, and that
one must never render as "not on PATH"); and one each for this install's own copy or the
resolved target being unreadable. Its remedy line names the *running* install's own path
rather than `$PWD`, so pasting it works regardless of where you are standing when you
paste it -- and on Windows it is the sentence above rather than a `ln -sf` that would do
nothing. That remedy is paste-ready even when the install path itself is not ASCII (#344):
it is composed by the diagnostic from its own resolved location, not text from the repo
being diagnosed, so it is exempt from the ASCII fold every OTHER finding still goes
through -- folding it would have turned a non-ASCII path into `?`, a shell glob that
either fails to match or links a file you never named.

That opens a session over the repo you are standing in, with the maintainer loop already running — or
with `/oss:setup` if the repo has no `.oss.json` yet, because a tick against guessed values merges
into the wrong place confidently.

Setup is not the whole onboarding. It deliberately writes nothing tracked, which is what makes it
safe to run anywhere and also what leaves the repo half-furnished — configured, and still without a
CLAUDE.md, a security policy, issue templates or a changelog gate. **`/oss:scaffold` is the second
step**, and it is separate because it writes tracked files: they want a branch, a diff and a review.
A repo that goes straight from setup to ticking never fails; it just runs the loop against furniture
nobody added.

So setup does not merely recommend the second step: it ends by running scaffold's own read-only plan
and relaying it. Nothing is written — the gap arrives as a measured per-file list (`create`,
`present`, `replace`, `decline`) rather than as a sentence suggesting you go and look, and a plan
that could not run is reported as unmeasured rather than as nothing to do. Writing still happens only
under `/oss:scaffold`.

It does **not** set up a board. The session is started able to receive watch-channel events, but
`radar` reads its tiers from that repo's own `.supertool.json`, and a fresh clone has none. The
launcher says which of the two is missing rather than reporting the session as armed — a channel
nobody publishes to looks exactly like a quiet board.

The channel's **name** gets the same treatment, because a name that does not arrive intact puts the
session on the socket shared with every repo that declares none, which renders as a quiet board too.
One rule decides what a name may be, and both roads reach it: a `watch_name` declared in the repo's
`.supertool.json` and a name derived from `repo` in `.oss.json` are checked by the same function, and
a value that cannot be used as a path component is refused out loud rather than exported. A refusal
names the channel the session **actually** landed on rather than assuming the shared one: an already
exported `SUPERTOOL_WATCH_NAME` wins over both roads, so a refusal there costs nothing and the session
stays on that channel, and the receipt says so. There is a third road out of the declared route too — a
name a repo declares and this console's encoding cannot carry. The name is read back through the
launcher's own stdout, so an unencodable one cannot arrive at all; it is reported as declared-and-
unrenderable rather than printed mangled or silently derived over, because a declaration that exists
is not a declaration that is absent. What that rule deliberately does not decide is whether supertool
will *accept* the name — it has its own
pattern, with a length cap. Rather than carry a copy of it here to go stale, the launcher reads that
rule out of the installed supertool and reports what it finds, in three states: accepted says
nothing, a name the consumer will discard is named with its length and the rule that refused it, and
**not being able to ask** — no rule where the launcher looks, a module that will not load — is said
just as loudly, because silence there is indistinguishable from acceptance.

Before the session starts working, the launcher runs `/oss:doctor`'s diagnostic over the repo it just
resolved, so a broken setup surfaces at second zero rather than after a tick has been spent against
it. The verdict is parsed, never the exit status: the diagnostic **exits 0 always**, by contract, so
`doctor.sh || warn` reads a pass on `not usable -- 4 failure(s)` exactly as loudly as on `ok`. A
healthy repo costs one line; anything else relays the diagnostic's whole output, because once the
answer is not `ok` a launcher has no standing to decide which line you needed. It **never refuses to
open** — a maintainer whose config is broken is exactly the person who needs a session in which to
fix it.

Six answers, and the last three are why this is not a one-liner: `ok`, `usable with gaps`, `not
usable`, `could not run`, a verdict word this launcher does not recognise, and **no verdict line at
all**. That last one splits again by whether the diagnostic printed nothing or could not be started,
which the launcher tells apart and says. A check that never fired and a check that found nothing
print the same thing otherwise.

It costs what the diagnostic costs. Measured on macOS against a repo with `supertool`, `gh` and node
on PATH: the launcher opens in **0.45 s** without it and **2.5 s** with it, most of that the
dependency-version check reaching the network — which is bounded at 25 s per declared dependency and
20 s per probed binary, so an offline or hung network is slower than that, not faster. Set
`OSS_WORKSPACE_SKIP_DOCTOR=1` (any non-empty value) to skip it — the skip is announced, with the
state of the repo reported as unknown rather than fine. The run is also announced *before* it
starts, carrying that variable's name, because an escape hatch you can only read about after the
wait is one nobody waiting has.

Install the launcher once, from this plugin's own checkout -- see "After cloning a repo you
maintain" above for what a stale symlink costs and how `/oss:doctor` now catches it:

```
ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace
```

POSIX only, for the reason given above: on Windows `bin/oss-workspace` is a `/bin/sh`
script that runs under Git Bash, nothing puts `~/.local/bin` on a Windows `PATH`, and
there is no one-line install to substitute -- run `sh bin/oss-workspace` from this
checkout (#330).

The working directory is the selection: it opens *that* repo, never this plugin's checkout.

## Commands

| Command | What it does |
| --- | --- |
| `/oss:tick` | One pass of the maintainer loop: board, decide, delegate, review, merge on green. |
| `/oss:setup` | Probes the repo and writes `.oss.json`. Measures; never assumes — a version site is a file read and found to carry a version, and every label that matched no pattern is named. |
| `/oss:scaffold` | Adds the missing repo furniture. Never overwrites; shows before it writes. Reports what it will not do: create a label, guess a required-check count, or generate a test workflow. Its receipt reads both halves of the board question, so a repo it scaffolded before the preset was added — tiers registered, no route to the op that reads them, and unreachable by a template fix because `.supertool.json` is never replaced — is reported rather than called clean. |
| `/oss:triage` | One triage sweep — priority, lane, milestone, the clusters one change would fix, the cohort burn-down with the limit it was counted under, and what the board is lying about. |
| `/oss:changelog` | Checks changelog fragments, or folds them for a release. |
| `/oss:release` | Gates, version sites, tag, and — where `.oss.json` says so — the GitHub Release, notes and all. |
| `/oss:doctor` | Config, dependencies, clone, worktree root, state file — including whether `/oss:tick` can actually read it, which is not the same question as whether it is there — which watch channel this repo resolves to, which decides whether its board is its own fleet or somebody else's, and whether anything publishes to that board at all: a registered radar tier is one half, a route to the op that reads it is the other, and a channel with neither renders exactly like a healthy one. Which *process* holds the socket is not established, and the output says so. Also **which copy of this plugin answered the invocation** — compared by content, because two copies a whole release cycle apart declare the same manifest version, and reported for one command rather than for the session. And **`./supertool`**, which is not the same question as `supertool` on PATH: it is gitignored on purpose, every brief tells an agent to call it, and a link pointing somewhere other than the plugin's copy is a different failure from no link at all. Where a defect in this plugin itself gets filed is reported too — derived from its own manifest, never inferred, and *could not determine* is said rather than rendered as *no tracker*. Exits 0 always. |

## Status

**Tested, not proven.** The claim this section used to make — that no real issue had gone from
triage through to a merge — stopped being true some time before anyone edited it: the loop now
maintains this repository, and the triage-to-merge round trip has run many times over, including
the releases cut with `/oss:release`.

What that does *not* establish is the part most users care about. Almost everything this plugin
claims about a repository it has **scaffolded** still rests on tests and scratch runs rather than on
a repo somebody maintains through it; owned files are known to have gone stale in the field, in
every repository carrying them, with no observed repair in any of them.

The measured version of that, with each claim graded observed or reasoned and dated to the commit
it was taken at, is **[What is not proven yet](CLAUDE.md)** — re-derived at each release rather than
edited. It is deliberately not restated here: a second copy is the one that drifts, and this
section is the proof of it.

**Installing this plugin does not put a maintainer loop in your repository.** The workflow it
installs is a changelog gate that fires on a pull request; every other step of the loop is a slash
command somebody types. The one thing it starts on a clock is a `.github/dependabot.yml`, seeded
once if you do not already have one and yours to delete — and nothing here reviews or merges what
that opens. The gate exempts pull requests **opened by `dependabot[bot]`** from the fragment
requirement, announcing the skip in its own log rather than passing silently: a bot cannot use the
`no-changelog` escape hatch, because its own labels fail the run before a human can apply one
(#293). If you point dependabot at a runtime ecosystem rather than `github-actions`, a bump that
*is* user-visible will announce nothing, and that log line is where it shows.
Nothing schedules a tick, a re-scaffold or an update of an owned file, so a repository
that installed the plugin and was never ticked again looks, from here, exactly like a healthy one.
What that would take is recorded in
**[Autonomy: what the loop reaches, and what it does not](docs/autonomy.md)**, which is a record of
the gap and deliberately not a design.

## Development

```
python3 -m pytest tests/ -q
```

CI runs the suite on ubuntu, macOS and Windows across Python 3.9-3.12. A green macOS run is not
evidence on its own.

A separate ubuntu leg runs `bash -n` and `shellcheck -S warning` over every tracked shell source.
Which files those are is derived rather than listed — `python3 scripts/shell_sources.py` prints the
list, selecting by extension or by shebang so an extensionless script is covered by the commit that
adds it. It exits non-zero when it matches nothing, so an empty selection fails the leg instead of
linting no files and passing.

That leg installs nothing. `shellcheck` ships in the `ubuntu-latest` runner image, and fetching it
anyway put a package-mirror round trip inside the job's `timeout-minutes`, which is what took the leg
— and with it every pull request — down for a day (#303). If the binary is ever missing the step says
so and exits `4`, rather than collecting one `command not found` per file into the same status a real
finding uses.

`python3 scripts/transcript_refusals.py` counts refused tool calls across this machine's own agent
transcripts — by class (`path-escapes-cwd`, the raw-command guard, the no-cut block,
`unavailable-here`, a jit-context block, or a residual `ERROR:`), by model (read only from each
turn's own `message.model`, never inferred), and the batching lever #313's own last comment
measured: runs of *consecutive* single-op read calls and the turns one batched call would have
collapsed. Nothing about which repository or which user is hardcoded — the transcripts root is
derived from `Path.home()` and the invoking `cwd`, or passed explicitly with `--root`. Its own
third state is the point: a directory with no transcripts (`no-transcripts-found`) must not read
like a directory full of transcripts that refused nothing (`measured`, `refusal_totals: {}`).
The same rule governs `--agent`: `transcripts_parsed` counts what the parser read, before the
filter, so `transcripts_found - transcripts_parsed` is always `len(unreadable_files)` and a file
the filter excluded is never reported as one that failed to parse (#374). What the filter matched
is its own number, `transcripts_matched_agent_filter` — `null` when no filter was passed, `0`
when one matched nothing, and present only in the `measured` state, since `no-transcripts-found`
has nothing to count either way.
It exists to make "does a jit-context rule for the `path-escapes-cwd` class pay for its own
injected text" a measurement rather than an assumption — see #313 for why a rule was
deliberately not added alongside it.

## License

Community License — see [LICENSE](LICENSE). Source-available, not open source: no commercial
redistribution, no competing use.

Built by Digital Process Tools in Toulouse, France.
