# claude-oss

> Run an open-source repo as its maintainer. Triage the tracker, delegate the work, review hard, merge on green.

![Version](https://img.shields.io/badge/version-0.4.0-orange)
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

Then, in any repo you maintain:

```
cd the-repo
oss-workspace
```

Without that symlink the launcher is only on the path it ships at, so run it as
`bin/oss-workspace` from this checkout.

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

Install the launcher once:

```
ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace
```

The working directory is the selection: it opens *that* repo, never this plugin's checkout.

## Commands

| Command | What it does |
| --- | --- |
| `/oss:tick` | One pass of the maintainer loop: board, decide, delegate, review, merge on green. |
| `/oss:setup` | Probes the repo and writes `.oss.json`. Measures; never assumes — a version site is a file read and found to carry a version, and every label that matched no pattern is named. |
| `/oss:scaffold` | Adds the missing repo furniture. Never overwrites; shows before it writes. Reports what it will not do: create a label, guess a required-check count, or generate a test workflow. |
| `/oss:triage` | One triage sweep — priority, lane, milestone, the clusters one change would fix, the cohort burn-down with the limit it was counted under, and what the board is lying about. |
| `/oss:changelog` | Checks changelog fragments, or folds them for a release. |
| `/oss:release` | Gates, version sites, tag, and — where `.oss.json` says so — the GitHub Release, notes and all. |
| `/oss:doctor` | Config, dependencies, clone, worktree root, state file — including whether `/oss:tick` can actually read it, which is not the same question as whether it is there — which watch channel this repo resolves to, which decides whether its board is its own fleet or somebody else's, and whether anything publishes to that board at all: a registered radar tier is one half, a route to the op that reads it is the other, and a channel with neither renders exactly like a healthy one. Which *process* holds the socket is not established, and the output says so. Exits 0 always. |

## Status

**Tested, not proven.** The claim this section used to make — that no real issue had gone from
triage through to a merge — stopped being true some time before anyone edited it: the loop now
maintains this repository, and the triage-to-merge round trip has run many times over, including
the releases cut with `/oss:release`.

What that does *not* establish is the part most users care about. Almost everything this plugin
claims about a repository it has **scaffolded** still rests on tests and scratch runs rather than on
a repo somebody maintains through it, and two owned files are known to have gone stale in the field
with no observed repair.

The measured version of that, with each claim graded observed or reasoned and dated to the commit
it was taken at, is **[What is not proven yet](CLAUDE.md)** — re-derived at each release rather than
edited. It is deliberately not restated here: a second copy is the one that drifts, and this
section is the proof of it.

## Development

```
python3 -m pytest tests/ -q
```

CI runs the suite on ubuntu, macOS and Windows across Python 3.9-3.12. A green macOS run is not
evidence on its own.

## License

Community License — see [LICENSE](LICENSE). Source-available, not open source: no commercial
redistribution, no competing use.

Built by Digital Process Tools in Toulouse, France.
