---
title: "worktree_reap.py's branch_merge_state lets an older PR row overwrite a newer OPEN one"
description: "gh pr list returns newest-first; branch_merge_state's loop keeps overwriting state with each row, so a branch whose older PR was closed and newer PR is still open reads closed overall -- plan_reap then force-removes a live lane's worktree."
match: (^|/)scripts/worktree_reap\.py$
---

**`branch_merge_state` (scripts/worktree_reap.py) only makes `MERGED` sticky, not `OPEN`.** Its
row loop does `if state == _STALE_PR_STATE: continue` (the sticky guard for the already-merged
case), then unconditionally `state = row_state` for every other row -- so the LAST row it
processes wins. `gh pr list` returns newest-first, and the loop iterates in that order, so the
last-processed row is the OLDEST one on record.

**Confirmed:** a branch whose newer PR is OPEN and whose older PR was CLOSED reads `"closed"`
overall (the older row overwrites the newer). `plan_reap` then marks the tree reapable and runs
`git worktree remove --force` plus `git branch -D` -- destroying a live, idle lane's worktree
while its own PR is still open. Nothing pushed is lost, but the tree and its uncommitted state
are gone.

**Fix direction (not yet built):** make an OPEN row win regardless of row order/position, the
same way `MERGED` already does -- an OPEN PR is not a decision yet, so it should outrank any
CLOSED row processed after it, not be overwritten by one. Existing tests only cover single-row
fixtures (`tests/test_worktree_reap_1628.py`); a mixed `[OPEN, CLOSED]` fixture asserting
`not-merged` (or the equivalent open-wins state) is what would catch this before it reaps a live
tree (#1637).

**Same precedence, reasoned but not observed:** it can also reap a reused `doctor/<check-slug>`
branch (#1703) while its new PR is open, since "MERGED wins forever" plus "last row otherwise
wins" applies identically there.

Routed via /oss:curate from `trap.d/1637.reap-precedence-can-drop-a-live-open-prs-worktree.md`.
