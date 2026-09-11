---
title: "A frontmatter key spelled wrong is silently ignored, not rejected"
description: "user_invocable vs user-invocable: an unrecognised frontmatter key does nothing, and a test asserting the file's own text proves nothing about whether the harness reads that key. Check the harness's own docs before trusting a frontmatter key does anything."
match: (^|/)(agents|commands|skills)/.*\.md$
---

`skills/manager/SKILL.md` carried `user_invocable: true` (underscore) for its whole life; the
harness's documented key is `user-invocable` (hyphen). The misspelled key was never read, so the
skill appeared in the `/` picker not because it asked to, but because appearing is the default for
a skill with no recognised visibility key at all. Flipping the same misspelled key to `false`
(#1391's own first attempt) left the picker listing exactly as it was -- a change that read as
correct (frontmatter edited, a test written and shown red-then-green) and did nothing at all to the
behaviour the issue was about.

**A test asserting a frontmatter key equals a value proves nothing about whether the harness reads
that key.** `tests/test_manager_not_user_invocable_1391.py` genuinely went red-then-green on the
`true`->`false` edit -- it was pinning the file's own text, not the harness's behaviour. Grepping
this repo's own installed plugin cache for other instances of the same spelling only proves internal
consistency, never correctness.

**Nothing in this repo's own tooling validates frontmatter keys against the harness's recognised
set** (`markdownlint`/`gitleaks` don't know YAML schema). Before trusting a frontmatter key does
anything, check it against the harness's own documentation
(https://code.claude.com/docs/en/skills for skill keys), not against the file's own history or
other files' apparent agreement with it.

Routed via /oss:curate from `trap.d/1391.skill-frontmatter-underscore-vs-hyphen.md`.
