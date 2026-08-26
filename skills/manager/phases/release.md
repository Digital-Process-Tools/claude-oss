# Release: the six gates

**Read this when** a release trigger has fired -- before any version site is touched. `/oss:release` is the wired form of it.

`skills/manager/SKILL.md` is the spine and carries the directives; this file carries the argument
each one rests on -- the incident it was written for, the measurement behind it, the thing that was
tried and rejected. A rule here that reads as obvious is one that has already been got wrong.

**Say whether you read it.** Three states, the same three everything else in this loop uses:
`read`, `not-read` with the reason, or `could-not-read`. A phase entered without its file is a set
of rules that did not run, and a rule that did not run renders exactly like a rule with nothing to
say -- so the absence is stated, never silent.

---

## Releasing

Trigger, whichever comes first: **N merged PRs since the last tag**, **any user-visible fix plus a
soak period**, or **immediately for anything in a class the ranking table above marks blocking** —
`destroys`, `discloses`, `containment (read)`, `containment (write)`, `forges`, `ships-local-state`.

Thresholds live in user config; state them out loud when reporting, because a threshold nobody can
see arriving is indistinguishable from deciding on a whim.

Gates, each a call and not a feeling:

1. **The default branch is green at leg level for the exact commit being tagged** — and count the
   *workflows*, not just the runs. `gh-branch` answers in **three** states and so does this gate:

   - the workflow ran here and passed — covered;
   - it is declared and **could not have run on this commit**, because its triggers do not include
     the event that produced the commit. Not a pass, **not a blocker**, and it
     **contributes no coverage** — name it in the report with where its coverage came from;
   - it is declared, **should have run, and did not** — `UNKNOWN`, and it blocks. Unchanged.

   The middle one is a measurement of an `on:` block, so re-read it from the op each release rather
   than remembering it: a workflow that gains a `push:` trigger moves to the blocking state with
   nothing announcing it.

   **Resolve the commit before you ask about it: `git rev-parse HEAD`, never an abbreviated sha.**
   That holds for whatever asks the forge which workflows ran — `gh-branch` above, or a raw
   `gh run list --commit` when no op carries the field you need. A short sha returns `[]` and exits
   0 from `gh run list --commit`, while the full **40-character** sha returns the runs on that same
   commit. `git log --oneline` hands you the short form, so the empty list is the default result —
   and an empty run list is indistinguishable from a commit no workflow ran on, which is this gate
   counting nothing and reporting a pass.
2. **Nothing in flight is mid-review.**
3. **A security audit of the delta since the last tag passed.** Three outcomes: clean → proceed;
   findings → **stop the tag** and file, **in round one**; **could not run → stop the tag and say
   so.** Neither one stops the loop; the continuation for each is below. Round two is
   different and deliberately so: what it finds is filed and the release ships over it.
   **Two audit rounds, hard cap** — a
   competent audit of any non-trivial delta always finds something, so an unbounded "findings → stop"
   makes every release hostage to diminishing returns. After round two, file the rest against the
   next milestone and ship.

   **One exception, and it is why the ranking is not decoration: a finding in a row the table marks
   blocking is not carry-forward material.** It stops the tag in either round. Without that, the cap
   outranks the table by being later in the document, and a gate whose worst outcome is a filed issue
   is not a gate. Each finding the auditor hands back carries its row, so this is a read and not a
   judgement — until one comes back with no row at all, which is two different answers and gets two
   arms:

   - **`unranked`** — the agent classified it and no row fits. It is ranked **here**, before the cap
     is applied to it, and the row decides from there. **The cap does not reach a finding that has
     no row yet**, so nothing is ever carried forward unranked.
   - **`could not rank`** — the table never reached the agent, so nothing was ranked and the audit
     did not complete. That is `could not run`, and it **stops** the tag. Re-dispatching with the
     table in the payload is how the answer gets computed; it is not an extra round.

   **Since #320, a `clean` verdict is itself graded, and a completion is joined to its own
   dispatch.** Two additions to this gate, not a separate one:

   - **The grade.** A class with no findings is `clean (exercised)` — a control ran that would have
     failed had the class been present, and it did not — or `clean (read)`, a look with no control
     behind it, which must never be weighed as the measured grade above. The verdict line carries
     `<k> of <m> classes read but not exercised`, and a nonzero count does not stop the tag by
     itself: it annotates rather than blocks — demanding a fired control for every class on every
     delta buys more words rather than a better audit. A `read` grade never outweighs a reproduction,
     from any source — a second completion, a contributor, you.
   - **The attribution.** The gate mints a dispatch token before the spawn and the auditor echoes it
     back. **unattributed** — no token, a mismatched one, or `dispatch token: none reached me` —
     does not clear the gate and is not discarded: read its findings and reconcile them, because in
     the instance this arm comes from the unattributed completion was the one that was right and the
     attributed one graded the same class clean. **More than one completion** for one dispatch clears
     only when every one of them agrees.

   **Stop the tag, not the loop.** This is the only gate whose failure *produces* work — the others
   clear themselves or name their own remedy — so every blocking arm has a continuation: round-one
   `findings` are filed **and the blocking rows delegated in the same tick**; a blocking row puts its
   fix on the release's **critical path**, ahead of the general backlog, because the tag cannot move
   until it lands; `could not run` is followed by diagnosing why it could not, not by waiting. None
   of that stops the loop, and the rule for what does is *Loop mechanics* above — read there, not
   restated here.

   Full mechanics — the exact template lines, the report wording, the re-dispatch procedure — live in
   `commands/release.md`'s own numbered gate 3, which is this gate's single source; this paragraph is
   a restatement of it, not a second definition (#321).

   The gate is performed, not judged: `scripts/release_delta.py` computes the range in three states
   and `oss:release-auditor` reads it. **`could-not-run` is the script's answer, not yours**, and it
   stops the release — a shallow clone or a tag HEAD cannot reach is the third outcome, and so is a
   spawn that never ran. **No tag at all is a `first release`**, which is a named state rather than
   an empty diff: the delta is the whole history, it gets audited, and it permits the tag. This is
   the gate the loop stated for months with nothing behind it, so the outcome to distrust is the
   quiet one.
4. **The number itself is proposed from the changelog fragments, not felt.** Every other input here
   is pinned somewhere; the version was the one thing nobody could derive, so it came from whoever
   was cutting the release. `scripts/release_version.py` reads the fragment sections and the current
   version and answers in three states — `proposed`, `could not decide`, `no baseline`. **On
   `proposed`, quote the receipt, accept the number, and record it — no stop (#467).** This is
   unconditional and does not read `release.authority`: `## Who decides` above already lists
   deriving a version number from rules the repository already states as the loop's, and stopping
   to have the derivation confirmed was asking permission to use an authority already granted.
   Override remains available — you may still override the proposal and record why; accepting by
   default is the absence of a prompt, not the loss of that override.

   **A major bump keeps its stop, and it is the one arm of this gate that does.** The proposal rule
   reaches a major only at `1.0.0` or later — `payload["bump"] == "major"` in the receipt — where the
   promise to users is a different promise. Say so and stop, the same shape as every other row in
   the Stops table above.

   The two answers that are not a proposal share one property, deliberately: the rule
   **names no number** when it could not decide one. A default bump over a breaking change is
   indistinguishable in the tag from a considered one. Fix what the receipt names and re-run rather
   than picking one.

   The rule, written down so "it depends" stops deciding it: **in a `0.x` line a breaking change is a
   minor, and at `1.0.0` or later it is a major.** The section alone never settles it — a removal need
   not break anything — so the fragment carries the verdict as a declared field, required on
   `removed`, and a fragment that declares nothing there is `could not decide` rather than a quiet
   minor.
5. **Every version site bumped**, swept **unfiltered** — a README is not a `.json` and an allowlist by
   extension cannot see it. A sweep keyed on the *outgoing* version only finds sites that are
   half-bumped; it cannot find one frozen at some third value, which is the one most likely to be
   wrong.
6. **The tag is not the delivery.** For plugin users the manifest version is what the updater
   compares; for catalogue users the pin is a commit sha somebody else advances. Report which
   surfaces the release actually reached, in those words — "tagged, not yet in the catalogue" rather
   than "shipped".

A quiet `git push origin <tag>` can die inside a wrapper and read exactly like a push that worked.
Verify with `git ls-remote --tags origin <tag>`, or create the ref through the API.

