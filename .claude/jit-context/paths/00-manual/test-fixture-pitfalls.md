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
- **Pin `XDG_CACHE_HOME` in every doctor/statusline test, not only the one you
  are fixing.** Three separate incidents (#1428, #1499, #1508), each caught
  only on the maintainer's own machine and green on CI:
  `_quiet_main`/`_rig`-style harnesses in `test_doctor_inprocess.py`
  exercise real cache-writing paths (`statusline.cache_dir`, the
  channel-health reading) without redirecting `XDG_CACHE_HOME`, so a
  stray real file under `~/.cache/oss-statusline/` -- written by an
  earlier, unrelated test run using the same placeholder repo slugs
  (`owner/name`, `owner/repo`, `a/b`) -- leaks into the fixture and
  produces a WARN the test does not stub. Confirmed each time by
  re-running with `XDG_CACHE_HOME` pointed at an empty directory.
  Fixing one consumer (`check_latest_skew`) did not fix the next one
  (`check_channel_delivery`) sharing the same unpinned harness --
  isolate the harness itself, not each symptom as it is found.
  Roughly twenty other test files share the placeholder-repo-slug
  pattern with no confirmed isolation nearby (`ls -la
  ~/.cache/oss-statusline/` is the fast diagnostic for whether this
  is recurring).

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

- **A positive control that never calls the real check is not a control.**
  Three instances in one release-audit round. A control for "the file
  must document the `external` filter" asserted a hand-typed local
  string contained that substring, never running the real filter token
  against supertool -- it would still pass if the documented call were
  refused outright, which it was (#1573). A sibling control for "the
  broken filter string must not appear" built its own local string and
  asserted membership against *that*, never touching the real path
  constants or the real helper the actual check uses -- it would pass
  even against an empty file. And a must-not-contain-X test that
  filters a file's own lines to a narrow shape (lines starting with
  `python3`) before asserting none contain X passes vacuously forever
  when the file states its calls as prose rather than literal command
  lines, regardless of content. **A control proves the mechanism only
  when it runs the real helper against the real file** -- a synthetic
  string standing in for either one tests itself, not the check.

**Assert the weakest property that actually matters, not the strongest one that happens to hold
locally.** A test asserting cross-implementation agreement on a platform this suite does not run on
locally cannot be red/green verified before it reaches CI. #1295's own
`test_statusline_safe_which_agrees_with_gh_which_on_a_real_directory` asserted byte-exact string
equality and went red on exactly the windows-latest/3.12 leg with `...git.exe` against `...git.EXE`
-- both resolving the identical on-disk file, from two walks that read the same PATHEXT and are
logically identical. Windows execution does not care about extension case at all, so the property
that mattered was "do the two walks land on the same file", not "do they spell the extension
identically"; the fix was `os.path.normcase`, which `safe_which`'s own dedup already uses. The
strongest property is the one likeliest to be an artifact of the single platform actually testing
it. (Root cause of the case difference itself: still unexplained.)

- **Monkeypatching a re-exported name patches the copy nobody calls.** `scripts/lane_setup.py`
  re-exports every submodule name at module level for backward compatibility, but `compute()` calls
  through the submodule (`lane_setup_worktree.resolve_base(...)`), not the re-exported alias. A
  `monkeypatch.setattr(lane_setup, "resolve_base", ...)` rebinds an attribute nothing reads; the
  real function then runs against the test's throwaway fixture, hits its own error path, and the
  test's asserted exit code arrives from a code path the test was never exercising (#1535). This hid
  a genuine regression for some time -- the fixture had gone stale and the code under test had
  changed shape, and the test stayed green throughout because the dead patch was supplying the exit
  code by itself. Grep for `setattr(<module>, "<name>"` to find the sites; only reading the *call*
  tells you which binding is live. Confirm by adding a paired positive control in the same fixture
  -- the identical call with the failure condition removed must reach the real success path, not
  just avoid the error one.
- **Deleting a surface needs a derived caller sweep, not a hand-picked one, and re-run after any
  rebase onto a moved base.** A sweep that greps every removed name across `scripts/`, `skills/`,
  `agents/`, `commands/` and `tests/` before deleting is necessary but not sufficient: a sibling PR
  can land a new test file that references the same names while your branch is in review, and a
  rebase with nothing to conflict on will not surface it because you never touched that file (#1532).
  Re-run the same grep after any rebase onto a moved base. Choosing the test set to run is the same
  problem one layer down -- a hand-picked "lane's own tests plus the named guards" list cannot
  contain a file that set never named; deriving it instead (every `tests/test_*.py` whose source
  imports one of the touched modules) is far cheaper than the full suite and is the one that would
  have caught a stale reference before CI did. Also check for orphaned fixture helpers left behind
  by a deleted parameter -- an unused nested `def _helper()` is silent, so only a name-based grep
  finds it; deleting a parameter and deleting the fixture that fed it are two edits.
- **Use a synthetic fixture path, not a real lane-owned one.** A new test file's own fixture data
  reusing a real cross-lane path (`CLAUDE.md` is the headline example) trips
  `doctor_check_lane_coupling.py`'s whole-test-tree static scan for literal paths matching two or
  more declared lanes' globs -- a check a lane's own targeted `--lane`/`--derive-held` guard list
  cannot surface, because it answers "which guard does this lane's own file set trip", never "does a
  new test file about to be written trip a repo-wide invariant" (#1528). The new file does not exist
  on disk until the guard already needs to see it. Prefer an obviously synthetic fixture string
  (`fixtures/example-a.md`, `held-example.txt`) over a real, well-known repo path whenever the test's
  own subject does not actually depend on the path being real.
