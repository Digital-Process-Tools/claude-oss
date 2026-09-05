---
title: "How the loop's markdown is managed: three tiers, replace-don't-append, split by subject"
description: "Route a lesson before writing it. Budgets are declared in three registries and hand-copied into CLAUDE.md, so baseline and budget move in the same diff. Split on subject, never size -- and measured 2026-09-05, there is almost no duplication left to extract."
keywords: phase file, manager spine, byte budget, document budget, split a document, loop prose
---

**Three tiers, and routing comes before writing.** `CLAUDE.md` is loaded whole on every session, so
only what governs every session regardless of what it touches lives there. Knowledge that fires on
touching a file, using a tool or meeting a term is a jit rule. Knowledge that governs a phase or an
agent is a `skills/manager/phases/*.md` or an `agents/*.md`. #245 is the precedent for moving, and
**a lane never appends to `CLAUDE.md`** -- it writes to `trap.d/` and `/oss:curate` decides later.

**The shape: a spine plus phase files.** `SKILL.md` 122,423 B became a 44,358 B spine plus seven
phase files; `agents/developer.md` 89,714 B became 47,819 B plus three. The spine carries **the
decision** for each phase; the phase file carries the argument -- the incident, the measurement, the
approach rejected. Quote both numbers when citing a split, or the saving reads as free.

**The split's own defect, named rather than solved:** an unread phase file is a rule that did not
run, and that renders exactly like a rule with nothing to say. Nothing here can observe whether a
reader opened one, so each phase states `read` / `not-read` / `could-not-read` beside its result, and
the only enforceable half is `skill_phases.check()` reporting `unreferenced` for a file the spine has
stopped naming. Never let a rule live **only** in the phase file.

**Split on subject, never on size.** #725 (`dispatch.md`) and #694 (`accounting.md`) both *declined*
splits: one subject wearing two names, where a fresh file plus its spine block would cost more than
it saved. #958 accepted one because ranking a finding is genuinely not the subject of choosing what
to dispatch. Make that argument in the diff; a byte count is not it.

**Not jit-context, for a directive.** #958 refused that route: jit's shown-set dedup is keyed on
`session_id` and a spawned agent inherits its parent's, so scheduler, sub-manager and every lane are
one session -- a directive moved there reaches an agent only if nothing earlier tripped the same
match. That is a rule that silently did not run.

**Budgets: replace, don't append.** `scripts/agent_budgets.py`, `skill_phases.py` and
`command_budgets.py` declare them; `CLAUDE.md` carries three hand-copied tables of the same numbers.
Pay for a paragraph by cutting one, or raise the ceiling in the same diff with a sentence saying what
was weighed. **Move baseline and budget together** -- `check()` compares only against the ceiling, so
a baseline can drift from disk unnoticed, which is why `tests/test_baseline_matches_disk_1014.py`
exists and why #1029 went red on `main`.

**Do not propose a deduplication sweep.** Measured 2026-09-05 over 27 files / 598,017 B: 6 exact
duplicate paragraph classes (~7 KB, mostly the phase headers the split knowingly pays for) and 4 file
pairs out of 351 sharing 150+ 8-grams. The two splits already took the redundancy. The one real
multi-parent candidate is `agents/auditor.md` / `release-auditor.md` at ~10% (#1071); everything else
is a pointer doing its job.

**This prose is executed.** Table cells are run verbatim by a session that cannot check them first,
and nothing guards that a script path named in a brief exists (#1070). A rename lands green and each
stale cell becomes an exit-2 an agent hits mid-lane.
