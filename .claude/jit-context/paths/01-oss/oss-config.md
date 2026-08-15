---
title: ".oss.json is config, not truth"
description: "Per-repo settings for the maintainer loop. Re-derive labels before acting; the CI leg count is not in here; null is an answer, not a gap."
match: \.oss\.json
---

Per-repo settings for the maintainer loop: `repo`, `default_branch`, `clone`, `worktree_root`,
`test_command`, `version_sites`, `labels`, `state_file`, `release`.

**Re-derive anything load-bearing before acting on it.** This file records what a probe observed on
the day it ran. `labels` rots first: they are spellings, and they differ between repos -- one spells
it `priority-high`, another `priority:high`. Read them off the repo before writing one, and never
invent a label that is not already there.

**The CI leg count is not a key here, and must not be added as one.** There was a
`ci.required_checks`; it counted workflow job declarations, which a build matrix, a reusable
workflow or an organisation/app-level check multiplies or adds to invisibly, so the number on disk
was never the merge gate's. Count the legs on the pull request they apply to, every time. Any leg
that is not a success gets named before merging -- cancelled, skipped, timed out and neutral are
none of them passes and none of them pendings. A config still carrying the block is harmless and
safe to delete; nothing reads it.

**`null` is an answer, not a gap.** `test_command` and `changelog_dir` may be null and mean "the
probe could not tell". Everything else null is a hole -- the probe found nothing and said nothing.

**No key here holds a credential.** The file is committed; tokens live in the forge CLI's own auth.
