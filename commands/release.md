---
description: Cut a release — gates first, then version sites, tag, and the surfaces it actually reached.
allowed-tools: Bash, Agent, Skill
---

Read `.oss.json`'s `release` block for what this repo does: `tag_pattern`, `commit_subject`,
`merge_method`, `triggers`. It is the tracked half of the config, so it is the same block for every
maintainer; the git-excluded `.oss.local.json` beside it holds only this machine's paths and nothing
release reads.

Two of those keys may be null, and they are handled differently on purpose:

- **`tag_pattern: null` — stop.** The probe could not tell how this repo tags, and inventing one
  opens a second tag namespace nobody notices until a release goes missing from it. Ask, then write
  it into the config. A wrong tag is permanent.
- **`commit_subject: null` — use `chore(release): {version}`.** That is the plugin's default, not a
  line for you to compose: a subject invented per release is an absence the tool produced, rendered
  as a value. Substitute the version being released. Nothing to ask about, because a wrong subject
  line is cosmetic and the next commit fixes it — which is exactly why this one gets a default and
  `tag_pattern` does not.

Load the loop for the judgment behind each gate:

```
Skill(manager)
```

## The gates are not configurable

Nothing in `.oss.json` can switch one off. Each is a call, not a feeling:

1. **The default branch is green at leg level for the exact commit being tagged.** Count the
   *workflows*, not the runs — one declared in `.github/workflows/` but absent from the run list is
   `UNKNOWN`, never a pass. `supertool 'gh-branch'`, which is conjunctive over every workflow on the
   head SHA.
2. **Nothing in flight is mid-review.**
3. **A security audit of the delta since the last tag passed.** Three outcomes: clean, findings, or
   **could not run**. An audit that did not execute must never render as an audit that found nothing.
   **Two rounds, hard cap** — a competent audit of any non-trivial delta always finds something, so
   an unbounded "findings, therefore stop" makes every release hostage to diminishing returns. After
   round two, file the rest against the next milestone and ship.

   **Except a finding in a row the ranking table marks blocking, which is not carry-forward
   material.** It stops the tag in either round. Each finding comes back carrying its row, so this is
   a read rather than a judgement — and without it the cap outranks the table by being later in the
   document, which makes the gate's worst outcome a filed issue.

   The range is computed before anyone judges it, because "could not run" is a fact about the
   repository and not a reading:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_delta.py" --repo . --json
   ```

   It reads `release.tag_pattern` out of this repo's `.oss.json` itself and derives the tag glob
   from it — `v{version}` becomes `v*`. **Do not compute that glob and interpolate it into the
   command.** A value you are told to substitute is a value you can substitute wrongly, and a wrong
   glob answers confidently about the wrong range. `--match` exists to override the derivation and
   `--config` to point at another file; neither is part of the normal call.

   - **exit 3, `could-not-run`** — no commits, a shallow clone, or tags HEAD cannot reach. That
     **stops the release**. Report the reason it gave; do not spawn the audit over a range you
     picked instead, and do not read the gate as satisfied because nothing objected.
   - **`first-release`** — no tag exists, so this is a **first release** and the delta is the whole
     history reachable from HEAD. A named state, not an empty diff: it is audited like any other
     range and it permits the release once audited. Inventing a tag so a previous one exists is a
     history nobody made.
   - **`delta`** — audit `range`. `commits: 0` is an empty delta, which is computable and is not a
     finding.

   `scope` is a separate fact from the state, and it is not a fourth outcome. **`scope: null`, which
   the receipt prints as `UNSCOPED`, does not stop anything** — a repo that has not said how its tags
   are spelled is common, and blocking it trades a reporting gap for a release nobody can cut. It
   does have to be carried: pass `scope_reason` to the auditor with the payload and repeat it in the
   release report, because an unscoped range anchors on whatever tag is newest, which in a repo that
   also tags nightlies or candidates is a fraction of the real delta. When the reason is a null
   `tag_pattern`, that is the same finding as the stop-and-ask at the top of this file, reaching you
   from the other direction.

   The reverse is now true as well: `tag_pattern` decides the range, not just the tag you are about
   to write. A pattern that disagrees with how this repo actually tagged its last release anchors the
   audit somewhere else — or reports `first-release` in a repo with releases — so a `scope` that does
   not match the tag you expect is a config finding, not a delta.

   Then, and only for the two computable states:

   ```
   Agent(subagent_type: "oss:release-auditor", run_in_background: false)
   ```

   Hand it the payload verbatim and the round number. It writes nothing and it does not tag. **A
   spawn that did not run is `could not run`**, never a clean audit — if the agent fails to start or
   comes back empty, that is the third outcome and the same stop applies.

   **A spawn that errors because the name does not resolve is that same `could not run`**, and it is
   not hypothetical: this gate dispatched to a name the harness never registered for two releases,
   so its third outcome was its permanent state and nothing reported it (#81). A release read as
   having passed its gates because the error scrolled past. So:

   - **Quote the spawn error verbatim in the release report.** It is the only thing that separates a
     wiring failure from a clean audit, and both otherwise render as silence.
   - **Re-dispatch to `general-purpose` with a pointer to `agents/release-auditor.md`**, handing it
     the same payload, the same round number and the same "writes nothing, does not tag". An audit
     performed by the fallback is an audit; record which agent ran.
   - **If the fallback does not run either, the gate is `could not run` and the release stops.** The
     contract above is unchanged by *why* nothing ran. Do not audit the delta yourself in its place
     — the gate asks for an independent read, and the releaser is not one.

4. **Every site in `version_sites` bumped**, swept **unfiltered**:

   ```bash
   git grep -n "<the new version>"
   ```

   A sweep keyed on the *outgoing* version only finds sites that are half-bumped. It cannot find one
   frozen at some third value, which is the one most likely to be wrong. A README is not a `.json`,
   so an allowlist by extension cannot see it.

## Then

Fold the changelog if this repo uses fragments (`/oss:changelog`), commit with `commit_subject` —
or with `chore(release): {version}` when it is null, per the rule above — and tag. Then **verify the tag exists on the remote**:

```bash
git ls-remote --tags origin <tag>
```

A quiet `git push origin <tag>` can die inside a wrapper and read exactly like a push that worked.

## Then publish the release, if this repo publishes

A tag with no release object leaves the releases page showing a bare tag with no notes, nothing
marked `Latest`, and nobody who watches for releases notified. That surface is entirely within
reach — the notes were assembled a moment ago and it depends on nobody else — so it is closed here
rather than narrated (#58):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_publish.py" \
  --repo . --version <the new version> --tag <the tag> --json
```

That is the dry run: it prints the command it *would* run and calls nothing. Add `--execute` to
create the release. Read the printed command before you do.

**Do not assemble the `gh` call yourself.** `--verify-tag` is the reason: without it
`gh release create` creates the tag when it is missing, which turns the `git ls-remote` check above
into a step that mints the very ref it was verifying. The script emits it on every branch that
builds a command and the suite asserts the whole argv, so it cannot be lost to an edit. `--repo`
is always passed for the same class of reason — `gh` otherwise infers the repository from whichever
directory it is standing in.

The notes are the `## [x.y.z]` section `/oss:changelog` just wrote, everything up to the next
`## [`. A heading with no body under it is **not** empty notes; it is `could not run`.

Three outcomes, exit codes because a shell reads those and never reads prose:

- **exit 0, `create` / `created`** — the command is buildable, or it ran and the release exists.
- **exit 4, `skipped`** — `release.create_release` says this repo does not publish, or has not said.
  A decision, reported as one. It never stops the release: the tag is the release for a project that
  tags deliberately without publishing.
- **exit 3, `could-not-run` / `could-not-create`** — the notes could not be extracted, `gh` is not on
  PATH, the API call failed, or `.oss.json` is not a JSON object at all. **Say so in those words.**
  This is the one that must never read as either of the other two, and above all never as a release
  that shipped: a maintainer who believes something is published stops looking at it.

A `.oss.json` that parses but is not an object — `[]`, `"x"`, `null`, `42` — is exit 3 and not exit
4. It states no policy, which is a different fact from stating one that does not publish, and the
two were indistinguishable until #126: the shipped defaults answered for it and the run reported
*skipped by policy* naming a key the document could not have set. The tag shipped and the Release
silently did not.

The policy lives in `.oss.json`'s `release` block, tracked, because how a project publishes is the
project's answer and not one laptop's:

| Key | Default | Why that default |
| --- | --- | --- |
| `create_release` | `false` | Publishing a repo that never asked is not this tool's call to make. |
| `draft` | `true` | A draft is undoable. A published release has already notified everyone. |
| `latest` | `false` | `Latest` changes what the repo's landing page shows, and that page is theirs. |

Unset is a third state, not a quiet `false`: the skip reason names `release.create_release` so a repo
that never chose is told what would change it rather than silently never releasing. `draft: true`
with `latest: true` is refused by the config validator — a draft cannot be Latest, so the pair states
an outcome no release path can produce.

## The tag is not the delivery

Publishing the release closes one surface. It does not close the others. For plugin users the
manifest version is what the updater compares; for catalogue users the pin is a commit sha somebody
else advances. **Report which surfaces the release actually reached, in those words** — "tagged and
released, not yet in the catalogue" rather than "shipped".

And the inverse is just as real: a repo can be *released by manifest and never tagged*, which leaves
the releases page a version stale while every install is already current. Check both directions
before saying the release is done.

## Cohort

At the tag, label everything then-open as a frozen cohort — in the same minute, by hand. Nothing
joins a cohort ever, so it can only shrink. This is the maintainer's act; the triager must never
write one.
