---
title: "git-commit:@- refuses \"no PATHS were given\" even when the payload lists a message"
description: "The op wants an explicit paths array, not just message -- and its own refusal already prints every dirty path. Copy them into the payload rather than treating it as a dead end."
tool: Bash
match: ~git-commit
mode: remind
---

`git-commit:@-` with only `message` in the payload refuses: "no PATHS
were given" -- even though every dirty path is already printed in that
same refusal. It is not "nothing is staged", it is "name what to commit
explicitly." Add a `paths` array (the exact list the error names, or
`git status --porcelain` output) to the same payload and resend.

Cost: one extra round trip. Observed by the fix/1467 lane (#1467, #1556).
