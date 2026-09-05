---
title: "A doctor warning has a lifecycle, and 'clear them all' is a real instruction"
description: "Every WARN is removable by a manual op or by /oss:scaffold. One that is removable by neither is a defect in the check. And an unclearable WARN pins bin/oss-workspace's stateless route to /oss:doctor forever."
keywords: oss:doctor, doctor warning, doctor verdict, usable with gaps, clear the warnings, remove all warnings
---

`/oss:doctor` gives the overall status and then exists to get the count to zero. Two routes to zero,
and no third: **a manual op** (a `gh api` call, a settings change, installing a tool) or
**`/oss:scaffold`** (an owned file, the `01-oss` rule layer). Doctor itself never writes.

| line | what it is | what to do |
| --- | --- | --- |
| `OK` | checked, fine | nothing |
| `NOTICE` | the check has declared it can never answer (#764) | nothing -- it does not gate `VERDICT:` |
| `WARN` | ran and could not answer, or found a gap it CAN resolve | clear it |
| `FAIL` | checked, broken | clear it |
| `not checked` | the check never ran (5 lines say it when `.oss.json` is absent) | a gap in the measurement, not a finding |

**A WARN no op and no scaffold run can clear is a bug in the check, not work (#1065).** There is no
state for a false positive, so one renders as work and a maintainer does it -- and #1062's own remedy,
followed, would have displaced the CodeQL default setup already scanning this repository. When a WARN
cannot be cleared, file against the check.

**And an unclearable WARN is not merely noise -- it changes what the launcher does (#1064).**
`bin/oss-workspace` replaces `/oss:tick` with `/oss:doctor` whenever the pre-launch diagnostic returns
`usable with gaps` or `not usable`, and that route is stateless. So one standing WARN pins every
future session to the diagnostic and the loop stops ticking. That is why the zero matters and why a
`VERDICT: usable with gaps` that has been true for days is worth chasing rather than living with.
