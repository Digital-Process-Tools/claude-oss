# Install, and developing this plugin

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

## Developing this plugin itself

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

Before the doctor diagnostic and before the session opens, the launcher also checks whether the
`oss` plugin itself is current -- synchronously, the same trade the diagnostic already makes,
because an update that lands mid-session was invisible until somebody happened to run
`/oss:doctor` by hand (#753). A genuine update selects `/oss:doctor` as the opening prompt instead
of the ordinary `/oss:tick`/`/oss:setup` choice, so the new copy diagnoses the tree it just moved
to; nothing else changes the opening prompt. The `OSS_NO_AUTO_UPDATE` / `auto_update: false`
opt-out already covers this exactly as it covers the SessionStart hook below. A `claude` started
by hand never reaches the launcher at all, so `hooks/session-start-update.sh` still runs the same
check in the background on every `SessionStart` -- `scripts/plugin_update.py` debounces the two
against each other, so the hook firing seconds after the launcher already checked does no
redundant network work.

The launcher also repoints `~/.local/bin/oss-workspace` itself when it is pinned at a superseded
install (#753/#289) -- read from `installed_plugins.json`'s own record for this project, never
from the symlink's current target, because a stale link is exactly the case where the *old*
launcher would otherwise keep re-pointing itself at its own stale target forever. It repoints
silently on success and says so on stderr; if it cannot tell or cannot write, it says that and
leaves the link untouched rather than guessing.

Before the session starts working, the launcher runs `/oss:doctor`'s diagnostic over the repo it
just resolved and relays anything short of a clean pass -- see `docs/commands.md`'s `/oss:doctor`
row for what it covers. It never refuses to open a session over a broken repo; a maintainer whose
config is broken is exactly the person who needs a session in which to fix it. Set
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

## From the same workshop

Four plugins, one team, each does one thing. This one and three siblings:

- [claude-remember](https://github.com/Digital-Process-Tools/claude-remember): memory across sessions. Saves, compresses through Haiku, reloads at the next start.
- [claude-jit-context](https://github.com/Digital-Process-Tools/claude-jit-context): project knowledge that loads only when the prompt, the file or the tool matches it.
- [claude-supertool](https://github.com/Digital-Process-Tools/claude-supertool): batched file and tracker ops. One call instead of seven, and a refusal instead of a wrong answer.

All four install from one marketplace: `/plugin marketplace add Digital-Process-Tools/claude-marketplace`.
