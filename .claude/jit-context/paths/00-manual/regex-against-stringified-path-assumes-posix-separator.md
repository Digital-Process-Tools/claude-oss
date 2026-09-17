---
title: "A regex matched against str(Path) assumes the host's own separator, quietly"
description: "_WORKTREE_RE = re.compile(r'-wt/(\d+)\b') only matches a forward-slash-separated worktree path; str(Path) on Windows renders with a backslash, so a real Windows-run transcript never matches and falls through to unattributed rather than erroring."
match: (^|/)scripts/[^/]+\.py$
---

**`scripts/loop_cost_report.py`'s `_WORKTREE_RE` (#1618) only matches a forward-slash-separated
worktree path**, because `scripts/lane_setup_worktree.py`'s `derive_worktree()` builds the path with
`oss_config.resolve_worktree(...)` and reports it as `str(path)` -- a `pathlib.Path` stringified
with the *host's* native separator. POSIX renders `/`; Windows renders `\`. A real Windows-run
transcript's worktree path never matches the regex, so its `oss:auditor` spend silently falls
through to `RULE_UNATTRIBUTED` rather than being attributed under its issue -- not a dropped
record (the `unattributed` bucket is explicit and the reconciliation total still holds), but a
class of Windows-only misreport a test written against a hardcoded POSIX-separated fixture string
cannot catch even on a real Windows CI leg, because the fixture itself is not OS-dependent.

**A sibling regex beside the same problem is not automatically the same risk.** `_BRANCH_RE`, the
branch-name fallback next to `_WORKTREE_RE`, is fine as-is: git branch names are always
forward-slash-separated regardless of host OS. Check what actually produced the string being
matched -- a stringified filesystem path carries the host separator, a git ref name never does --
before assuming a fix for one applies to the other.

**Fix shape, when this needs fixing:** split the string on either separator before matching
(`re.split(r"[\\/]", text)`) or normalize with `PurePath`/`os.path.basename` first, rather than
hardcoding `/` into the pattern.

Reasoned, not observed -- confirmed against the regex literal and `derive_worktree`'s own
`str(path)` call, no Windows machine available to reproduce the actual mismatch.
