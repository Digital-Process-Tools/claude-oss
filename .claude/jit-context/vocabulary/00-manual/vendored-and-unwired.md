---
title: "Vendored files, and checking whether anything actually uses one"
description: "A vendored file is a document about the repository it came from and stays one after you copy it. The axis is whether anything uses it -- and a check for unreferenced files must not count the documentation of a deletion."
keywords: vendored, vendoring, unwired script, unreferenced file, copied script, coverage gate
---

**A vendored file is a document about the repository it came from, and it keeps being one after you
copy it.** `scripts/coverage_gate.py` was a verbatim copy of another project's coverage gate, wired
into nothing here for its whole life. Every claim in it was true — *there*. Its floors named that
repo's directories; its "measured, not enforced" entry for `scripts/` carried that repo's reason,
and this repo's entire product is in `scripts/`, so asking it about `doctor.py` returned `measured`,
unfloored, with a confident reason belonging to somebody else.

- **The axis is whether anything uses it, not whether its prose looks wrong.** One false-looking
  sentence was filed against that file and the sentence was fine; the file was not.
- **Delete rather than fork.** Forking means maintaining another project's issue history for a gate
  nobody decided to adopt. `assemble_changelog.py` stays because it is the opposite case on the only
  axis that matters: many tracked files mention it and it ships into every scaffolded repo.
- **Quote the number the check produces.** `git grep -l assemble_changelog.py` says 34 — that `.` is
  a regex wildcard — counting every file says 33, and the check itself says 27. Prose and guard must
  describe the same measurement.

**A check for unreferenced files must not count the documentation of a deletion**, and a changelog
fragment is the case with teeth. Excluding `CHANGELOG.md` alone is not enough: the commit that
deleted the unwired file also added a `CLAUDE.md` note, a `changelog.d/` fragment and a regression
test, so a general check called the file **wired** by the three files whose entire subject is that it
was deleted for being unwired. The fragment is worst — `changelog.d/` is emptied at the fold, so a
file whose only reference is its own fragment is wired today and unwired the moment a release is cut,
producing a red build on a release branch caused by nothing in that branch's diff.

- **Exclude narrative sources as a set**, and have the checking module exclude itself by deriving its
  own path from `__file__` rather than spelling it out.
