---
title: "sub_manager_spawn_guard.py: two known gaps in its own fail-open promise"
description: "The module docstring promises every error resolves to allow, but the import that would need to fail sits outside the try, and the role check reads a repo-global marker rather than the caller's own identity."
match: (^|/)scripts/(sub_manager_spawn_guard|agent_role)\.py$
---

The module's own docstring promises "a crash reading the role, an
unreadable payload, an unexpected shape, all resolve to allow." Two
gaps found in the same audit round, both non-blocking today because
nothing has hit either in practice yet:

- **`import agent_role` sits at module scope, outside `decide()`'s own
  try/except.** With `agent_role` missing, the process exits 1 with an
  empty stdout and a bare `ModuleNotFoundError` traceback on stderr --
  not the "allow, could-not-tell" note the docstring's contract
  implies. A fail-open guarantee has to guard its own imports, not
  just its body.
- **The role check reads `agent_role.current_role`, a repo-global
  marker file with a 4-hour TTL**, not the calling agent's own
  identity. It cannot distinguish "a sub-manager is asking" from "a
  sub-manager wrote a marker in this repo within the last four hours"
  -- and the marker clears only on the clean exit path, so a crash,
  kill or context death leaves it live. Exercised: with a stale live
  marker, a *scheduler* (not a sub-manager) spawning a nested
  `oss:sub-manager` was refused with a remedy ("spawn
  `oss:tick-dispatch` or a developer lane instead") that is wrong for
  a scheduler, which legitimately must spawn one.

- **The role marker is not cleared on a sub-manager's own clean exit, only read as a 4-hour TTL.**
  Observed live, not reasoned: immediately after a tick handed back `TICK: completed` (confirmed by
  `tick_handback.py`'s own classification and a `SendMessage` status check that got "my tick is
  finished... no further work is in progress"), `agent_role.py` still read `sub-manager, marker
  state: live`, and the scheduler's next spawn attempt was refused on "a running sub-manager may not
  spawn a nested oss:sub-manager" -- a caller (the scheduler) that is not a sub-manager at all,
  refused as if it were the thing the guard exists to stop. This compounds the marker-scope gap
  above rather than being a separate mechanism: a stale marker from a crash and a stale marker from
  an ordinary completed tick render identically, and both currently require a manual
  `agent_role.py --clear` that nothing prompts. The guard fails *closed*, which is the safer
  direction, but the refusal message names the wrong caller ("a nested spawn" when none happened),
  sending whoever debugs it looking in the wrong place. Clearing the marker as part of the
  sub-manager's own completion path, and having the refusal distinguish "the marker says a
  sub-manager is live" from "you are that sub-manager," would close this without touching the TTL
  design above.

Both original gaps are `misreports`/`misdirects`, not merge-blocking. Read the
current docstring's promise before changing either the import shape or
the role check here -- it is the contract this file is supposed to
keep and currently does not, in either of the original two ways, or in the
completion-path gap just above.

- **`--clear-marker-root` resolves the marker path via `git rev-parse --git-dir`, not
  `--git-common-dir`.** In a linked worktree the two diverge: `.git/oss-agent-role` at the main
  clone versus `.git/worktrees/<name>/oss-agent-role` from inside the worktree. Measured: with a
  live `sub-manager` marker at the main clone, invoking `--clear-marker-root <worktree>` prints
  `marker: nothing to clear`, exits 0, and leaves the marker live -- "no marker was ever written" and
  "the marker is live at a git dir this call did not resolve" render identically. Does not fire on
  the ordinary path (this harness resets cwd between calls, and a sub-manager's handback runs from
  the main clone), but a cwd at handback time that is ever a linked worktree can leave a marker that
  outlives a clean tick and blocks the scheduler's next legitimate spawn -- the exact symptom this
  mechanism exists to fix (#1585). Use `--git-common-dir` when resolving this marker's path, or add
  a fourth `marker:` state naming the git dir actually resolved.
- **A fail-open premise inferred from one field's shape is not the same as having watched that field
  live.** `_is_subagent_transcript()` short-circuits to `DECISION_ALLOW` whenever
  `payload["transcript_path"]` does not look like `.../subagents/agent-<id>.jsonl`, on the premise
  that a main-session caller never carries that segment. The fallback shape is sound -- an absent,
  non-string, or already-matching path still falls through to the existing marker-based decision
  unchanged, so this only ever widens what is allowed, never what is denied -- but the premise itself
  was the issue's own investigation, not confirmed against a live harness-captured payload the way
  `tool_input.subagent_type` was checked against published SDK docs before #1520 built on it (this
  same module already got a harness-payload-shape fact wrong once, per the `1520`/`1571` entries in
  this layer's `00-README.md`). If a nested spawn's real `transcript_path` ever diverges from this
  shape, the guard fails open for exactly the case #1520 exists to deny. Settle it with a real nested
  spawn's actual `transcript_path`, read back and compared against `_SUBAGENT_TRANSCRIPT_RE`, before
  trusting the premise further (#1585).

Routed via /oss:curate from
`trap.d/1571.role-marker-is-not-cleared-when-a-sub-manager-finishes.md`,
`trap.d/1585.clear-marker-root-uses-git-dir-not-common-dir.md` and
`trap.d/1585.spawn-guard-transcript-path-assumption-not-live-fire-verified.md`.
