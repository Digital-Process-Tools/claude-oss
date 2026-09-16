---
title: "A command whose exit path matters, piped into head/tail, can silently drop the failure"
description: "SIGPIPE from an early-closed pipe, or a wrapper reporting the pipeline's last command's exit code, both hide a real failure behind a clean-looking success. Redirect to a file and read the file, or let the command print in full."
tool: Bash
match: ~\|[[:space:]]*(head|tail)([[:space:];&|><)]|$)
mode: once
---

Never pipe a command whose exit code matters -- a rebase/push/merge/cherry-pick
continuation, a background wait -- into head/tail. SIGPIPE truncates it; a
pipeline's exit status is tail's, not the command's. Redirect to a file and read
the file. After a multi-commit rebase, both count commits
(`git log --oneline <upstream>..HEAD`) AND grep for a symbol only the later commit
introduced -- counting catches a dropped commit, grepping catches one that applied
as empty. (#1532, #1530)
