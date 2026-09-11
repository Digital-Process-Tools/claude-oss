# CI green: the one call, shared by whoever has to wait on it

**Read this when** you have to know whether a pull request has gone green -- a sub-manager
merging, or a releaser landing gate 3's blocking fix. Both spawns open `Skill(manager)`, so this
is the one place the read lives rather than a second copy in either agent's own definition.

---

**Never hand-write a CI wait loop (#1086).** `until ... | grep -qE "ALL GREEN|failed"` is #1066's
own trap: the op prints `NOT ALL GREEN`, which *contains* the substring `ALL GREEN`, so the loop
exited green with checks still pending. A hand-rolled prose match cannot tell a negated line from
the positive it negates.

Call the script instead, verbatim:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_green.py" NUM [NUM...] --wait
```

(or `--all-open` in place of one or more numbers, to scan every open pull request). It answers as
an **exit code**, never a line to grep:

| state | exit | meaning |
| --- | --- | --- |
| `green` | 0 | every leg in the check rollup concluded and passed |
| `red` | 1 | a leg failed, or reported a conclusion this script has never seen |
| `pending` | 2 | every leg is still running, or the rollup is empty |
| `could-not-read` | 3 | the read failed -- `gh` unreachable, non-zero exit, unparsable output |

A leg superseded by a later run of the same check name is excluded from `red` (#1458), matching
`gh-pr:N:status`.

It scans the named pull requests in order and stops at the first not pending -- no wait-for-all,
so a red pull request is reported the instant it is seen rather than behind a slower neighbour.
Its `red` line already carries the branch, the failing legs, the sha and the shortest decisive log
line -- brief a developer straight from it rather than re-deriving any of that by hand.

**`could-not-read` collapses into neither of the other two states.** Read as `pending`, it spins a
wait forever on a pull request nobody can read; read as `green`, it is a merge or a tag cut over a
diff never actually confirmed. Both collapses are this repository's own defect class, applied to
one call.

**If the wait outlasts your own turn, hand it back rather than polling.** Neither a sub-manager nor
a releaser has `ScheduleWakeup` or can receive channel events, and each already has a report shape
for exactly this: `TICK: paused` / `RELEASE: paused` with `WAIT-DISPATCH:` (what this run set in
motion) and `WAIT-OBSERVABLE:` (what clears it -- checks green, a leg failing). `--wait` polls
within one call and one `--timeout`; it does not survive past the turn that made it. **A
sub-manager's own `WAIT-OBSERVABLE` folds in one more fact, the fleet's occupancy** (#1190) --
`agents/sub-manager.md` carries that convention, since a releaser has no fleet to report on.
