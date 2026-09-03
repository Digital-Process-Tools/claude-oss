# Release currency: the readings behind `What is not proven yet`

`CLAUDE.md`'s `What is not proven yet` section holds the verdict, the marker and the two
claims a test pins. This file holds the readings behind it: the delta counts, the audit
rounds, the reach probe's per-repository results, the owned-file drift table and the install
readings. **Re-derive at each release rather than editing it.**

Carried out of `CLAUDE.md` unedited at `v0.20.0` (measured `94a6c7d`). Everything from
`### The reach probe` onward was already stale when it moved here — those are `v0.17.0`'s
readings, measured at `ad38b93`, and `#815` tracks re-deriving them.

---

## What is not proven yet (carried, v0.20.0)
**Measured at `94a6c7d`, the commit `v0.20.0` was cut from — but only in part, and the part is
named.** The delta counts, the two audit rounds and the lane findings below were re-derived against
`v0.19.0..94a6c7d` in the session that cut this release. **Everything from `### The reach probe`
onward was not** — the field probe, the owned-files table, the two installs and the `doctor` run are
still `v0.17.0`'s readings, carried unchanged through **three** releases now, and each of those
headings says so where it stands. `#815` is where re-deriving them is tracked, and it is now three
releases old rather than two: this paragraph disclosing the gap accurately is not the same thing as
closing it, and the second release running to disclose the identical gap is evidence the disclosure
is doing the work the fix was supposed to. **Re-derive this at each release rather than editing it**
remains the rule; this paragraph is a disclosure of following half of it. The version it replaces was
measured at `e241c5c`; before that at `160e77b`, `ad38b93`, `27d2f15`, `d2a2968`, `48bb420`,
`990d0da`, `bce0362`, `53e2d0c`, `805debb`, `c570977`, `d4c12c1`, `7690fd0`, `01212b0` and `e8e75b2`.

**The two delta counts agree exactly, for the second round running.** 25 commits against 25 merged
pull requests, and `gh-prs:merged-since=v0.19.0` reports the count `[EXACT]` with its own cross-check
`RAN and AGREED` on 25 PR references in the range. The fix that produced the first agreement — edit
this section's currency marker *inside* the release commit rather than as a direct push to `main`
before it — held a second time without anyone re-deciding it, which is the only evidence that a
one-off fix was a fix and not a quiet round.

**Every trailing `(#N)` in the range was checked against the issues API rather than read as a pull
request number**: 25 of 25 returned `pull_request != null`, **zero** were issues. That check exists
because a round three releases ago found one that was — `#679`, cited in a commit message — and
reconciled it by hand. Clean again, and recorded as such rather than passed over, because a check
that only speaks when it finds something is indistinguishable from a check nobody ran.

`git rev-list --count --merges v0.19.0..HEAD` returns `0`, unchanged: this repository squash-merges,
so a merged pull request is an ordinary single commit and no merge commit exists to intersect
against.

### This release was gated twice, and both rounds are on the record

Both rounds ran with distinct tokens: **round one under `rel-0200-0116419f52`**, **round two under
`rel-0200-r2-a1dc626b57`**. Both completions echoed their own token, so both were attributed; neither
arm for an unattributed or duplicated completion was reached.

- **Round one: 4 findings, `0 of 4 classes read but not exercised`.** Round-one findings stop the
  tag, so they did. Three were fixed and merged before round two was dispatched — `#886` (`#891`),
  `#887` (`#890`), `#889` (`#893`). **The fourth, `#888`, was refuted by measurement and closed
  invalid**, and that is the round's most useful outcome: a gate whose findings are all treated as
  true has stopped being a measurement and become a queue. The refutation was itself verified rather
  than believed — round two ran `git diff 378dab0..94a6c7d` over the two files `#893`'s commit
  message claimed to have reverted and found the diff empty, so the tree matches the claim.
- **Round two: 4 findings, `0 of 4 classes read but not exercised`, none in a blocking row.** Filed
  as `#895`-`#898`; the tag moved over them, which is what round two is for.

**`0 of 4` twice in one release, and six rounds running.** Still held up by the brief asking for
controls rather than reads, and still by nothing in the checklist — so it survives exactly as long as
somebody keeps asking for it, on the same single thread it has always rested on. A streak is not a
mechanism, and the length of this one is an argument for writing the mechanism rather than evidence
that none is needed.

**Round two declined two blocking rows on measurement and refused the table outright on a third, and
that is the better record of this gate working than either count.** Its `B-1` — `#869` made
`state_file` derive from the tracked `repo` on every config load, and `REPO_RE` permits a backslash,
so on Windows `ntpath.normpath` resolves the derived path to `C:\x-watch.json`, outside the clone —
has a complete, measured mechanism for `containment (write)`, which blocks unconditionally. The
auditor declined it, because it could not establish a route by which `repo` takes a value the
maintainer did not choose. It then declined `splices` (the fix that row invites, quoting, does not
remove the defect) and `misreports` (the module already warns the value is a guess), and reported the
finding **`unranked`** rather than shrinking it into the nearest row that would take it — the
escape hatch `## Who decides` describes, used for the first time on a release. `B-2` declined
`containment (read)` the same way, on a control that fired: six hostile lane patterns refused, three
benign ones accepted, and the one residual (`~`, refused in neither form) shown to be inert by
`grep expanduser scripts/` returning 28 hits across six modules and none in `lane_setup.py`.

**The audit read its own definition against the copy running it, and complied with the stricter
one.** `checklist_skew.py` read `matches` — installed `0.19.0`, this tree `0.19.0` — with **six of
ten** definition files `differs` underneath it, including **both** audit definitions, which is why the
state name alone is never the answer and why the byte comparison runs on `matches` as well as on
`differs`. The auditor identified what the skew actually was: the installed `agents/release-auditor.md`
lacks `## Test behaviour is reasoned, not run`, added by `d119d59` (`#877`) **inside this range**. It
complied with this tree's stricter copy — ran no suite, delegated no test verdict, and labelled every
coverage claim `reasoned` — rather than with the laxer copy that was actually loaded. That is the
`#538` machinery paying out: the skew was computed rather than recalled, so the agent could read it.

### What the two-layer arrangement produced this release

**8 findings from two audit rounds, one of them refuted.** The lane-review layer produced nothing
comparable to the previous two releases' catch of a defect inside the audit's own fix, and that is
recorded as an absence rather than passed over: three lanes fixed three round-one findings and each
one's reviewer came back with nothing to add. Whether that means the fixes were smaller, or the
reviews were, is not established here — the previous release's entry could name the reviewer's own
measurement, and this one cannot.

What did happen at the lane layer is a defect a lane caused and then reported on itself. The `#764`
lane, writing its note file with an **unquoted heredoc**, executed backtick-quoted markdown phrases
as shell commands and created an empty `.git` at the shared `worktree_root` — a second git repository
sitting one level above every lane worktree. It was verified before removal (no commits, no refs,
`git log` reporting "does not have any commits yet"), and the lane's own two cleanup attempts were
refused by the permission classifier, which is correct agent behaviour: the step belonged to the
maintainer. The reason it is here rather than in a changelog entry is that the lane **said so
unprompted**; a lane that quietly cleaned up after itself and a lane that never noticed render
identically in a handback.

### The reach probe: eleven repositories, fifty-five probes, and the field did not move at all

> **NOT RE-DERIVED for `v0.20.0`.** Every number in this subsection, and in the three that follow it,
> was measured at `ad38b93` for `v0.17.0` and has now been carried through three tags without being
> re-run. It is a reading, and it is a reading with a date on it — not a statement about the field
> today. `#815` is where re-deriving it is tracked. Read nothing here as current.

`gh repo list Digital-Process-Tools --limit 100` returns **eleven** repositories **in that one
GitHub organisation**, unchanged, and each of five artifacts was probed in every one — **55 probes**,
no filtered subset, re-run at this commit. **The count is scoped to the org the command names, not
to "the field"**: a repository under a different account renders identically to one that does not
exist, and this probe cannot tell the two apart (#711).

- **`.oss.json` on four** — this one, `claude-supertool`, `claude-jit-context`, `claude-remember`.
  Unchanged.
- **Every field cell is byte-identical to the previous round's reading.** Sixteen cells, none moved.
- **The remaining seven carry none of the five, unchanged** — `claude-marketplace`, `.github` and
  the four `mcp-*-warm` servers.

What has **still** not been observed, across fifteen rounds **within the one organisation this probe
can see**: any repository scaffolded **by a maintainer who is not the author of this plugin**. That
qualifier is load-bearing and it is `#711`'s whole subject — `#705` was filed from `jbkkz/requivo`,
a repository under a personal account this probe cannot enumerate — so "not observed" here means
"not observed by a probe that could not have seen it", never "does not exist" (#711). The owned-files
table below inherits the identical gap.

### Owned files in the field, and the strongest case yet against gating on our own render

Rendering each at `ad38b93` with `scaffold.render_owned(name, config, ".")` — the config **unpacked
from `oss_config.load('.oss.json')`, which returns `(config, warnings)`; passing the tuple renders
the two vendored copies fine and raises `AttributeError` on the two templated ones**, which is worth
writing down because it looks like a defect in the renderer and is not.

| owned file | would write today | `claude-jit-context` | `claude-5h-window-spread` | `claude-remember` | `claude-supertool` |
| --- | --- | --- | --- | --- | --- |
| `.oss/assemble_changelog.py` | 136,323 B (`1cfa2d72`) | 102,079 `b16cc044` — **drifted** | 55,261 `dc1f11f8` — **drifted** | 124,329 `28ef77c7` — **drifted** | **absent** |
| `.oss/README.md` | 2,808 B (`67472247`) | 1,753 `c380cfe0` — **drifted** | 1,325 `68de5d32` — **drifted** | 1,753 `c380cfe0` — **drifted** | **absent** |
| `.github/workflows/oss-changelog.yml` | 12,639 B (`c820d2dc`) | 9,954 `dae31dc9` — **drifted** | 2,159 `032184b4` — **drifted** | 12,648 `259ddf76` — **drifted** | **absent** |
| `.oss/statusline.py` | 88,159 B (`bd072a18`) | 52,373 `d60ecb75` — **drifted** | **absent** | 65,637 `ef3ed46b` — **drifted** | 65,637 `ef3ed46b` — **drifted** |

- **Our render moved in two rows of four** — `.oss/assemble_changelog.py` 127,721 → 136,323 B
  (+8,602, the `compatibility_finding()` transcription from `#737`) and `.oss/README.md` 1,753 →
  2,808 B (+1,055). The other two render byte-for-byte what they rendered last round.
- **Two field cells flipped from `identical` to `drifted` without the field moving one byte.**
  `claude-jit-context` and `claude-remember` both carry `.oss/README.md` at `c380cfe0`, which *was*
  what we would have written and now is not. Nothing changed in those repositories.
- **So the case against gating CI on this column is stronger than last round's, and last round's was
  already the strongest yet.** Then, one render moved and sixteen field cells held still. This round,
  two renders moved, sixteen cells held still again, **and two of them changed verdict as a pure
  artifact of our own edit**. A gate on this column would have fired twice on us and stayed silent
  about every cell that is actually stale.

### The two installs, and the launcher

```
installed: 0.15.0, no git HEAD here, content ad08d4efebc2 over 58 file(s)
clone    : 0.17.0, git HEAD ad38b93, content read from this checkout over 65 file(s)
```

The marketplace cache holds `0.16.0` as well as `0.15.0` — the directory is there — but this whole
session's commands resolved from `0.15.0`, because the session began before `0.16.0` was picked up.
**That had one measured consequence and it is worth keeping**: the installed copy's
`skills/manager/phases/dispatch.md` still carried the pre-`#673` batch-error string, and the brief
written from it would have shipped a string this repository has already measured as wrong. It was
caught by reading the clone's copy before pasting. `#477`'s identity comparison is what surfaced the
skew in the first place, on the tick's own first call.

**`oss-workspace` reads `PINNED ELSEWHERE`** — `PATH` resolves it to `…/oss/0.15.0/bin/oss-workspace`
while the tree is `0.17.0`. The previous round reported *no skew* on this machine and predicted
exactly this: the symlink is pinned to whatever version was current when it was made. `#289` is back,
one round after a twelve-round streak was broken by a fresh install rather than by a fix.

`python3 scripts/doctor.py --root .`: **6 warnings, 0 failures** — the plugin-copy scope not
established on a bare invocation, the launcher pin above, the two `remember` store-location unknowns,
the jit layer `unknown`, and `.oss/statusline.py` absent from this clone.

### Still the most important sentence here

Most of what this plugin claims about a *scaffolded* repository rests on tests and scratch runs
rather than on a repo somebody maintains through it. That stood at `v0.3.0` and at every release
since, and it is re-earned rather than inherited here. **The surface is thin because it has barely
been run, not because it is sound.**

What changed since the previous round: a round-one finding was **refuted by measurement and closed
invalid** rather than fixed, which is the first time this gate has disproved its own output; round
two reported a finding **`unranked`**, declining two blocking rows on measurement rather than
stretching it into the nearest row that would take it; the auditor read the skew between its own
installed definition and this tree's, identified the missing section by the commit that added it, and
complied with the stricter copy; the delta counts agreed exactly for a second round, on a fix nobody
re-decided; and the lane-review layer produced no finding inside an audit fix, recorded here as an
absence rather than passed over.

`tests/test_claude_md_currency.py` still cannot check that a claim above is true, and still does not
try — and at the moment this section was rewritten it reported that in as many words, skipping with
*no unfolded changelog fragments, so no release is being prepared … UNTESTED here: whether the
section is current*. The mechanism to add more of is a **second measurement** contradicting the prose
beside it. This round produced four, and every one of them contradicted something a reader would
otherwise have believed: every trailing `(#N)` checked against the issues API rather than read as a
pull request number; `#888`'s revert claim verified with an empty `git diff` over the two files it
named, rather than read out of its own commit message; `checklist_skew` reading `matches` while six
of ten definition files differ, so the state name was measured against the files rather than quoted;
and the auditor's own definition compared against the copy loaded to run it, which is the only reason
`#877`'s new section governed this audit at all.

One claim stays deliberately unguarded, and the decision is re-taken rather than inherited: the
"would write today" column is computed entirely from this tree and a three-line test could hold it.
**Declined again**, and this round the reason is one step weaker and stated as such: the field table
above was not re-derived, so it offers no fresh evidence either way, and the decision rests on the
previous round's reading plus the argument below rather than on anything measured here. The reason
not to add it is unchanged: it would redden unrelated pull requests until somebody edited
`CLAUDE.md` to make CI green, training the reflex of editing the section instead of re-deriving it.

Treat this as tested, not proven.
