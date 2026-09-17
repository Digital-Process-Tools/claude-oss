---
title: "Resolving a CONFLICTING pull request by hand and committing normally never clears it"
description: "GitHub (and git merge-tree) compute mergeable state from the commit graph, not from content -- a single-parent commit that merely matches what a real merge would produce still resolves merge-base to the old fork point, so CONFLICTING never clears no matter how correct the hand-written content is."
keywords: merge conflict, conflicting, mergeable, hand-resolve, single parent, merge origin/main, git merge-tree
---

**A pull request reporting `mergeable: CONFLICTING` is a graph fact, not a content fact.** Editing
the branch's files by hand to match what a real merge of the target branch would produce, then
committing that with a plain `git commit` (one parent), does not clear it: `git merge-base HEAD
origin/main` still resolves to the old fork point regardless of how correct the hand-resolved
content is, so GitHub keeps reporting `CONFLICTING` and re-polling never clears a state that was
never cached in the first place -- it is recomputed from the graph every time (#1637).

**Observed on PR #1637** (Digital-Process-Tools/claude-oss): a commit message said "Merge
origin/main into fix/1623", but `git log -1 --format='%P'` on that commit showed exactly one
parent. `gh-pr:1637:full` still reported "Conflicts: YES" well after the push, and `git merge-tree
$(git merge-base HEAD origin/main) HEAD origin/main` reproduced the identical conflict markers
locally -- confirming the mergeable state was correct, not stale. The diff against main also
pulled in every file merged to main since the fork (51 files instead of the lane's own ~15), since
the merge-base git actually uses predates that content.

**Fix: run a real `git merge origin/main` (or rebase and force-push), never hand-write the
post-merge result and commit it as a normal, single-parent commit.** If the content needs custom
combination logic (two parallel lanes touching the same line, e.g. a shared byte-budget table
row), do that combination *inside* the real merge -- resolve the conflict markers `git merge`
leaves in the working tree, then `git commit` the merge as-is. A two-parent commit is what moves
`merge-base` forward; nothing else does.
