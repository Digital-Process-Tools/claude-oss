---
title: "A jit rule a session has already consumed is silent for every agent that session spawns"
description: "The hooks run for a spawned agent's tool calls, but the shown set is keyed on the hook payload's session_id, which a subagent shares with its parent -- so a remind-mode rule the parent or an earlier spawn already saw never reaches a later lane."
keywords: subagent, sub-agent, spawned agent, developer lane, sub-manager, jit rule, hook injection
---

**Measured 2026-09-03, two spawns (`Explore`, `general-purpose`), same command each.**

| where the call ran | `supertool 'read:trap.d/905.jit-probe-payload-form.md'` |
| --- | --- |
| the parent session, first time | `trap-fragments.md` injected |
| either spawn, after that | `(none) [shown:2]` in `hooks.log`; the spawn saw no hook text at all |

- **The hooks do run for a spawn.** `.claude/jit-context/.discovery/logs/hooks.log` carries a
  `pre-path` and a `pre-tool (Bash)` line at the spawn's timestamp. Read the log before
  concluding a rule never fires in a subagent.
- **Dedup is per `session_id`, and a spawn carries its parent's.** `jit_session_key` in the
  plugin's `common.sh` reads it off the hook payload; the marker files live under
  `.claude/jit-context/.discovery/state/`. One shown set for the session and every agent in it.
- **Consequence for the loop:** scheduler, sub-manager and every developer lane are one session.
  A rule the sub-manager's own board read tripped, or the first lane tripped, reaches no later
  lane. `agents/*.md` prose is the only instruction a lane is guaranteed to hold; a trap moved
  out of a brief into a jit rule reaches a lane only if nothing earlier in the session touched
  the same match.
- **To probe:** batch a known-good control (a rule already seen to fire this session) and read
  `hooks.log` for `(none) [shown:N]` -- that string means suppressed, not unmatched.
