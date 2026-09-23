---
title: "release_gate2.py crashes, uncaught, on a comment age of the wrong type"
description: "latest_review_comment_age_minutes as a string reaches a bare `age < threshold_minutes` with no type check, raises TypeError, and the script's own top-level exit-1 catches it -- so a malformed field renders exactly like blocked, not could-not-tell. Reproduced directly."
match: (^|/)scripts/release_gate2\.py$
---

**A present-but-wrong-TYPE field is not the same gap #1706 already closed.** #1706 fixed the
top-level "field absent" shape (`could-not-tell` when `latest_review_comment_age_minutes` is
missing from the payload entirely, distinct from an explicit `null`). It did not add a type
check to the comparison itself: `if age is not None and age < threshold_minutes` still runs a
bare `<` with no `isinstance` guard.

**Reproduced directly:**

```bash
echo '[{"number":1,"review_decision":"NONE","lane_active":false,"latest_review_comment_age_minutes":"5"}]' \
  | python3 scripts/release_gate2.py --prs-json -
# Traceback ... TypeError: '<' not supported between instances of 'str' and 'int'
# exit 1
```

**Why this matters here specifically:** the script's own top-level exit code for a genuine
`blocked` disposition is also `1` (`EXIT_BLOCKED`), and nothing catches the `TypeError` before it
propagates to that same exit code. A malformed field therefore renders EXACTLY like "in-flight,
release blocked" rather than like "could not tell" -- this repo's own named defect class, applied
to gate 2's own numeric field.

**Fix direction (not yet built):** type-check `age` (and any other field this decision reads)
before the comparison, and return `could-not-tell` (exit 2) on a bad type -- the same shape #1706
already gave a missing key (#1706's own extension, filed as this same issue's follow-on).

Routed via /oss:curate from `trap.d/1706.release-gate2-crashes-closed-on-a-non-int-comment-age.md`.
