---
title: "A closing keyword next to an issue number closes it, denial included"
description: "GitHub matches a closing keyword followed by a reference anywhere in the body, with no notion of the surrounding sentence, so 'does not close #N' closes #N. no_close: true does not stop it."
tool: Bash
match: ~gh-pr-create|gh-pr-edit|gh-pr-merge
mode: remind
---

**Never write a closing keyword next to an issue number you do not want
closed, in any form, including a denial.** Say "#N stays open" or "this
is not a fix for #N" -- never "does not close #N", "do not fix #N",
"does not resolve #N", or any other spelling GitHub accepts.

Measured (#1075, merging PR #1076 as 06c85e2): a section headed "What
this does not do" opened with **"It does not close #1075."** The merge
reported `#1075: CLOSED`. The paragraph written to say the issue stays
open is what closed it, and the merge output reported the closure as a
normal successful outcome.

`no_close: true` in the payload does **not** prevent this. It is the
op's own switch for "this pull request closes nothing"; the create
output still printed the parsed reference, and GitHub still acted on the
body. Both readings were correct about what GitHub would do -- the
intent lives in a sentence and the mechanism lives in a regex, and
nothing compares them.

**Read the merge output's `## Linked issues` block before moving on.**
That is what caught it; nothing else can. The issue closed was, in the
same hour, a stated precondition for another one.

Same defect one tool over: `waiting-on-a-status-line.md` -- a grep for
`ALL GREEN` matched `NOT ALL GREEN`.
