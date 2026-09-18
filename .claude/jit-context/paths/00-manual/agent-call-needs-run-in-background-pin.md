---
title: "Every Agent(subagent_type: ...) call needs an explicit run_in_background token -- never a bare call"
description: "A bare Agent(...) spawn with no run_in_background pin has been found and fixed piecemeal, one grep-hit per issue (#1586 doctor spawns, #1649 the releaser spawn) -- the same class recurring because nothing sweeps the whole family at once."
match: (^|/)(commands/.*\.md|agents/.*\.md)$
---

**Every `Agent(subagent_type: "oss:...")` call written in `commands/*.md` or `agents/*.md` must
carry an explicit `run_in_background: true` or `run_in_background: false`, never a bare call with
the token omitted.** A bare call has been the wrong default before: an unpinned spawn observed
satisfying an ordering rule by backgrounding itself and then doing the work itself anyway, paying
for both (#1586). Before adding a new `Agent(...)` call, or editing a file near an existing one,
`grep -n 'Agent(subagent_type'` the file and confirm every hit names the token.
