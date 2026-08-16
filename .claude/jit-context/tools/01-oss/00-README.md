---
title: "There is deliberately no rule keyed on the Agent tool"
description: "A tools rule on Agent cannot fire -- the PreToolUse hook builds its match subject from four keys and an Agent payload carries none of them."
---

**Nothing in this layer is keyed on `Agent`, and that is a decision rather than an oversight.**

A rule that fired on agent dispatch would be worth having: it would put the standing clauses
of a brief in front of the dispatcher at the one moment they change behaviour, instead of
being re-typed from memory. It cannot be built against the hook as it stands.

The PreToolUse hook builds the subject its tool rules match against from four keys, taken in
this fallback order:

| key | carried by |
| --- | --- |
| `command` | `Bash` |
| `skill` | `Skill` |
| `file_path` | `Read`, `Edit`, `Write` |
| `pattern` | `Glob`, `Grep` |

An `Agent` payload carries `subagent_type`, `description` and `prompt`. **None of those is
read.** The subject is empty, and the hook returns `{}` and exits *before* the loop that
walks the layers. So a `tool: Agent` row cannot match -- at any layer, under any `match:`,
in any mode, `mode: block` included. It would index cleanly, list healthy in a diagnostic,
and never once fire.

**Re-measure rather than trusting this file.** Point `CLAUDE_PROJECT_DIR` at a tree holding
a layer with an `Agent` rule and a `Bash` rule, both `match: ~.*`, and drive the hook twice:

```
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | bash .../pre-tool-hook.sh
printf '%s' '{"tool_name":"Agent","tool_input":{"subagent_type":"x","prompt":"y"}}' | bash .../pre-tool-hook.sh
```

The `Bash` call is the control. If it says nothing either, the harness is blind and the
second answer means nothing -- that is not evidence the gap is still there.

**If the `Agent` call now injects, this file is stale**, and a record of a gap that has
closed is worse than no record, because it is read as current. It is not edited here: this
whole layer is generated and replaced wholesale on every install, so a correction made in
this directory is gone the next time the owning plugin writes it. Report it instead, and
whoever maintains that plugin has a test that fails on the same day this sentence stops
being true.

Two things wait on that day, neither of which the hook can answer now: the rule would fire
on *every* dispatch rather than one kind, so it can only carry what is true of any subagent;
and it should point at where the clauses live rather than restate them, because the second
copy is the one that drifts and the one people quote.
