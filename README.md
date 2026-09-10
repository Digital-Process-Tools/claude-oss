# claude-oss

Runs an open-source repo as its maintainer: triage the tracker, delegate the work, review hard,
merge on green.

![claude-oss — triage, build, review, merge, ship](docs/oss.png)

[![Tests](https://github.com/Digital-Process-Tools/claude-oss/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Digital-Process-Tools/claude-oss/actions/workflows/tests.yml)
![Version](https://img.shields.io/badge/version-0.31.0-orange)
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

## Type it once

`/oss:run` is what a session opens on, and the only thing a person types. It asks one
question — what does this repo need now — and answers it from state and config, never
from an argument. Everything repo-specific lives in `.oss.json`: a cadence step written
only in prose is one somebody has to remember, which is why they are thresholds instead.

```mermaid
flowchart TD
    YOU([you, once]) --> W["oss-workspace<br/>update plugin · wire channel · open session"]
    W -->|injects| RUN["/oss:run"]
    RUN --> Q{"what does this<br/>repo need now?"}
    Q -->|no config yet| CFG["probe the repo, write .oss.json"]
    Q -->|someone wrote to us| IN["inbound: issue · PR · comment"]
    Q -->|its trigger fired| REL["release: gates · audit · tag · publish"]
    Q -->|a backlog crossed its threshold| CUR["curate trap.d"]
    Q -->|a release just landed| TRI["triage the board"]
    Q -->|otherwise| BOARD["read the board,<br/>decide what is worth building"]
    BOARD --> LANE["developer lane<br/>worktree · test first · stops at a commit"]
    LANE --> PR["pull request"] --> AUD["audit the diff for<br/>what CI cannot fail on"]
    AUD --> GREEN{"green?"}
    GREEN -->|no| LANE
    GREEN -->|yes| MERGE["merge"]
    CFG & IN & CUR & TRI & REL & MERGE --> RUN
```

The loop arms its own next turn and stops only on a direct instruction to stop.

## The launcher

Once installed and set up in a repo you maintain, `/oss:doctor` prints the exact, paste-ready
command to wire up `oss-workspace` for the version you have installed. Run it from that repo, and
`oss-workspace` opens a session there with the maintainer loop already running.

## More

- [docs/overview.md](docs/overview.md) — what it is for, and how to tell if work is inside that.
- [docs/install.md](docs/install.md) — installing, developing it, the launcher and its symlink.
- [docs/commands.md](docs/commands.md) — every slash command.
- [docs/status-line.md](docs/status-line.md) — every status-line field.
- [docs/development.md](docs/development.md) — the test suite and this repo's own guards.
- [docs/status.md](docs/status.md) — what installing this does and does not put in motion.
- [docs/pick-the-work.md](docs/pick-the-work.md) — how the loop decides what to build next.
- [docs/open-the-workspace.md](docs/open-the-workspace.md) — what the launcher sets up.
- [docs/autonomy.md](docs/autonomy.md) — what "autonomous in someone else's repo" would take.
- [CLAUDE.md](CLAUDE.md) — what is not proven yet, measured and dated at each release.

## License

Community License — see [LICENSE](LICENSE). Source-available, not open source: no commercial
redistribution, no competing use.

Built by Digital Process Tools in Toulouse, France.
