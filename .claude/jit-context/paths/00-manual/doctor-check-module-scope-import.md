---
title: "A new scripts/doctor_check_*.py: don't import doctor at module scope"
description: "doctor.py imports every doctor_check_X submodule; a submodule importing doctor back at module scope is a circular ImportError the moment the submodule (or its own test) loads before doctor.py does."
match: (^|/)scripts/doctor_check_[^/]+\.py$
---

`doctor.py` does `from doctor_check_X import check_X` for every `doctor_check_*.py` submodule under
the #497/#630 convention. A submodule that does `import doctor` at its own module scope collides
with that the moment the submodule (or a test importing it directly) is loaded before `doctor.py`
is -- a circular `ImportError`, reproducible live and confirmed pre-existing in roughly twenty
siblings (`doctor_check_clone_head.py`, `doctor_check_vanished_worktree.py`,
`doctor_check_stale_branches.py`, `doctor_check_branch_protection.py`, and more). Masked in the
ordinary case because every existing sibling's own test imports `doctor` first, not the submodule
directly.

If a `doctor_check_*.py` module genuinely needs something from `doctor.py`, import it lazily --
inside the function that needs it -- never at module scope.

Routed via /oss:curate from `trap.d/1350.doctor-check-circular-import-systemic.md`.
