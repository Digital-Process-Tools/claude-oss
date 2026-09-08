---
title: "A background watcher meets no guard, and every checker rule applies to it"
description: "raw_command_guard hooks Bash only, so a call handed to Monitor runs unchallenged. Four defects in one four-minute watcher; the three quiet ones each produced a confident wrong answer."
tool: Monitor
match: ~.*
mode: remind
---

**A watcher is a checker. It just does not look like one -- it looks
like plumbing.** Every rule this repository has about checkers applies:
three states, a positive control, no swallowed errno.

Measured (#1180), four defects in about four minutes, in one watcher:

- **The Bash guard does not reach here.** `raw_command_guard` hooks Bash
  only. The identical `gh` call refused ninety minutes earlier in the
  same session ran unchallenged when handed to Monitor. You are never
  told; you simply never meet the guard. Read through
  `./supertool 'gh-run:N'`, not raw `gh`.
- **`2>/dev/null || true` turned a failed read into "not yet".** An
  expired token or a wrong run id would poll silently for twenty minutes
  and then assert something about the run that was never measured.
- **A free-text match reported `in progress` as terminal.** See
  `waiting-on-a-status-line.md`; anchor on `^Status:`.
- **`status` is read-only in zsh.** `status=$(...)` dies with
  `read-only variable: status`. Use another name.

The ranking is the point: the three quiet defects each produced a
confident, wrong, plausible answer; the one that crashed cost nothing.

**What a correct watcher distinguishes**: CONCLUDED / READ FAILED /
UNMEASURED after N consecutive failures / PARSE FAILED (no state line --
the read worked, the parse did not) / NOT CONCLUDED after N successful
reads. Emit a heartbeat every Nth poll, so silence cannot pass for a
quiet run.
