---
title: "trap.d/: log it and move on, decide nothing"
description: "One file per trap, <issue>.<slug>.md, no frontmatter required. Do not choose a dimension, write a match pattern, or judge whether it is worth keeping -- that is /oss:curate's, taken later with every fragment visible at once."
match: (^|/)trap\.d/
---

**Log it and move on.** Hesitating because you are not sure it is worth recording is the exact
failure this directory removes. Write it; let the pass throw it away.

- **Name:** `trap.d/<issue>.<slug>.md` — the issue that was being worked on, and a slug so two
  fragments on one issue never collide on a path. Both halves are required; `904.md` does not parse.
- **No frontmatter.** No `title:`, no `match:`, no `keywords:`. Prose is fine.
- **Decide nothing.** Not the dimension, not the match pattern, not whether it earns a rule.
  `/oss:curate` does that later, holding every fragment at once — which is the only position from
  which "these three are one rule" is visible, and it is not the position you are in.

What helps whoever curates it:

| | |
| --- | --- |
| **what was observed** | the behaviour, not the theory |
| **where** | the file, the command, the error string, verbatim |
| **what it cost** | a CI round, a retracted conclusion, ten minutes |
| **how it was confirmed** | what you changed to make it go away, or what you measured |

Unsure whether it belongs upstream, or is even a real rule? **Say so in the fragment and log it
anyway** — "possibly this belongs in supertool's docs rather than here" is a useful line for the
curator and costs you nothing.

Fragments are **inert**: nothing loads them into a session. The cost of that is bounded — only a lane
touching the same file within the same release cycle misses the lesson. Making them live would mean
every unfiltered observation firing on every matching session forever.

`python3 scripts/trap_curate.py .` says how many are waiting, in three states.
