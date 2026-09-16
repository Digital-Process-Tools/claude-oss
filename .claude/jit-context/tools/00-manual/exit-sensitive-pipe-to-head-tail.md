---
title: "A command whose exit path matters, piped into head/tail, can silently drop the failure"
description: "SIGPIPE from an early-closed pipe, or a wrapper reporting the pipeline's last command's exit code, both hide a real failure behind a clean-looking success. Redirect to a file and read the file, or let the command print in full."
tool: Bash
match: ~\|[[:space:]]*(head|tail)([[:space:];&|><)]|$)
mode: remind
---

Never pipe a command whose exit code matters -- a rebase/push/merge/cherry-pick
continuation, a background wait -- into head/tail. SIGPIPE truncates it; a
pipeline's exit status is tail's, not the command's. Redirect to a file and read
the file. After a multi-commit rebase, count commits
(`git log --oneline <upstream>..HEAD`). (#1532, #1530)
