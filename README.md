# claude-oss

Runs an open-source repo as its maintainer: triage the tracker, delegate the work, review hard,
merge on green.

![claude-oss — triage, build, review, merge, ship](docs/oss.png)

[![Tests](https://github.com/Digital-Process-Tools/claude-oss/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Digital-Process-Tools/claude-oss/actions/workflows/tests.yml)
![Version](https://img.shields.io/badge/version-0.20.0-orange)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![OS](https://img.shields.io/badge/os-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/license-Community-green)

## Install

```
/plugin marketplace add Digital-Process-Tools/claude-marketplace
/plugin install oss@dpt-plugins
```

**Then run `/reload-plugins`, or restart Claude Code.** Plugin registrations are read once at
session start, so a mid-session install leaves the agent registry unresolved until you do.

See [docs/install.md](docs/install.md) for developing this plugin's own source, and for setting
up `oss-workspace` in a repo you maintain.

## One tick

`/oss:tick` reads the board, decides what is worth building, delegates it, reviews the result, and
merges on green. Everything repo-specific — default branch, labels, test command, version sites —
lives in `.oss.json`, written once by `/oss:setup`.

## The launcher

Once installed and set up in a repo you maintain, `/oss:doctor` prints the exact, paste-ready
command to wire up `oss-workspace` for the version you have installed. Run it from that repo, and
`oss-workspace` opens a session there with the maintainer loop already running.

## More

- [docs/overview.md](docs/overview.md) — what each piece is, what a tick does, what the loop
  refuses to do, and where the project stands.
- [docs/install.md](docs/install.md) — installing, developing this plugin, the launcher and its
  symlink.
- [docs/commands.md](docs/commands.md) — every slash command.
- [docs/status-line.md](docs/status-line.md) — every status-line field.
- [docs/development.md](docs/development.md) — running the test suite, and the scripts and hooks
  that check this repo's own conventions.
- [docs/status.md](docs/status.md) — what installing this plugin does and does not put in motion.
- [docs/autonomy.md](docs/autonomy.md) — what "autonomous in somebody else's repo" would take, and
  does not.
- [CLAUDE.md](CLAUDE.md) — what is not proven yet, measured and dated at each release.

## License

Community License — see [LICENSE](LICENSE). Source-available, not open source: no commercial
redistribution, no competing use.

Built by Digital Process Tools in Toulouse, France.
