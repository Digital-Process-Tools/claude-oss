# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `skills/oss-manager/SKILL.md` — the maintainer loop, carrying process only. Every repo-shaped fact
  reads from `.oss.json` instead of being asserted in prose.
- `agents/oss-developer.md` and `agents/oss-triager.md`. Neither is granted `Read`/`Grep`/`Glob`:
  reads go through supertool via `Bash`, which makes the batching instruction binding rather than
  advisory. The triager is additionally denied `Edit`/`Write`.
- Content guards asserting no repo slug, clone path, worktree root or maintainer handle appears in
  any skill or agent, and that every document reading a public tracker keeps its untrusted-input
  clause.

## [0.1.0] - Scaffold

### Added

- Plugin manifest, Community License, cross-platform CI matrix (3 OS x Python 3.9-3.12).
- Version guard tying `.claude-plugin/plugin.json` to the newest CHANGELOG release and the README badge.
