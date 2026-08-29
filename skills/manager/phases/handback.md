# Handback: a lane reported, and the pull request

**Read this when** a dispatched lane has replied with a report path -- before you read the report or push anything.

`skills/manager/SKILL.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## What comes back is a file, not a document

An agent replies with **a path and at most two lines**. The work itself is a JSON report it wrote
outside every worktree, and a forge-ready pull request payload beside it. You read the fields you
need, when you need them — a report that arrives whole is paid for again on every later turn of the
session, and most rounds need four of its fields.

`schemas/agent-report.schema.json` carries the fields, their enumerations and a worked example;
`scripts/report_schema.py` says which of them are enforced and which are convention that nobody
checks. **Point a brief at those; never copy the field list into one.** A fact living in two documents
diverges, and a brief is the copy nobody proofreads.

The `developer` definition already asks for both files, so a brief adds nothing about the format —
only the unconditional publishing clause above, which is unchanged. The agent commits. You push.

**Release what a lane did not finish.** The developer never writes to the forge, so the assignment
placed at dispatch is still sitting on the issue when this report comes back, and the report already
carries what tells the two cases apart — `files` empty, no commit made. When a lane ends without a
commit, unassign the issue it was claimed under before the spawn:
`gh issue edit <N> --remove-assignee @me`. Skipping this turns a collision problem into a permanent
lock: an issue assigned to a lane that
no longer exists is indistinguishable from one still being worked, which is this repository's own
defect class landing on the mechanism meant to prevent it. A lane that *did* return a commit needs no
release here — merging closes the issue and drops it off the open board this selection step reads,
which is what stops it being picked again, not the assignee field being cleared.

**A pull request that closes without merging releases its issue too (#465).** It is further along
than a lane that never committed — a commit exists, a pull request was opened — and ends in the same
state: an assignee, no lane behind it, and a selection step that now skips it forever because it
reads as somebody's. `gh-pr:N:status` already reads `state` and `merged_at`; when `state` is `CLOSED`
and `merged_at` reads as unset (the op prints `-`, never the word `null`), unassign the linked issue
the same way — `gh issue edit <N> --remove-assignee @me`. Three states, exactly as parallel as the
claim step's own: **released** — `state` is `CLOSED` and `merged_at` is unset; **still-assigned** —
`state` is `MERGED` or still `OPEN`; and **could not read the pull request state** — the call failed
or was not made, and this **must never render as released**, for the same reason a claim state that
could not be read must never render as free. The reachable event is the one this loop's own decision
produces: when this loop is the one that closes a pull request without merging — a superseded
approach, a scope change, a duplicate — run this check as part of that same step, not a separate
sweep. **A pull request closed by someone else, outside a tick this loop ran, is not observed by this
step**; that gap is named rather than silently solved, because nothing in the loop currently re-reads
a closed pull request on its own once it drops off the board a merge would have closed it from.

## Opening the pull request

Pushing and opening is yours, and it is one read plus one call:

1. **Push the agent's branch.**
2. **Read the body before you publish it.** Not optional, and it is what makes this a saving rather
   than a trick: you stop *writing* a document you still have to *read*. A body published unread is
   your name on text you have not seen. If it is wrong, argue it in the pull request or send it back;
   do not quietly rewrite it, because the person who did the work writes the record — twice now, a
   body has carried a correction to the brief that a re-narration had flattened out.
3. **Hand the payload path to `gh-pr-create:@FILE`.** Not `gh pr create`, and not a body of your own
   assembled from the report. The op parses the body's closing references with the same reader
   `gh-pr` uses, so a missing or malformed `Closes #N` is **surfaced** at creation instead of after
   the squash — when the issue quietly stays open and the board reads clean. **Surfaced, not caught:
   the pull request is opened and the op exits 0**, printing *No closing keyword in the body, so
   merging this will close nothing.* Reading that line is yours. See below.
4. **If the fragment gets renamed to this pull request's own number, the rename is not
   metadata-only, and it is not a step to remember either.** A lane commits a fragment keyed to the
   issue it was briefed on; a maintainer who then keys it to the pull request number instead runs
   `git mv changelog.d/N.section.md changelog.d/M.section.md` — and the fold consumes the
   *filename*, so the entry body still has to name the number the filename now carries, or the
   `fragment` leg refuses a fragment that passed a moment earlier (measured on PR #338: the body
   named `#338`, the file became `425.…`, and CI read the mismatch as a fragment naming nothing).
   The rename and the rewrite are one coupled fact, not two — a fragment keyed to the pull request's
   own number does not exist until the pull request is open, so nothing about it is correct until
   both halves have moved together.
   `${CLAUDE_PLUGIN_ROOT}/scripts/rename_changelog_fragment.py <old path> <new number>` performs both
   in one call: it moves the file with `git mv`, rewrites the fragment's own
   self-reference to the new number, and **refuses** rather than leaving behind a fragment
   `assemble_changelog.py --check` would still reject — including when the old body never named
   itself at all, where there is nothing to move and the fix needs a human's `(#N)`. Renaming to the
   number a fragment already carries is a no-op, not a rewrite. Amend and re-push after it runs.

**Four fields arrive filled in, and they are not yours to retype.** The payload requires `title`,
`body`, `head` and `base`; `schemas/agent-report.schema.json` also defines `draft` and `labels` as
optional, so read it rather than this sentence for the current set. Measured: ten pull requests in
one day where `head` and `base` were both overwritten by hand and all twenty values were already
right. The op requires `base` because it never *defaults* one — not because you must type it.

**How far the validator actually gets, because "already checked" is not the same claim for both**,
and the difference decides what is worth your attention:

- **`head` is checked, but against the agent's own report**, not against git: `report_schema.py`
  compares `payload.head` to the report's `branch`. Two fields written by the same agent in the same
  run agreeing is internal consistency, not ground truth. Note also that the report's *top-level*
  `head` is a commit SHA and the payload's `head` is a branch name — same word, two objects.
- **`base` is checked for presence and nothing else.** Nothing compares it to `default_branch`. A
  wrong-but-non-empty `base` passes, and it is the field whose corruption merges into the wrong
  branch.
- **Nothing in this loop runs the validator.** The agent runs it and reports the result, so
  "validated" is a claim you are reading, not a check you observed.

So the useful move is not retyping the two fields — it is **spending one call to see the check
rather than the claim**, which is the thing your own hands cannot do better:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py" <the report path the agent replied with>
```

**This call has three answers, and the third is not a finding about the report.** The path above is
`${CLAUDE_PLUGIN_ROOT}`, which resolves into the **installed** plugin — a copy that can implement an
older contract than the clone the work was done in, and routinely does, because a merged fix is
invisible to the running loop until a tag is cut and installed. So:

- **`ok`**, with the contract version it validated against — the routine answer. Since #416 that
  version is sometimes **older than the copy's own**, and the line says so: the schema declares per
  version whether it widened the one below it, and a chain of declared widenings back to the
  report's number means a document valid there is valid here. `ok … read under version N` is a
  weaker claim than a plain `ok` and is worth reading as one — it says the report satisfies a
  contract this copy holds, not that it was written against this copy's contract.
- **A finding** — the report is wrong, and the message says how.
- **`UNVALIDATABLE`, exit 2** — the report names a contract *this copy does not hold*. That is a
  statement about the **validator**, not about the report, and it is the answer to relay rather than
  a defect to chase. A copy predating that verdict spells the same fact as
  `INVALID … schema_version: expected N, got M`, which reads as a finding and is not one. An **older**
  number reaching this answer now means something more specific than a version skew: some step
  between the two contracts was declared breaking, or nobody declared it at all.

When the two disagree, **the clone is the authority** — it is the tree the work was done in and the
tree the release will ship. Nothing distinguishes the two copies by name; both manifests read `oss`,
so the disagreement is only visible if you know to look for it.

**The report path, not the payload path** — and the reason is the same one that makes the call worth
making. The `head` comparison above only exists where *both* documents are in hand: the validator
opens the payload named at `pr_body.path` and compares its `head` to the report's `branch`. Handed
the payload alone it has no branch to compare against, so the one check this call is for could not
run. Validating the report reads both files, which is why one path covers both.

Reach for the payload path anyway and the validator says so by name and names the call to run — it
does not enumerate the report keys a payload is missing, because fourteen of those on a completely
correct payload reads as a finding about the file rather than a mistake by the caller, and the move
it invites is hand-writing `head`.

You have just pushed the branch, so you are the only party in the loop holding ground truth about
what `head` should be. **Compare it; rewriting them by hand is the one move that makes things
worse** — a hand-written value is the only one nothing downstream verifies at all, and a mistyped
`head` opens a pull request from somewhere other than the work with the validator's guarantee
already spent.

`title` is the agent's. It is the sentence most people read, and after a squash it is the only part
of the pull request that survives into the log, so it belongs to whoever did the work.

**Reading `pr_body` has three answers, not two.**

- **`written`** — the routine path above. Read the body, then hand over the path.
- **`not-written`** — the field says why. The body is yours, written from a report rather than from
  the work. That is the expensive path this exists to avoid, not the routine one.
- **The path is named and the file is absent, unparseable or unreadable.** That is neither of the
  above and it is **never "no pull request to open"**. A payload that **could not be read** is a
  missing artefact from a run that believed it wrote one: say which of the three you are in, and
  either recover the file or write the body yourself *and record that you did*. Silently opening
  nothing, or silently opening a body of your own as though none had been offered, is this loop's
  own defect class landing on its own output.

### Your verification is a different voice, so append it

If you verified something the agent could not, **append a `## Verified by the maintainer` section to
the body — never edit the agent's text into agreement with you.** Step 2 above says the person who
did the work writes the record; without somewhere to put a verification, that rule leaves rewriting
as the only way to record one, which is exactly what it forbids. The section is the missing half,
not a new ceremony.

**This happens at review time, not at creation time** — you have verified nothing when you open the
pull request, and your verification is the *Reviewing* section below. So it is an edit to a body
that already exists, and that has its own op:

```bash
supertool 'gh-pr-edit:<N>:@<FILE>'
```

The payload is the shape `gh-pr-create` takes. **Read the published body out first and build the
payload from it** rather than reconstructing it — the write replaces the whole body, so an append
built from memory silently truncates the record you were protecting.

**Use the op rather than raw `gh pr edit`, and #195 is the whole reason.** `gh pr edit` resolves the
pull request through a GraphQL query that also asks for `projectCards`, a Projects (classic) field
GitHub now refuses. It exits non-zero naming `repository.pullRequest.projectCards` — a field you
never asked for, about a feature you are not using — and **leaves the body unchanged**. The command
is loud and the *edit* is silent, and the error reads as deprecation noise rather than as an
unwritten body, which is what makes it dismissible: a maintainer following the old wording believed
a verification was recorded and the pull request carried none. Two things bound it, both measured
rather than assumed, and neither is the reason to prefer the op:

- **It is not about your repository.** The field is refused for **every** repository, so this does
  not depend on classic project cards existing anywhere.
- **It is about your `gh`.** A current `gh` consults a detector and drops the field where Projects
  (classic) is unsupported (cli/cli#13069); a `gh` predating that fix asks for it unconditionally
  and fails every time. So the raw call will start working again on its own, which is exactly why
  pinning a hand-rolled replacement for it would have been the wrong fix.

**The mechanism was never the load-bearing half — the read-back is.** The op writes through REST,
then compares the body the response carried against the bytes it sent and reports `EXACT`,
`NORMALISED`, `MISMATCH` or `UNKNOWN`, and only the first two exit `0`. That is this repository's own
rule enforced rather than remembered: **a write that landed something else is never rendered as a
success**, and a verification reported from a command's return is a record nobody read —
indistinguishable from a verification nobody performed. If you ever do reach for a raw call you have
taken that guarantee back into your own hands, so re-read the published body yourself with
`gh-pr:<N>:full` and confirm your section is in it. `:full` is load-bearing there: a plain read
truncates a long body and an appended section sits at the end, so the cheap read is precisely the one
that cannot see what it was called to confirm.

**The op also closes the composition that made this worse than a broken command.** `gh-pr-create`
**reports** a body with no `Closes #N` at creation, the earliest point anything can see it — and
**reporting is all it does: the pull request is created and the op exits 0.** This document said
*refuses* until #209, which is the more expensive error of the two, because the sentence that claims
a guarantee is the sentence that stops anyone checking. Measured on two pull requests in one night,
both created at `exit=0` with no binding closing reference and repaired by hand before merge; four of
seven agent payloads across two sessions carried the same defect. **So read the receipt** — it names
the issues the body links, and *No closing keyword in the body, so merging this will close nothing.*
is the line that means nobody will. A separate check does refuse: the report validator rejects a
`pr_body` whose declared `closes` is unmet. That is the payload being validated before it is used,
not the forge call being blocked, and the two must not be read as one gate. When the
repair *is* that reference, a silent no-op merges the pull request with the issue still open and the
board reading clean — the exact failure the merge gates warn about, reached through the tool that was
supposed to prevent it. `gh-pr-edit` re-parses the published body with the same reader `gh-pr` uses
before it writes, in three states — the references survived, one was **dropped**, or the body **could
not be read at all** — and refuses on either of the last two, because those are not the same answer.
A deliberate re-scope says so with the `unlink` token rather than arriving indistinguishable from an
accident.

What belongs in it is only what the agent could not have written: an independent reproduction or red
run, a premise of the brief the agent falsified, and your acceptance or rejection of its argued-down
findings. **Nothing else — an appendix restating the agent's claims in your voice is worse than no
appendix, because it reads as corroboration and is a copy.** Having nothing to add is a normal
outcome and the section is simply absent then, which means the converse holds and is worth stating:
**an absent section says nobody verified independently, not that verification found nothing.** If
you want the second of those on the record, write the section and say so.

**Two ways a body silently references less than it appears to**, both worth catching before you
publish rather than after the squash:

- **A backticked issue number does not autolink.** `` `Part of #137` `` inside a code span creates
  no reference at all on the forge, and renders as something that plainly did.
- **A closing keyword binds one issue only.** `Closes #A #B` links both numbers and closes only
  `#A`; `Closes #A B` does not even link `B`. Two issues need the keyword repeated — `Closes #A,
  closes #B` — and the safe habit is one `Closes` line per issue. The merge gates carry the second
  of these two cases; this is the first, and it is the one that looks correct.

