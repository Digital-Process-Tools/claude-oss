---
title: "A bare #NNNN at the start of a physical line trips markdownlint MD018"
description: "MD018 (no space after # on an ATX heading) cannot tell a heading from prose that happens to start a line with an issue cross-reference like #1629 -- rewrap so the line starts with a word instead."
match: (^|/)(CLAUDE\.md|agents/.+\.md|commands/.+\.md|skills/manager/.+\.md|trap\.d/.+\.md|\.claude/jit-context/.+\.md)$
---

**markdownlint's MD018 fires on the character position, not on meaning.** A paragraph like
`**Re-baselined for #1629**...` is ordinary prose, but if the wrap happens to put `#1629` at the
very start of a physical line, MD018 reads it as an ATX heading missing its space
(`#NNNN` looks exactly like `#heading`) and refuses. This repo's own `.markdownlint.json` enables
MD018 via `"default": true` with no rule-specific exception, so there is no config escape --
the fix is in the prose, not the config.

**Fix: rewrap so no physical line begins with a bare `#NNNN`.** A leading word before the
reference (`issue #1629`, `See #1629`, `-- #1629 changed this`) is enough; only a line-initial
`#` followed directly by digits trips the rule. Hit twice drafting one PR's `CLAUDE.md` prose
(#1629) -- check whether a paragraph's own natural wrap point lands a bare `#NNNN` at column 1
before sending the edit, rather than discovering it from the refusal.
