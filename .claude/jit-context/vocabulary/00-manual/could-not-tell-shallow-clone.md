---
title: "A could-not-tell naming \"shallow\" on a clone that was full recently is not a GitHub problem"
description: "next_action.py ranked release and triage both could-not-tell with 'the clone is shallow, so its history is truncated'. The shared clone had gone shallow mid-run from a --depth fetch nobody could identify; check .git/shallow first."
keywords: shallow, could-not-tell, release_delta, is-shallow-repository, unshallow
---

**A `could-not-tell` citing "shallow" is telling you about this clone's own
history, not about GitHub, a rate limit, or a real ambiguity in the
underlying data.** Observed (#1493): after a tick's handback,
`next_action.py --root . --json` ranked both `release` and `triage` as
`could-not-tell`, each citing `release_delta`: "the clone is shallow, so its
history is truncated and a delta over it is not the delta". The shared
clone had genuinely gone shallow -- `git rev-parse
--is-shallow-repository` answered `true`, and `.git/shallow` held exactly
one sha: the most recent release commit, tagged a couple of hours earlier.

**Check `.git/shallow` first, before assuming the tool is confused.** Its
one line names roughly when the truncation happened -- here, right around
the last tag, which is itself a clue about what ran a `--depth` fetch
against the shared clone rather than a scratch worktree. The actual writer
was never identified in this incident (no fetch in the state file, nothing
in `git reflog`), but the fix is mechanical either way:

    git fetch --unshallow origin

**Cost of not checking:** both the release and triage triggers were
unreadable, so the scheduler could not rank either candidate until the
fetch ran. **A lane that reproduces a shallow checkout for its own testing
purposes must do it in its own worktree, never against the one shared clone
the scheduler and every other lane also reads from.**

**A truncated shallow-clone commit count can render as exact somewhere other
than `release_delta.py` too.** `scripts/statusline.py`'s own
`since_floor = len(commits) >= window` (confirmed still unguarded) treats a
short `git log` as proof the release-boundary commit was actually reached;
in a shallow clone `git log` stops at the graft point rather than the true
boundary, so a truncated count can satisfy `>= window` and render as an
exact figure (`rel 50/?`, no `+` marker) instead of the honest "at least N,
could be more". `release_delta.py` already refuses to operate on a shallow
clone for exactly this reason -- `statusline.py` does not (#1692).
