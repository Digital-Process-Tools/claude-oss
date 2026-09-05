---
title: "Writing a test here: ten traps that each cost a CI round"
description: "A fixture is a measurement, not a given. Long paths, permission denies, injected failures, ambient credentials and section locators must be established, not assumed -- and a check must name its subject and derive its location."
match: (^|/)tests/
---

**A condition you did not establish must not be asserted on.** Attempt the exact operation the code
under test performs; when it does not take, `pytest.skip` carrying the platform, the errno and the
sentence naming what went untested.

- **Long-path fixtures: build the length from many short components.** Windows caps the whole path
  at 260, POSIX caps each component at 255. Four nested directories failed all four Windows legs at
  `git init -q: Filename too long`; one 256-byte component then failed all eight POSIX legs. A
  construction that cannot violate either limit is the fix, not shorter names — shortening deletes
  the case on the one platform where paths are long.
- **A permission fixture is a measurement.** Root ignores the mode bit, some filesystems ignore it,
  and Windows' `os.chmod` on a directory toggles a read-only attribute that does not stop a listing.
  Confirm the deny by attempting the operation; never assert on an error code from a table.
- **Patch the method the code under test calls, not a module attribute.** `pathlib` on **3.10 alone**
  binds `_NormalAccessor.open = io.open` at import, so monkeypatching `io.open` injects nothing.
  Patch `Path.write_text` / `Path.read_bytes` — looked up on the class at call time on every version.
  Green on 3.9, 3.11, 3.12 and red on all three OSes at 3.10 is this bug.
- **A stdlib answer is not a constant across interpreter versions.** `ntpath.isabs("/etc/passwd")` is
  `False` on 3.13 and `True` on 3.9-3.12. Do not pin the answer your local interpreter gives; remove
  the dependence on a live `os.path` answer (a fabricated stand-in module, a normalized string test).
- **`pytest.raises(Exception)` does not catch a skip.** pytest's outcome exceptions derive from
  `BaseException`, so a `pytest.skip` inside the block skips the enclosing test — a green tick over
  an assertion that never ran, reported as `1 skipped` where nobody reads it. Pin the outcome type
  when a test's subject is a skip.
- **A guard over "did this platform distinguish these two cases?" asks a control, never a table.**
  Windows folds several Win32 codes onto `ENOENT`; a `winerror in (2, 3)` skip arm cannot report a
  value it does not contain. Open a plainly-missing path of the same shape and compare: identical
  answers mean there is nothing to classify, and it skips carrying both.
- **Pin `PATH`.** With the stub absent, the launcher finds the real `claude` and executes it — a
  suite starting live agent sessions in temp directories.

- **Ambient credentials are a third axis, beside OS and interpreter, and the least visible.**
  `tests/test_select_issues_970.py` spawned `select_issues.py` as a subprocess; that reached the real
  `issue_claim.check`, which shells out to `gh issue view`. The author's shell was authenticated, so
  it passed locally. CI has no `GH_TOKEN`, `gh` exits 4, and the code correctly answered
  `could-not-select` — red on every leg. **The code was right and the test was environment-dependent**:
  it asserted a success path reachable only when the environment happens to carry credentials, and
  said so nowhere. Unlike OS and interpreter this is not a property of the machine at all — the same
  laptop passes or fails depending on whether somebody ran `gh auth login` that month. Any test whose
  subject shells out to `gh`, `git push`, or anything authenticable must pin the unauthenticated case
  explicitly, or it is measuring the author's session. A review spawn found the identical dependency
  in a sibling test — the first was found by CI, the second only by looking for more of the shape.

- **A content check should name its subject and derive its location.** `text.find("## What is not
  proven yet")` takes the *first* occurrence: adding a cross-reference elsewhere in `CLAUDE.md`
  containing that literal string (inside backticks, which `find` does not care about) repointed two
  tests at the wrong section, and four tests went red reading as *the section has gone stale* — the
  opposite of what happened. Anchor on `\n## ` at line start, or the heading plus its newline. The
  worse case is the same bug passing: `test_the_release_trigger_names_exactly_the_rows_that_block`
  found its marker in the *wrong file* because the intended sentence had reflowed between the two
  words it matched on, and reflowing one more line would have landed it on a sentence that enumerates
  nothing — green, vacuously. Splitting `SKILL.md` twice turned this up six times; the guards that
  survived were the ones deriving location from the spine's own text
  (`checklist_skew.py`, `manager_docs.documents()`), not the ones that pinned a filename.

- **A test whose comment names a source of truth must import it.** A parity guard read
  `#: dispatch_rank.SHORT_REASONS is the actual source of truth` and then compared
  `agents/sub-manager.md` against `commands/tick.md` — two prose copies against each other, so both
  naming the same stale set was indistinguishable from both being right. A fourth word was added to
  `SHORT_REASONS` and the guard went on reporting parity, shipping a refusal no dispatching agent had
  been told about. `tuple(_dispatch_rank.SHORT_REASONS)` made it fail immediately on both briefs.
  Note `loop-prose-parity.md` already said *pin the measured tool output, not the parity* — it fires
  on `agents/*.md` and `skills/manager/**`, not on the test asserting over them, so the guidance was
  in the session and pointed at the wrong file.

**A negative assertion needs a positive control**: pair every must-not-fire with a must-fire in the
same fixture, or an assertion that nothing happened also passes when nothing ran.
