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
- **Dedup used to be per `session_id` for every dimension, and a spawn carries its parent's --
  #1584 changed this for `tools` only.** `claude-jit-context` 0.10.0 added `jit_agent_key()`
  (keyed on the hook payload's own `transcript_path`, which a spawn does NOT share with its
  parent), and `pre-tool-hook.sh` uses it for `mode: once` dedup on the `tools` dimension since
  commit `09155e9a`. **`paths` and `vocabulary` -- this rule's own dimension -- were not
  touched and could not be:** neither carries a `mode` column at all (confirmed against
  `doctor.py`'s documented index arities and `common.sh` itself, which uses `jit_agent_key()`
  "ONLY by pre-tool-hook.sh"), so a `paths` or `vocabulary` rule still dedups on plain
  `session_id` regardless of anything written in its frontmatter, on every `claude-jit-context`
  version including the one running right now.
- **Consequence for the loop, split by dimension:** a `tools` rule in `mode: once` now reaches
  one lane per invocation, on `claude-jit-context` >= 0.10.0 -- an install below that floor (no
  version is pinned in `plugin.json`, itself a separate gap) silently falls back to the old
  per-session behaviour with no signal that it has. A `paths` or `vocabulary` rule -- this file
  included -- still reaches only the first agent in the whole session to trip it: scheduler,
  sub-manager and every developer lane remain one session for those two dimensions. `agents/*.md`
  prose is the only instruction a lane is guaranteed to hold; a trap moved out of a brief into a
  `paths`/`vocabulary` jit rule reaches a lane only if nothing earlier in the session touched the
  same match.
- **To probe:** batch a known-good control (a rule already seen to fire this session) and read
  `hooks.log` for `(none) [shown:N]` -- that string means suppressed, not unmatched.

**And the probe itself has to be a form the hook understands.** Driving `pre-path-hook.sh` with
`{"tool_name":"Bash","tool_input":{"command":"supertool 'paste:trap.d/904.x.md'"}}` reported
`(silent)` for a rule whose `match:` was correct — and for a known-good rule that had already fired
several times in the same session. The real write op is `paste:::PATH:::CONTENT`, so `paste:PATH` is
not a form any path can be extracted from; the same three paths with `read:<path>` fired correctly.
First reading was *my new rule does not fire*; the honest one was *my probe does not probe*.
**Always put a rule you have already seen fire in the same probe batch.** A probe that produces no
output and a probe that was never understood by the thing it is probing look identical, and telling
those two apart is the first thing this repository says about itself. That control was in the batch
by luck, not design, and it is the only reason the false reading cost two minutes instead of an
afternoon spent editing a correct rule until it "worked".

**And a `mode: remind` (or, since #1584, `mode: once`) `tools` rule fires once per lane, so it is a
greeting rather than a guard against a habit within one lane's own turns (#1146).** Measured in a
five-hour session: `md-is-a-manual-not-a-rationale.md` was written at ~10:50 and fired at ~11:00,
the 15th and last entry in that session's shown set. At 12:34 the same session rewrote two phase
files and put rationale straight back in -- five clauses of it -- with no reminder, because the
rule had been shown ninety minutes earlier. The maintainer caught it by eye; the hook did not. That
measurement predates #1584 and is unaffected by it: a `tools` rule now dedups per *reader*
(transcript_path) rather than per session, which stops a **later spawn** from missing what an
**earlier** one already saw, but a single reader still sees its own `once`/`remind` row exactly
once for the rest of its own life -- the "greeting, not a guard against a habit" problem is about
repetition *within* one reader's turns, which #1584 does not touch. A `paths` or `vocabulary` rule
(this file's own dimension) still dedups per session exactly as measured above, #1584 or not.

Every hook line in between reads `(none) [shown:4]`. **That string means suppressed, not
unmatched** -- the rule matched every one of those edits and was withheld each time.

This bites hardest here specifically: the rules most worth firing in this repository are the ones
about a **habit** -- how to write prose, how to shape a payload, what a third state is for -- and a
habit is exactly what a single reminder does not fix. The rules that survive one showing are the
ones about a fact you either know or do not.

**A dispatched `oss:developer` lane reporting "I have no `SendMessage` tool" is not a failure of
the resume, and should not be misread as `agent-unreachable` (#1436).** `agents/developer.md`'s
own frontmatter grants Bash, TodoWrite, Skill and Agent -- deliberately no `SendMessage`, since a
developer lane reports back through its own completion rather than messaging anyone. Sending
`SendMessage` to that lane from the sub-manager side still resumed it successfully (the same
task-id/agentId round trip a sub-manager already reads for the first completion), and the lane
picked up the new instruction and acted on it even though it had no way to reply the same way --
it used its own ordinary finish-and-report path instead.
