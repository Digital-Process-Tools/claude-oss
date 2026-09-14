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
