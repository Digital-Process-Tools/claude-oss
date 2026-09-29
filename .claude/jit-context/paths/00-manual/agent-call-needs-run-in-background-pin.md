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

**The pin can be present in the file's own text and still be dropped or ignored at call time
(#1770).** Two real-session observations, both on a managed repo's own first `/oss:run`: a
scheduler spawning `oss:doctor` per `commands/run.md` step 1's own `run_in_background: false` pin
issued the actual tool call with no `run_in_background` field at all (the harness reported "Async
agent launched successfully" and the hand-back arrived ~10.5 minutes later as a message from
another session) -- the model paraphrased the call and dropped the token. A same-day correction
found the opposite failure mode too: a session spawning `oss:sub-manager` with
`run_in_background: false` passed explicitly still got "Async agent launched successfully... The
agent is working in the background" -- on that harness version the pin can be present and still be
ignored. Either way, **prose in a command file cannot make a spawn blocking.** Anything in the loop
that assumes a blocking spawn (reading a result "in the same turn," rather than waiting for a
completion notification or `SendMessage`) should be checked against this rather than trusted.
