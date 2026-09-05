---
title: "scripts/: one script, one LLM problem -- and a submodule has to look like one"
description: "A script earns existence when an LLM does the job wrong without it. If it is one of several pieces the caller still joins, it is worse than none. doctor.py is the shape: one entry point, N prefixed modules, and the prose that names them is part of any rename."
match: (^|/)scripts/[^/]+\.py$
---

**The unit is the LLM's problem, not the code's cohesion.** A script earns existence when an LLM
does the job **wrong** without it -- and the failure this repository keeps paying for is a third
state lost in a hand-join (`could-not-read` collapsing into `found nothing`). That is why
`select_issues.py` exists (#970). If nothing goes wrong without it, it is a library function.

**A script that leaves the caller holding a join is worse than none.** It reads as tooling and the
join stays where the states die. So the test for merging two scripts is never size -- it is whether
an LLM is left joining them.

**`doctor.py` is the shape.** One entry point; 19 `doctor_check_*.py` modules, none carrying a
`__main__`. Measured 2026-09-05: 38 of 61 modules under `scripts/` carry a `__main__`, so 38 entry
points claim 38 LLM problems, and five families hold 29 of them. Before adding an entry point, name
the LLM problem it answers and check no existing one already answers it.

**A submodule must look like a submodule.** Prefix it with its entry point's own name --
`doctor_check_*`, `select_issues_*`, `lane_setup_*` -- so the grouping is visible in a directory
listing and not only in the import graph. A new `__main__` on a file with such a prefix is the
smell.

**The prose that names a script is part of the file.** `agents/*.md` and `skills/manager/**` name
these paths ~20 times for the dispatch family alone, several inside table cells a session runs
verbatim (`loop-prose-parity.md` records that trap). **`tests/test_unwired_scripts_253.py` guards
only the opposite direction** -- a script nothing references. Nothing checks that a path named in a
brief exists, so a rename lands green and every stale call site becomes an exit-2 an agent hits
mid-lane with the brief still telling it to. Update the prose in the same diff as the rename, and
if you are moving several, add the forward guard (#1069) with a positive control.

**Two vocabularies for one act was the same defect one level up, and #1069 is the fix, not a new
trap to watch for.** `issue_claim.py --claim` used to write the assignee while `lane_setup.py
--claim` registered the lane -- two scripts, two calls, both meaning *this issue is taken* -- and
the split was why rolling back a half-finished lane lived in prose (a jit-context reminder to run
`gh issue edit --remove-assignee @me` by hand) rather than in either script. `lane_setup.py --claim`
now does both in one call (`lane_setup_claim.claim_and_register`), rolling the assignee write back
in code when registration fails, named states throughout. The general lesson survives the specific
fix: **two names for one act is a signal to fold them**, checked the next time a script grows a
second vocabulary for something another script already claims to do.
