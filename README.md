# claude-oss

> Run an open-source repo as its maintainer. Triage the tracker, delegate the work, review hard, merge on green.

![Version](https://img.shields.io/badge/version-0.1.0-orange)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![OS](https://img.shields.io/badge/os-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/license-Community-green)

---

## The problem

A maintainer loop written as prose gets copied between repos, and the copies drift. Fixing a triage
rule means editing it in three places and remembering the third. Repos that never got the copy run
no loop at all.

This packages the loop once: one skill, two agents, a handful of commands. Everything that differs
between repos — default branch, label spellings, version sites, test command — lives in a config
file the plugin writes by probing the repo, not in the prose.

## Install

```
/plugin marketplace add Digital-Process-Tools/claude-marketplace
/plugin install oss@dpt-plugins
```

**Restart Claude Code afterwards.** Plugin registrations are read once at session start.

Installing pulls in `supertool`, `remember` and `claude-jit-context` automatically — they are
declared dependencies and resolve from the same marketplace.

## Status

v0.1.0 is a scaffold. The maintainer loop is being extracted; nothing here manages a repo yet.

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
