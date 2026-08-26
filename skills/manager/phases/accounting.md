# Accounting: the cohort freeze and the intake ratio

**Read this when** a tick is closing, and at every release tag.

`skills/manager/SKILL.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## The backlog needs a terminating condition

A set that grows while you drain it has no end by construction. **At each release tag, label
everything then-open as a frozen cohort** — `cohort-1`, `cohort-2` — in the same minute as the tag.
Nothing joins a cohort, ever, so it can only shrink. **Freeze the moment you decide, not at the next
tag**: a boundary defined by a future event is not a boundary yet. The metric is whether each cohort
is smaller than the last.

Cohort labels are the maintainer's act, by hand; **the triager must never write one.** The cohort is
closure accounting, never a work order — priority decides what gets worked next.

**The freeze is a label, and a label write can silently delete it.** `gh api -X PATCH issues/N -f
'labels[]=…'` **replaces the whole label set** — so a later write setting priority or lane removes
the cohort label, exit 0, nothing errors, and the freeze verified minutes earlier is wrong. Add with
`POST issues/N/labels` or `gh issue edit N --add-label`; reach for `PATCH` only when replacing the
whole set is what you mean. And re-count the cohort **after the last label write of the tick**,
never before it — a count taken first measures a set that is still being edited.

**Ordering is not settling, and the filtered query can still read low after the last write.**
GitHub's label filter is an index and it lags the writes that feed it: 22 label writes, all 22
exiting zero, and `issues?state=open&labels=<cohort>` returned 19 immediately afterward and 22 about
a minute later — every one of the 22 issues carried the label the whole time. A cohort can only
shrink, so a low freeze recorded here is never corrected by any later count. **Take the freeze from
two routes that disagree by construction** — the filtered query plus either `search/issues`'s
`total_count` or a per-issue read of the set — and never record a number where they disagree. This
is `scripts/oss_state.py`'s `cohort_freeze`: given two or more route counts it reports `measured`
only when they agree, `unknown` when they do not (never the lower one, never the first one), and
`could-not-count` when fewer than two routes answered. Record the result as `detail.cohort_freeze`
on the state entry that documents the freeze, and if it reads `unknown`, re-count rather than
writing down either number.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
  --decision "froze <cohort> at N" --at "…" \
  --cohort <cohort> \
  --cohort-count filtered_query=22 --cohort-count per_issue_read=22
```

Passing `--cohort-count filtered_query=19 --cohort-count per_issue_read=22` instead — the routes
disagreeing, as the earlier example in this section did — records `unknown`, not a freeze at either
number. Re-counting rather than writing either one down is the correct response to that state.

### Intake: filings per merged pull request

The cohort measures the drain. This measures the fill, and without it the board's growth is a
feeling rather than a number. **Report it every tick, in the state entry.**

**The denominator, stated every time**, because a ratio whose denominator nobody wrote down means
nothing: pull requests **merged since the last tick**, against issues **the loop itself filed** in
that same window. Not everything that arrived on the tracker — a filing a maintainer made by hand,
or one a stranger opened, is intake the loop did not generate, and folding it in inflates the
numerator with work the loop has no lever on. Both halves of that rule travel with the number; a
window and an authorship rule left unstated make the ratio unreadable a week later.

**The review layer is a discovery machine and must not be throttled to make this number look
better.** The findings are the return on the review, not a side effect of it. Rationing filings
while discovery runs ahead of delivery moves the queue into somebody's head, which is the one place
it cannot be counted at all.

**Raising the bar on what counts as a finding is not throttling.** Looking less is throttling. A bar
is a definition: same reading, same defects seen, and the ones with no caller land in the pull
request instead of on the tracker.

**The bar, stated so it can be applied**: a finding gets its own issue when its cost was paid or is
payable -- a red build, a wrong answer that reached a consumer, a maintainer round trip, a receipt
somebody acted on -- or when it is the first reachable instance of a class: an input that arrives,
a wrong result it produces. A real finding below that line is still recorded, in the pull request
or as a comment on its class issue, because the tracker is the queue somebody will drain, not the
ledger of everything ever noticed. The two directions are not symmetric -- filing costs a sentence
and draining costs an agent plus a full CI matrix -- so an undefined bar drifts toward filing
everything, and the board grows while everybody is busy.

**One class, one issue.** The second instance of a filed class is a checklist line on the class
issue, not a sibling row: seven open issues for one defect class is seven briefs, seven worktrees
and seven reviews for work one sweep drains. Instances arriving faster than the class issue drains
is an argument for raising that issue's priority, never for widening the row count.

**The triager's proposed clusters are this rule arriving late, and this step is their consumer.**
The triage report names clusters and proposes only; acting on one is yours: pick or open the class
issue, move each sibling's substance into a checklist line on it, close the siblings with a pointer.
A proposed cluster nobody acts on is the board lying with extra steps -- the duplication was seen,
written down, and kept.

**The number is not a target and it is not inert.** No threshold may be claimed from one sample — the
paragraph below, unchanged. But a ratio climbing across a run of ticks is a finding about the loop:
ask whether the numerator is filings that cost somebody something or filings that cost nobody
anything. **Those two render identically in the count** and only one is work.

**No target ratio is claimed here, and none may be added from a single sample.** One project
measured roughly three filings per merged pull request; one day of another measured roughly 0.6.
Whether that gap is a healthier codebase, a shallower review, or the two ends counting a "filing"
differently is not knowable from either number — and a threshold read off one day of one repository
is exactly the hardcoded fact that never belongs in shared prose. Report the number and its window,
and let a run of them say something.

`scripts/oss_state.py` computes and records it, so it is recomputable rather than asserted:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> \
  --decision "…" --at "…" \
  --filings 6 --merged-prs 11 --window "since the last tick"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --trend
```

**The pair is stored, never the quotient.** 1/2 and 3/4 do not average to the ratio over six pull
requests, so a history of quotients cannot be re-added. `--trend` re-adds the numerators and the
denominators, which is only possible because both were kept.

Four states, and the third is the one that gets lost:

| State | What it means |
| --- | --- |
| `measured` | both counts taken, something merged. **A ratio of 0.0 lives here**, and it is a finding |
| `no-denominator` | nothing merged in the window. 6/0 is not 6 and it is not 0; the numerator still reports |
| `could-not-count` | a count was not taken — pass `unknown` with `--intake-why`. **Never renders as zero** |
| `partial` | `--trend` only: some ticks counted and some did not. A real sum, and not the range's total |

**Never count by aggregating pages.** `gh api … --paginate --jq 'length'` runs the filter once per
page and prints **one number per page**, never a total — measured `98` then `13` against a real
total of `111`. Whoever reads the first line gets a number smaller than the truth, correctly
formatted, at exit 0. Collect the pages into one array before the filter (`--slurp`), or count the
rows yourself. The same trap in its other spelling — a full page read as a complete list — is in the
triager's duties, and both are one shape: a partial read rendering as a total.

**Never derive a commit count or a commit identity by parsing rendered `git log` text.** The
maintainer's own shell rewrites every `git …` invocation through an rtk proxy, and that rewrite
corrupts exactly the values this loop most depends on: an empty range piped into a row count reads
as one row, not zero, because the proxy's own output for nothing at all is a single trailing
newline. Zero is the load-bearing value here — *nothing merged since the tag*, *reach did not move
this cycle*, *no fragments pending* — and every one of those reads as one instead of the absence it
is (#236). Through the same rtk proxy, separately, a `git log` naming a merge commit explicitly
drops it and slides the window down by one — measured against `rtk 0.35.0`, where `git log -1`
immediately after a merge named the pre-merge tip instead, and `git rev-parse HEAD` disagreed with
it (#310). This is the proxy's rewrite, not plain git's own traversal, which by default does list
merge commits; the two issues are the same mechanism reaching two different values through it.
Neither failure is visible locally: a count or identity derived this way is well-formed, exits `0`,
and is wrong. Type the count instead of rendering and re-parsing it — `git rev-list --count <range>`
for how many, `git rev-parse` for which commit — so git answers with one value and there is no row
for a proxy to corrupt in between. `scripts/release_delta.py` is the one place in this repo that
already computes a release delta this way; hold every new count to the same rule.

