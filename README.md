# claude-oss

**OSS is open-source software.** This is the maintainer loop for a public repo.

![claude-oss — triage, build, review, merge, ship](docs/oss.png)

> Run an open-source repo as its maintainer. Triage the tracker, delegate the work, review hard, merge on green.

[![Tests](https://github.com/Digital-Process-Tools/claude-oss/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Digital-Process-Tools/claude-oss/actions/workflows/tests.yml)
![Version](https://img.shields.io/badge/version-0.16.0-orange)
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

### Developing this plugin itself

The marketplace install above unpacks a second tree under
`~/.claude/plugins/cache/dpt-plugins/oss/<version>/`. Commands, skills and agents resolve
from that cache copy, not from your clone — so an edit to `agents/developer.md` or
`skills/manager/phases/dispatch.md` changes nothing about the session that runs it until a
release is cut and the cache refreshes (#607). That is the right route for running this
loop against a repository you maintain; it is the wrong one for working on this repo's own
source.

This repository ships `.claude-plugin/marketplace.json` with a `directory`-source entry
that points at itself, so a local marketplace add resolves plugin content **in place** —
Claude Code reads commands, skills and agents straight from the path you give it, with no
copy into the plugin cache (confirmed by reading the installed CLI's own marketplace-source
handling, version 2.1.219 — a `directory` source's `installLocation` is set to the given
path directly, never cloned or copied elsewhere). From a clone of this repository:

```
/plugin marketplace add /path/to/your/claude-oss
/plugin install oss@claude-oss-dev
```

Reload the same way any install needs it -- restart Claude Code, or run the reload
command from the Install section above. An edit to `agents/`, `skills/` or `commands/` in
your clone is live the next session — no release needed. This is a
**contributor path alongside** the marketplace install above, not a replacement for it:
a maintainer running the loop against a different repository should still use
`dpt-plugins`, because that is the tagged, released copy the loop's own currency and
release tooling (`/oss:doctor`'s `SKEW` line, `plugin_update.py`) assume the installed
copy to be. Running both marketplaces registered at once is fine; just install `oss` from
whichever one matches what you are doing in this session.

## After cloning a repo you maintain

Install the launcher once. **On a marketplace install** -- `/plugin install oss@dpt-plugins`,
the route above, and the one almost everyone reading this took -- there is no checkout and no
fixed path to write here: the plugin's own `bin/oss-workspace` lives under a version-scoped
cache directory (`.../dpt-plugins/oss/<version>/bin/`) that moves on every release, so a literal
command in this file would be correct until the next release and silently wrong after it (#617).
Run `/oss:doctor` instead -- its `oss-workspace launcher` line prints the exact, paste-ready
command for the version you actually have installed, platform-appropriate on POSIX and on
Windows, computed from `PLUGIN_ROOT` rather than typed here.

**If you have cloned this plugin's own repository** -- for development, or because you are
contributing to it -- the equivalent line, run from that checkout, is:

```
ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace
```

POSIX only, and there is no Windows equivalent to substitute for it (#330): `bin/oss-workspace`
is a `/bin/sh` script that runs under Git Bash rather than cmd or PowerShell, and `~/.local/bin`
is on no Windows `PATH`. Run `sh bin/oss-workspace` from the checkout instead.

Either way, the symlink is resolved once, at install time, and does not follow a later plugin
update or a later commit in your checkout -- `/oss:doctor` reports that under `oss-workspace
launcher` (#289/#333/#519), from PATH entries your own shell actually carries: the plugin's own
`bin/` directory is excluded from that check, because a running session always has it on PATH and
finding the launcher only there says nothing about whether the command above ever worked (#617).

That symlink step is not a stopgap waiting on the plugin's own installed directory reaching `PATH`
some other way: measured on a clean login shell, the marketplace cache
(`.../dpt-plugins/oss/<version>/bin`) is not on `PATH` at all outside a running session (#526), so
the step above is the answer rather than a placeholder for one -- CLAUDE.md's "Traps" section
carries the measurement.

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
repo then reported as unknown rather than fine.

Measured 2026-08-29 on macOS 15.3.2 (arm64), with `supertool` 0.52.0, `gh` 2.98.0, node v22.22.1 and
`claude` 2.1.219 on PATH: eight runs of the real launcher per arm, wall-clock mean, with the final
`exec claude` replaced by a no-op so no interactive session is opened but every `claude mcp ...`
subcommand still reaches the real binary -- opening costs **~1.3 s** without the diagnostic and
**~3.2 s** with it. Both figures now include a `claude mcp get` call the launcher itself makes at
every open (#621), which this receipt did not carry when it was first written; of the diagnostic's
own added ~1.9 s, roughly half is its own `claude mcp get` call (`claude` itself takes about a second
to start, independent of the network) and roughly half the pre-existing per-dependency network check
bounded at 25 s per dependency -- not "most of it", the way this sentence used to read. One machine,
one run of measurements; re-measure rather than trust this past its own date.

## Commands

| Command | What it does |
| --- | --- |
| `/oss:tick` | One pass of the maintainer loop: board, decide, delegate, review, merge on green. |
| `/oss:setup` | Probes the repo and writes `.oss.json`. Measures; never assumes — a version site is a file read and found to carry a version, and every label that matched no pattern is named. |
| `/oss:scaffold` | Adds the missing repo furniture. Never overwrites; shows before it writes. Reports what it will not do: create a label, guess a required-check count, or generate a test workflow. Its receipt reads both halves of the board question, so a repo it scaffolded before the preset was added — tiers registered, no route to the op that reads them, and unreachable by a template fix because `.supertool.json` is never replaced — is reported rather than called clean. |
| `/oss:triage` | One triage sweep — priority, lane, milestone, the clusters one change would fix, the cohort burn-down with the limit it was counted under, and what the board is lying about. |
| `/oss:changelog` | Checks changelog fragments, or folds them for a release. |
| `/oss:release` | Gates, version sites, tag, and — where `.oss.json` says so — the GitHub Release, notes and all. |
| `/oss:doctor` | Config, dependencies, clone, worktree root, state file, which watch channel and radar board this repo resolves to, whether a `pre-push` hook's push budget was ever raised above supertool's 300s default, and whether the merge call can skip supertool's publish-confirm gate. Also reports which copy of this plugin answered the invocation (compared by content and by declared schema version, not by manifest version alone), where a defect in this plugin itself would get filed, whether `./supertool` points at this plugin's own checkout, and three lines about the machine itself — interpreter architecture, CPU topology, worker sizing. Exits 0 always; see `commands/doctor.md` for what each line means. |
| `/oss:install-audit` | Is this install complete — the plugin, its declared dependencies, and what the human still has to do, answerable with no `.oss.json` in hand: is it present, valid, *and committed*; do declared dependencies resolve at a version this plugin's scripts can read; does the label vocabulary the triager needs exist; would re-scaffolding change the owned files. Exits 0 always; see `commands/install-audit.md`. |

## Status line

`/oss:scaffold` writes `.oss/statusline.py` as an owned file, and Claude Code renders its output
in the corner of the terminal. Every field is separated by ` | `; a field this repository could not
measure renders `?` rather than a guess, per this repository's own rule that a check which did not
run must never look like one that ran clean.

Left to right:

| field | example | means |
| --- | --- | --- |
| model · context | `Opus · 42%` | Claude Code's own session facts, passed straight through. |
| repo | `claude-oss main v0.15.0` | repo name, then branch (only when it is not the declared default) and the tracked version. |
| board | `4pr 2ok 1x 1... 0? · 23is / 2eis` | open pull requests, then a CI breakdown (green/red/running/unknown, every group shown even at zero), then open issues and how many of those arrived from outside repository membership. |
| release | `rel 4/17` | commits banked since the last release, over what a release here usually costs. Either half is `?` on its own when only one could be measured. |
| tick | `tick 4m` / `tick due` / `tick off` / `tick -` / `tick ?` | when the next maintainer tick fires, if one is armed at all. |
| last | `last 12:34` | a wall-clock stamp of when this line was last rendered — frozen like the rest of the line between renders, but a frozen clock time stays readable against your own watch. |
| plugins | `plug 3✓ oss↥0.15.0 1?` | how many of this repo's declared plugin dependencies are current, then each one that is not, named. `↥`/`>` shows the **latest published** version behind a plugin marked `behind`; `↑`/`+` shows the version **installed** for one marked `ahead` — two markers that print two different fields, not two colours of the same one (#549/#550). `?` counts a plugin whose version could not be compared at all. |
| ch | `ch✓` / `ch✗` / `ch◐` / `ch!` / `ch?` | whether supertool's watch channel is delivering — green when the consumer's counters are moving, red when nothing is listening, yellow (`◐`) when the consumer is bound but nobody is subscribed, `ch!` on a contradiction, `ch?` when nothing could be established. Set `"watch_channel": false` in `.oss.json` to turn it off — the field then disappears entirely rather than showing `ch?`, because an operator's deliberate off switch is not the same absence as a question this line asked and could not answer. |

Colour, where the terminal supports it, adds a second signal on top of the marker shape rather
than replacing it — every state above is told apart by its glyph alone, in monochrome.

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

Install the test dependencies once (`pytest-cov` is required by `pyproject.toml`'s `addopts`;
the plain `pytest` command below fails before a test runs without it):

```
pip install -r requirements-dev.txt
```

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

`scripts/batch_hint.py` is a `PostToolUse` hook (`hooks/hooks.json`) that flags a run of 3 or more
consecutive single-op read-only supertool calls with one line naming the collapsed form, and only
that -- it never blocks. It exists because the equivalent instruction in prose, in `agents/
developer.md`, measured at zero effect across 612 transcripts and a controlled A/B (#490): a hook
costs nothing on a clean run, where prose is charged on every turn whether or not it ever applies.

`scripts/agent_budgets.py` records a size budget for each `agents/*.md` definition -- every byte
there is re-read on every turn of every lane that runs it -- and `tests/test_agent_definition_
budget_491.py` fails when one crosses it. `CLAUDE.md` carries the current sizes and the
replace-don't-append rule that goes with them (#491).

`python3 scripts/preflight_check.py --pattern PATTERN --path FILE_OR_DIR` searches the tree for a
pattern the issue names, in three states -- `matched`, `not-matched`, `could-not-search`, the last
of which must never render as the second -- so a dispatch decision can tell an issue whose fix
already shipped from one still genuinely open before an agent is briefed for it (#457).

`python3 scripts/transcript_refusals.py` also now reports `turns_over_threshold_count`/`_share`
against a measured 140-turn threshold and `decile_bytes`/`first_fifth_byte_share`, the two lane-cost
findings #498 measured across 612 transcripts -- read after a lane completes, never surfaced to the
one running.

## License

Community License — see [LICENSE](LICENSE). Source-available, not open source: no commercial
redistribution, no competing use.

Built by Digital Process Tools in Toulouse, France.
