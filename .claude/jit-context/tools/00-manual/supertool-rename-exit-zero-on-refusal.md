---
title: "supertool rename: can refuse and exit 0 -- do not trust || / && after it"
description: "'./supertool rename:OLD:NEW' printed 'rename: missing file path' (a refusal) but exited 0, so the shell's || fallback never ran and the && success branch did. The session was told 'renamed' for a rename that never happened."
tool: Bash
match: ~rename:
mode: once
---

**A `rename:` refusal can exit 0.** Every other measured supertool op signals failure loudly
(`git-worktrees` returns distinct 1/2/3 codes with a footer explaining why; `batch` exits 1 when any
op refuses) -- `rename` is the outlier. Do not chain `rename:... || fallback` or `rename:... &&
echo done` and trust the exit code; **read the op's own output text**, and confirm with a follow-up
`ls`/`git-status` that the file actually moved before reporting success.

Not established: whether every `rename` refusal exits 0, or only this argument-shape one, and
whether a correct invocation exists (`help:rename` was not checked). Either way, verify the result
directly rather than trusting the exit code for this op.
