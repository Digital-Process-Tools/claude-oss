---
title: "scripts/ and bin/ are surveyed whole, with no extension test"
description: "A suffix filter is the silent-skip defect wearing a different hat: a file a lint never received and a file it cleared both exit 0."
match: (^|/)(bin/[^/]+|scripts/shell_sources\.py|tests/test_unwired_scripts_253\.py)$
---

- **Never filter this survey by suffix.** `git ls-files '*.sh'` matched one path while
  `bin/oss-workspace` — tracked, POSIX `sh`, extensionless — was parsed by no leg for its whole life,
  and the leg stayed green: **a lint that found nothing and a lint that never received the file both
  exit 0.** A file skipped by a suffix test is not an offender and not unknown; it is never looked at.
- **`scripts/shell_sources.py` classifies by extension *or* shebang** and exists to solve exactly
  this. Use it for anything that needs to know "is this shell".
- **Do not reach for it when the better fix is dropping the classification.**
  `tests/test_unwired_scripts_253.py` deliberately does not call it: after the suffix test is gone
  there is no question left to ask, and `shell_sources.py` answers "is this shell", which was never
  the question.

**Same mistake one dimension over: an exclusion written as a name.**
`tests/test_jit_layer_set_sync_702.py` compared the `01-oss` layer on disk against the set
`scripts/oss_rules.py` ships, excluding exactly one filename — `00-index.tsv`, spelled as the
constant `INDEX`. A newer `claude-jit-context` rebuild writes a **second** generated index,
`01-paths.tsv`, into the same directories, and the check reported it as *in this repository's layer
and shipped by nobody*: one CI round, four red legs, on a pull request whose subject was unrelated.
Confirmed by deleting the file (green) and letting `rebuild-tsv.sh` recreate it (red again), so it
would have hit the next contributor who rebuilt. **An exclusion list written as a name is a bet that
the tool on the other side never adds a second file.** A rule in a jit layer is always a `.md`, so
the class — *not a `.tsv`* — is the boundary that cannot go stale this way. Exclude the class the
invariant is about, not the instance you have seen.
