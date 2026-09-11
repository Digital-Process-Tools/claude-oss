---
title: "A refused Bash call may have partially run, and /tmp is not private across one"
description: "The no-|-tail guard (and similar refusals) refuse the WHOLE call, but an earlier command in the same chain can still have executed against stale state. Never reuse /tmp/*.toml as a payload path across a refused-and-retried call -- use the session scratchpad."
tool: Bash
match: ~/tmp/
mode: remind
---

A single Bash call chaining `python3 - <<'PYEOF' ... open("/tmp/e5.toml", "w") ... PYEOF` with
`supertool 'edit:@-' < /tmp/e5.toml | tail -30` was refused whole by this repo's own
no-`|`-tail-on-a-supertool-op guard. The refusal names the offending command, but the call is
all-or-nothing from the caller's point of view: nothing signals which earlier command in the chain
actually ran. On retry (same call, `| tail` removed), the heredoc write to `/tmp/e5.toml` ran, but
`edit:@-` read stale content left at that exact path by something else on the machine, from before
this session -- and it happened to match an `old` anchor in the WRONG file, editing it successfully
with no error (validators all passed, because the resulting file was syntactically fine).

Caught only by a habitual `git status --short` right after the "successful" edit; the tool's own
success output gave no indication anything was wrong.

- **Never assume a refused multi-command Bash call refused only the part the error message
  named.** Re-run the whole chain, or verify each earlier command's effect before trusting its
  output.
- **`/tmp/*` scratch paths are not reliably private to one session or one call.** Use this
  session's own scratchpad directory instead, which the developer brief already directs writes
  toward.

Routed via /oss:curate from `trap.d/1345.tmp-toml-collision-blocked-heredoc.md`.
