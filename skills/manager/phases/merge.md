# Merge: the call, the gates, and what is still owed after green

**Read this when** a reviewed pull request is green, and once before the first tick of a new install.

`skills/manager/SKILL.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## Before the first tick: the merge call has to be able to run

`gh-pr-merge` is the only op in the table that writes, and by default **it writes nothing**. Without
a `|force` suffix it evaluates every gate, prints the preview, and exits non-zero with
`requires explicit confirmation`. So a loop reaches the merge step with all gates satisfied, having
spent the whole review, and then cannot merge. Arrange this at setup, not at the merge.

Three opt-outs exist, and they are not equivalent:

| Opt-out | Reach |
| --- | --- |
| `\|force` on the call | that one call. Per-merge, explicit, leaves a record in the command |
| `SUPERTOOL_NO_PUBLISH_CONFIRM=1` | every op in the environment, for as long as it is exported |
| `"no_publish_confirm": true` in `.supertool.json` | every confirm-gated op in that project, permanently |

**Prefer `|force`.** The other two are the same switch with a wider blast radius: the confirmation
gate is shared, so turning it off for merging turns it off for the publishing ops in the same
project too. That is three ops today, and the count is a fact about the installed presets rather
than a promise — a project that later enables a publishing preset widens what it already disabled,
silently.

A second mechanism sits in front of all three and is not the same thing: the harness's own
permission handling can deny the call before supertool sees it, and an allowlist entry does not
necessarily clear it. Two consequences worth knowing before the first tick, because both cost a
round trip each to rediscover:

- `gh-pr-merge:N:squash` and `gh-pr-merge:N:squash|force` are **different command strings**, so an
  approval of the first does not carry to the second.
- The obvious fallback is worse than the thing it replaces. Raw `gh pr merge` is refused by
  supertool's own guard, and rightly: the op is what does the leg-level arithmetic and reads
  `state` / `mergedAt` / `mergeCommit` back. **Do not route around a denied merge.** Say the call
  was denied, name it exactly, and let the maintainer run or permit it.

**Which spelling to type, stated rather than left to be inferred.** Use the bare
`supertool 'gh-pr-merge:N:squash|force'` from the clone root — an allowlist rule anchored on the
`supertool ` prefix matches it. **Do not use `python3 supertool.py 'gh-pr-merge:…'` for the merge**,
even in a repo whose own rules require that exact spelling for file operations: that requirement
exists so a worktree's edits run against its own branch's core rather than whatever the global
binary resolves to, and the merge op is a forge call that does not care which tree's core runs it,
so the constraint does not carry over to it. One merge per Bash call — a loop or a compound command
no longer *starts* with the allowed prefix, so it is denied even when each call inside it would be
allowed on its own. And **read `Blocked by classifier` as a claim about the command string, not
about the action**: on a call the allowlist appears to cover, it means the spelling in front of the
op differs from the one the rule was written against, not that merging itself was refused. Three
sessions chased the wrong cause before this was written down (#445).

## Merge gates

Merge only when all hold: **CI fully green at leg level, the review passed, and the change is a
bugfix / docs / test / chore.** Then verify the merge landed — read `state` / `mergedAt` /
`mergeCommit` back off the remote, because a zero exit is not a merge.

**Never auto-merge:** feature scope, public API or behaviour renames, external-contributor PRs,
anything irreversible. **And do not invent gates** — parking a real bug as "the owner's call" when it
is not on this list is just a way of not fixing things.

- **"Not failing" is not "green" — count the checks.** The state counts must sum to the number of
  legs, and any leg not `SUCCESS` gets named before merging.
- **Green and mergeable means merge -- no pre-merge rebase, `git merge origin/main`, force-push, or
  fresh matrix run, unless something other than staleness demands one (#1085).** This holds where
  the managed repo's CI has this shape, and it is a fact to check per repo rather than assume: a
  `pull_request`-triggered workflow paired with its own `push: branches: [<default_branch>]` run on
  the same file (this repo's own `.github/workflows/tests.yml` is one instance, not a name to expect
  elsewhere). A `pull_request` run checks out a merge-ref computed when the run started, so where the
  base has not moved since, a green PR has already tested the post-merge content and a rebase would
  re-test byte-identical content -- a full matrix for nothing. Where the base *has* moved, the
  squash's own `push` run on the default branch tests the real combined content regardless of
  whether anyone rebased first, so a pre-merge rebase does not add coverage there either -- it
  duplicates a run already being paid for. That `push` run is the backstop, which is why step 3
  below (reading `gh-branch` after the squash) matters more, not less. **Where a managed repo's CI
  lacks that `push`-on-default-branch half, there is no backstop and this policy does not carry over
  without re-deriving the argument for that repo's own trigger shape.**

  The residual cost, stated rather than smoothed over: a semantic conflict -- one branch adds a
  test, another renames what it calls -- is green *and* mergeable and can still land red on the
  default branch, and the remedy then is a revert. That cost is accepted deliberately; it is smaller
  than a rebase on every merge, nearly all of which would be re-testing content that did not change.
  **This policy holds only paired with watching the tick's last merge to conclusion before the tick
  closes** (`skills/manager/phases/tick-order.md`'s *What ends a tick*, which refuses to close while
  radar's board -- carrying the default branch as a member row, per that file's own step 4 --
  reports anything unwatched) -- a green merge followed by the tick dying before that run
  concludes removes the pre-merge check without keeping the post-merge one. A rebase or
  `git merge origin/main` stays
  correct where the PR is *not* mergeable, or its failure is understood to come from a stale base --
  #389's rule just below still applies there, and a merge is preferred over a rebase because it does
  not rewrite
  history.
- **A rerun does not re-resolve a moved base, so it replays the same red.** `gh run rerun <id>
  --failed` re-runs the check suite against the merge ref it already had; it does not re-resolve
  that ref against a `main` that has since moved. A fix landed on the default branch after the run
  started is therefore invisible to the rerun, and the second failure looks exactly like a fix that
  did not work rather than a fix that was never tested. **The tell is the run id**: a rerun that
  reports the same run id as before has told you it re-ran the old resolution, not a new one — read
  it before trusting the second red. When the base has moved under a red PR, use `gh api -X PUT
  repos/OWNER/REPO/pulls/N/update-branch` instead, which merges the new base into the head
  server-side, needs no local worktree and no force-push (#389).
- **Cleanup is gated on the verified merge result — use the op's own `|cleanup` token rather than a
  second, separate call.** Chaining merge and cleanup by hand once deleted a branch after a failed
  merge and auto-closed the PR; recovery was possible only because the forge keeps the PR ref. That
  is the exact guarantee `|cleanup` runs inside the op instead: `gh-pr-merge:N:squash|force|cleanup`
  is the documented default, and its three deletions run only **after** the op's own `MERGED`
  read-back, never before.
- **Release the merged issue's own lane record in the same breath.** A live record blocks a
  follow-up for its full 240-minute TTL regardless of whether its own pull request merged --
  three recorded instances cost 20-90 minutes of a follow-up wrongly `BLOCKED` on files a merge the
  loop itself performed and read back had already freed (#734). Once step 1 above verifies
  `state`/`mergedAt`/`mergeCommit`, run `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue>
  --release --repo <clone>` -- `released` / `not-found` (nothing to do, not a failure) /
  `could-not-release`. Skipping it is slower, not wrong: `held_from_live_lanes` also prunes a
  record once its branch is confirmed gone from the shared clone's local `refs/heads`, which
  `|cleanup`'s branch deletion above causes anyway -- the explicit release just does not wait for
  a later lane to ask.
- **Verify the linked issue actually closed.** Write one `Closes #N` per issue — the *keyword*
  repeated, not just the `#`. `Closes #A B` silently references only A, and `Closes #A #B` links
  both and closes only A, so "each number has its own `#`" is not the rule and satisfying it is not
  enough. A check that greps a *fragment* of the line cannot audit either case. Read the whole line.
- **`Part of` is a decision, not a defect.** Do not close such an issue because the work shipped.
- **Delete merged worktrees**, but read ownership before you reap, and know that `|cleanup` only
  does this half when the board holds exactly one idle tree. A fleet-running loop normally holds
  several, so on any of them `|cleanup` reports `skipped: reason` for the worktree while still
  deleting the branch; that skip is correct, not a failure, and it is not free to notice — a skip and
  a success both end with no error. **Reap the rest yourself**, the same way whether or not
  `|cleanup` handled this one: `git-worktrees` boards every tree with an occupancy verdict and a
  merge state; `git-worktrees:PATH` gates one, and supertool's exit is 0 only for `idle`. Both
  columns have three states and the third is never a yes: `cannot tell` is not `idle`, and `merge
  unknown` is not `merged`. The merge column consults a merged PR as well as ancestry, because
  **ancestry cannot see a squash merge** — the same blind spot the branch bullet below names, on the
  same refs. Then `git worktree remove`, not `prune` — `prune` will not touch a directory that still
  exists. A shell that has to branch on the verdict must run the preset `worktrees.py` itself:
  supertool collapses the exit to 0/1, so `cannot tell` (2) arrives indistinguishable from `occupied`
  (1), and treating both as "not idle" is the only safe read through supertool. That is the one read
  this document sanctions outside supertool, and only for that reason — the op's own `help` names the
  script, so derive its path from the installed tool rather than from a path written down anywhere.
- **A `cannot tell` worktree is not yours to force through without re-checking HEAD, and the force is
  recorded when you do it anyway (#1007).** `|cleanup` declined that worktree for a reason: an agent
  may still be writing there, and the tick's own last observation of that tree is already stale by
  the time cleanup runs. Twice this loop force-removed one anyway — `git worktree remove --force` plus
  `git branch -D`, the manual fallback `commands/doctor.md`'s `worktree-reap permission` check names —
  and both times destroyed a commit the lane had made in the window between the tick's last look and
  the force-remove: a self-review finding it had just fixed, local only, gone with the tree. Both were
  recovered by luck, a surviving reflog entry, not by design. **Before that force-remove runs, read the
  tree's HEAD one more time with `git -C <worktree> rev-parse HEAD` — unconditionally, never as a
  fallback (#1056; see below for why)** — and compare it to the HEAD you observed when you decided
  to force this one — the merge's own head commit, or your last `git-worktrees` read of that path.
  If it moved, something committed there after your last look and the force-remove is refused this
  tick: leave the worktree standing, the same as any other `cannot tell`, and let a later tick's
  cooldown re-evaluate it rather than destroying work you have not re-observed. This closes the
  actual race window; a tick cannot get it right by being careful, because the gap is between its
  own two observations, not a lapse in attention.

  **`git-worktrees:PATH` cannot perform this comparison at all, so it is never the fallback and
  never the primary either (#1056).** The op reports branch, path, occupancy, `[merged, clean]`, a
  remote-tracking line and a `git status --porcelain` line — no commit SHA anywhere. #1017 wrote the
  raw `rev-parse` as a fallback "taken only if the op cannot answer" on the reasoning that
  `git-worktrees` would usually suffice; but the op *always* answers with a merged/occupancy
  verdict, just never with the SHA this check needs, so that fallback could never fire — the guard
  was nominally on and effectively off. Read `git-worktrees:PATH` for the merged/occupancy state as
  before; run `git -C <worktree> rev-parse HEAD` for the SHA comparison every time, full stop.

  #982 narrowed `.claude/settings.json`'s blanket `Bash(git *)` grant to an enumerated allow-list
  matched as a literal command-string prefix, and `git -C <worktree> rev-parse HEAD` does not
  start with the string `git rev-parse` — `-C <path>` sits ahead of the subcommand. Whether Claude
  Code's own Bash permission matcher normalizes a git global option before that prefix test is
  reasoned here, not observed (nothing in this loop can drive its permission UI to confirm it
  directly); expect this call may need an interactive grant. Widening the allow-list is not the
  fix — `Bash(git -C:*)` would match `git -C <any path> <anything at all>`, reopening every
  subcommand #982 narrowed the grant to exclude — so grant this one call, not the pattern.

  **When the HEAD check passes and you do force it, record the override** —
  `oss_state.py`'s `--cleanup-override WORKTREE=REASON` (repeatable), same call as the tick's other
  `--decision` flags, reason required. A forced cleanup over a `cannot tell` is not the same event as a
  clean one, and until this the only trace of the override was a state file that afterwards read
  identically to a tick that never triggered `cannot tell` at all — the guard's refusal was a line in
  an op's output and the force-remove that followed was two ordinary git commands, so nothing outlived
  either. Recording it does not make the removal safer; the HEAD check above is what does that. It
  makes the override auditable rather than invisible, which is the second, cheaper half of the fix.
- **The branch deletion is `|cleanup`'s, not a second call.** Inside the token it is
  `gh api -X DELETE repos/OWNER/REPO/git/refs/heads/<b>`, never `git push --delete`, and only once the
  head branch is established to be in this repository and the remote ref reads back at the PR's own
  head commit. Reach for the raw command by hand only in the three cases the op deliberately refuses
  to touch: a cross-repository head, an unestablished branch, or the default branch — where it prints
  no command at all. And note `git branch -r --merged` **cannot see squash merges** — it reported 4 on
  a repo holding 96 merged branches, which is why the op reads the remote ref back rather than
  trusting ancestry.

### The merge is not done when the PR is green

**A green PR is a statement about its merge-base, not about the default branch after the squash.**
Three steps, not one:

1. merge → read `state` / `mergedAt` / `mergeCommit`
2. clean up via `|cleanup` on the same call, gated on that op's own `MERGED` read-back
3. **check the default branch's own run** — `gh-branch`, which is conjunctive over every workflow on
   the head SHA and states GREEN / NOT GREEN / NO RUN / UNKNOWN apart. Not `gh run list --limit 1`,
   which returns whichever *workflow* started last and reports its conclusion as the commit's.

   Read its third state here too, and not only at the release gate. A `pull_request`-triggered
   workflow **could not have run on the squash commit**, so it is neither a pass nor a failure; the
   op prints that under the table, and it is the most common thing on this line to be
   **misread as a red default branch** — a merge reported as having broken `main` when nothing ran.

Step 3 costs one call. Skipping it means the default branch is red for hours while the board reads
clean, and the person who notices is the one who asked you to watch it.

