---
title: "A command whose exit path matters, piped into head/tail, can silently drop the failure"
description: "SIGPIPE from an early-closed pipe, or a wrapper reporting the pipeline's last command's exit code, both hide a real failure behind a clean-looking success. Redirect to a file and read the file, or let the command print in full."
tool: Bash
match: ~\|[[:space:]]*(head|tail)([[:space:];&|><)]|$)
mode: remind
---

**Two incidents, same mechanism, different callers.**

- **`git rebase --continue 2>&1 | head -20`** (#1532) printed commit 1's summary and stopped at 20
  lines -- that is what `head -20` is for. Closing the pipe early sends `SIGPIPE` to git partway
  through its own output. A *later* `rebase --continue` then printed `Successfully rebased` and
  exited 0, but the branch had **one** commit where two were expected -- the second, carrying a real
  bug fix, was silently dropped with no conflict ever reported for it. `git log --oneline
  <upstream>..HEAD` against the expected count was the only reliable tell; `git status` said "clean"
  either way.
- **`python3 scripts/pr_green.py 1537 --wait --budget 1500` run with `run_in_background`, piped
  through `| tail -25`** (#1530): `--budget` is not a real flag, so argparse refused and exited 2 --
  but the harness notification read `completed (exit code 0)`, because a pipeline's exit status is
  its last command's (`tail`'s) unless `pipefail` is set. A caller trusting the notification alone
  would have concluded the wait ran and returned green; only reading the output file surfaced the
  argparse error text.

**Never pipe a command whose exit code or full output matters -- a rebase/push/merge/cherry-pick
continuation, a background wait, anything where "it printed something and exited" is being read as
"it succeeded" -- into `head` or `tail`.** Redirect to a file and read the file, or let it print in
full. After any multi-commit rebase, count the commits (`git log --oneline <upstream>..HEAD` against
the number you started with) rather than trusting "Successfully rebased", and grep for a symbol only
the later commit introduced -- counting catches a dropped commit, grepping catches one that applied as
empty.
