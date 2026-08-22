# claude-oss

> Run an open-source repo as its maintainer. Triage the tracker, delegate the work, review hard, merge on green.

![Version](https://img.shields.io/badge/version-0.11.0-orange)
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
that installed the plugin and never reloaded, its commands resolve and its agents do not — which
reads as a plugin that is installed and working with a broken `agents/` directory, and has already
produced two wrong bug reports against this repo (#140). If a spawn comes back `Agent type
'oss:...' not found`, reload before concluding anything about the files.

Installing pulls in `supertool`, `remember` and `claude-jit-context` automatically — they are
declared dependencies and resolve from the same marketplace.

## After cloning a repo you maintain

Install the launcher once, from this plugin's own checkout:

```
ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace
```

That line is POSIX-only, and there is no Windows equivalent to substitute for it (#330):
`bin/oss-workspace` is a `/bin/sh` script that runs under Git Bash rather than cmd or
PowerShell, and `~/.local/bin` is on no Windows `PATH`. Run `sh bin/oss-workspace` from this
checkout instead -- `/oss:doctor` prints that as its remedy there. The symlink is resolved once
against this checkout's own path, so it goes stale across an update; `/oss:doctor` now reports
that too, under `oss-workspace launcher` (#333).

Then, in any repo you maintain:

```
cd the-repo
oss-workspace
```

Without the symlink, run it as `bin/oss-workspace` from this checkout. The working directory is
the selection: it opens *that* repo, never this plugin's own checkout.

That opens a session over the repo you are standing in, with the maintainer loop already running —
or with `/oss:setup` first if the repo has no `.oss.json` yet, since a tick against guessed values
merges into the wrong place confidently.

Setup alone is not the whole onboarding: it writes nothing tracked, which leaves the repo
configured and still without a `CLAUDE.md`, a security policy, issue templates or a changelog
gate. **`/oss:scaffold` is the second step**, because it writes tracked files that want a branch,
a diff and a review -- and setup ends by relaying scaffold's own read-only plan, so the gap is a
measured list rather than something you have to remember to check.

Before the session starts working, the launcher runs `/oss:doctor`'s diagnostic over the repo it
just resolved and relays anything short of a clean pass -- see the `/oss:doctor` row below for
what it covers. It never refuses to open a session over a broken repo; a maintainer whose config
is broken is exactly the person who needs a session in which to fix it. Set
`OSS_WORKSPACE_SKIP_DOCTOR=1` (any non-empty value) to skip it -- announced either way, with the
repo then reported as unknown rather than fine. Measured on macOS with `supertool`, `gh` and node
on PATH: opening costs **0.45 s** without the diagnostic and **2.5 s** with it, most of that a
per-dependency network check bounded at 25 s.

## Commands

| Command | What it does |
| --- | --- |
| `/oss:tick` | One pass of the maintainer loop: board, decide, delegate, review, merge on green. |
| `/oss:setup` | Probes the repo and writes `.oss.json`. Measures; never assumes — a version site is a file read and found to carry a version, and every label that matched no pattern is named. |
| `/oss:scaffold` | Adds the missing repo furniture. Never overwrites; shows before it writes. Reports what it will not do: create a label, guess a required-check count, or generate a test workflow. Its receipt reads both halves of the board question, so a repo it scaffolded before the preset was added — tiers registered, no route to the op that reads them, and unreachable by a template fix because `.supertool.json` is never replaced — is reported rather than called clean. |
| `/oss:triage` | One triage sweep — priority, lane, milestone, the clusters one change would fix, the cohort burn-down with the limit it was counted under, and what the board is lying about. |
| `/oss:changelog` | Checks changelog fragments, or folds them for a release. |
| `/oss:release` | Gates, version sites, tag, and — where `.oss.json` says so — the GitHub Release, notes and all. |
| `/oss:doctor` | Config, dependencies, clone, worktree root, state file, which watch channel and radar board this repo resolves to, and whether the merge call can skip supertool's publish-confirm gate. Also reports which copy of this plugin answered the invocation (compared by content and by declared schema version, not by manifest version alone), where a defect in this plugin itself would get filed, whether `./supertool` points at this plugin's own checkout, and three lines about the machine itself — interpreter architecture, CPU topology, worker sizing. Exits 0 always; see `commands/doctor.md` for what each line means. |

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

**The supported floor is Python 3.9**, declared in `pyproject.toml` as
`[project] requires-python = ">=3.9"` and nowhere else. CI runs the suite on ubuntu, macOS and
Windows across Python 3.9-3.12; that is what the code is *demonstrated* on, which is a different
question from what it *supports*, and reading the two as one is what #410 filed. The floor is wider
than the code needs — nothing tracked here uses a syntax or standard-library feature above 3.7 — and
it is set at 3.9 because 3.9 is the oldest version anything here has ever been run on.

The badge above, the matrix, the `Python X.Y compatible` line eight modules under `scripts/` carry,
and the oldest explicit `python3.N` in `scripts/doctor.sh`'s interpreter walk are all *derived* from
that key. None of them can read a manifest at parse time, so `tests/test_python_floor_410.py` is what
makes them agree. A green macOS run is not evidence on its own.

A separate ubuntu leg runs `bash -n` and `shellcheck -S warning` over every tracked shell source.
Which files those are is derived rather than listed — `python3 scripts/shell_sources.py` prints the
list, selecting by extension or by shebang so an extensionless script is covered by the commit that
adds it. It exits non-zero when it matches nothing, so an empty selection fails the leg instead of
linting no files and passing. A tracked file that is in the index and not on disk — what an
uncommitted delete looks like, and what the changelog fold leaves behind until the release commit —
is named on stderr and does not fail the leg; only a file that is there and will not read does.

That leg installs nothing. `shellcheck` ships in the `ubuntu-latest` runner image, and fetching it
anyway put a package-mirror round trip inside the job's `timeout-minutes`, which is what took the leg
— and with it every pull request — down for a day (#303). If the binary is ever missing the step says
so and exits `4`, rather than collecting one `command not found` per file into the same status a real
finding uses.

`python3 scripts/transcript_refusals.py` counts refused tool calls across this machine's own agent
transcripts, by refusal class, by model and by the batching lever #313 measured. Its own third state
is the point: a directory with no transcripts must not read like one full of transcripts that
refused nothing. The script's own docstring carries the full field list.

`python3 scripts/review_return.py -` classifies what a review spawn actually handed back, in six
states from `states-findings` to `could-not-classify` -- built for `referred-not-stated`, a message
that gestures at findings without stating them, which two rounds of brief language (#275, #296,
#392) failed to prevent. `agents/developer.md` is where it is actually driven from; the script's own
docstring has the full mechanism, including why input is framed rather than read raw (#404).

## License

Community License — see [LICENSE](LICENSE). Source-available, not open source: no commercial
redistribution, no competing use.

Built by Digital Process Tools in Toulouse, France.
