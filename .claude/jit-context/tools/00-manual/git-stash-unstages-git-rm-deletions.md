---
title: "git stash pop silently un-stages a git rm deletion"
description: "A stash push/pop round-trip is not transparent to a staged deletion: a file removed with git rm comes back D-in-worktree, still-tracked in the index. git ls-files reports the index, not the filesystem, so a guard built on it fails far from the cause."
tool: Bash
match: ~git[[:space:]]+stash
mode: remind
---

Observed 2026-09-15 (#1532): `git stash push -q -u` then `git stash pop -q`, used to compare two
failing tests against the base tree, silently restored eighteen `git rm`-deleted test files and one
script **to the index**. `git status --short` afterwards showed them as ` D` (deleted in the
working tree, still tracked) rather than `D ` (staged deletion). Nothing failed at the time.

It surfaced ~25 minutes later, at the end of a full suite run, as an unrelated-looking
`FileNotFoundError` from a guard that enumerates governing files with `git ls-files` and reads each
one — `git ls-files` reports **the index**, not the filesystem, so a file deleted from the worktree
but restored to the index is listed and then cannot be opened. The error names the file, not the
cause.

- **If a lane uses a stash round-trip mid-run to check something against its base, `git add -A`
  afterwards and check `git status --short` for ` D` entries before believing the tree is what it
  should be.**
- **A guard built on `git ls-files` inherits this**, and will fail with a confusing
  `FileNotFoundError` far from the cause. A guard of that shape should skip a listed path that does
  not exist on disk, or say so, rather than raising.

Confirmed by `git ls-files | grep <deleted names>` returning the files, and fixed by `git add -A`.
