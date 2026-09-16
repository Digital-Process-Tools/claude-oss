---
title: "A refused Bash call may have partially run, and /tmp is not private across one"
description: "The no-|-tail guard (and similar refusals) refuse the WHOLE call, but an earlier command in the same chain can still have executed against stale state. Never reuse /tmp/*.toml as a payload path across a refused-and-retried call -- use the session scratchpad."
tool: Bash
match: ~/tmp/
mode: once
---

A refusal (this repo's own no-`|`-tail guard, among others) refuses the **whole** chained Bash
call, but is all-or-nothing only from the caller's point of view: an earlier command in the same
chain can still have run. A retry then re-ran a heredoc write to a stale `/tmp/*.toml` path, whose
leftover content from before this session matched an `old` anchor in the WRONG file and edited it
silently -- validators passed because the result was syntactically fine. Caught only by a habitual
`git status --short` (#1345).

- **Never assume a refused multi-command call refused only the part the error named.** Re-run the
  whole chain, or verify each earlier command's effect before trusting the retry's output.
- **`/tmp/*` is not reliably private to one session or one call.** Use this session's own
  scratchpad directory instead.
- **The scratchpad is per-session, not per-lane, and is not immune either (#1466).** A staged,
  verified commit-message file was overwritten by a concurrent lane between the verify and the
  `git-commit` call that consumed it; the commit that landed carried a different issue's message
  verbatim, caught only by a routine `git log -1` afterwards. Re-read a file right before the call
  that consumes it whenever a concurrent lane could have touched the same path.
