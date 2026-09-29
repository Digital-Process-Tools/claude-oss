---
title: "gh-pr-merge refuses mergeable=UNKNOWN right after a sibling merge -- retry, do not read it as a conflict"
description: "Merging two green PRs back to back: the first merges, the second refuses with mergeable=UNKNOWN because GitHub recomputes mergeability asynchronously after main moves. Re-running the identical op about a minute later merges it cleanly."
tool: Bash
match: ~gh-pr-merge
mode: once
---

**Merging two green PRs back to back in one batch** (`gh-pr-merge:1771:squash|force` then
`gh-pr-merge:1773:squash|force`): the first merged; the second was **refused** with "GitHub
reports mergeable=UNKNOWN", because `main` had just moved and GitHub recomputes mergeability
asynchronously. Re-running the identical op about a minute later merged it cleanly.

**Cost: one extra call, no harm.** The op refuses rather than guessing, and its own output says
the retry is the remedy. **Expect `UNKNOWN` on every merge after the first** when a tick merges
several pull requests in one pass, and retry rather than reading it as a conflict or a gate
failure -- this is a distinct case from `SKILL.md`'s own classifier-denial rule (#1724), which
covers a different refusal shape (the call itself was denied) and also says retry once, report the
outcome either way, never a second time.

Routed via /oss:curate from `trap.d/1769.gh-pr-merge-unknown-right-after-a-sibling-merge.md`.
