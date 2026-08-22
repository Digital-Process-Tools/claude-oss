"""A script in `scripts/` that nothing references is a file with no job -- and a
file with no job still gets read.

Issue #253 filed one sentence in `scripts/coverage_gate.py`: a claim that shell was
`bash -n`-parsed "on all twelve pytest legs", cited to a test this repository does
not contain. Re-derivation put that sentence in a different light. The file is a
vendored copy of another project's coverage gate; the cited test exists *there* and
that project's matrix really is twelve pytest legs, so the sentence is true in its
home repository. Nothing was wrong with the sentence. What was wrong is that the
file was sitting in `scripts/` at all, wired into no workflow, carrying a whole
document's worth of another repository's claims.

So the predicate this test uses is deliberately **not** the one the issue proposed.
"A cited test path that does not exist in this tree" fires six times on
`coverage_gate.py` -- and all six of those citations are correct upstream. It fires
on faithful vendoring, which is the one thing a vendoring check must not do. It
measures "is this file vendored", not "does this file describe us".

What separates the two vendored copies here is not their citations, it is whether
anything uses them. `assemble_changelog.py` is mentioned by 27 tracked files -- as
counted by `survey_unwired` below, which is the only count worth quoting here: a
shell `git grep -l assemble_changelog.py` says 34, because that `.` is a regex
wildcard, and a count that excludes nothing says 33 -- and it ships into every
scaffolded repo. `coverage_gate.py` was referenced by one file, and that one
reference existed only to exclude it from measurement. Hence the rule below, and
hence the three kinds of mention that do not count as a use:

* **Narrative.** `CHANGELOG.md`, `CLAUDE.md`, `changelog.d/*.md` and this module.
  Each of them names a file in order to say something *about* it, and a deletion
  documents itself in every one of them -- so counting them means a deletion
  immunises the very file it removed. Measured on this commit: after
  `coverage_gate.py` was deleted, the matcher still found three references to it,
  and all three were the files whose entire subject is that it is gone. The
  `changelog.d/` half is the sharper one, because those fragments are **deleted at
  the fold**: a script whose only reference is its own fragment is wired today and
  unwired the moment a release is cut, which is a red build on a release branch
  caused by nothing in that branch's diff.
* **A suppression.** The whole `[tool.coverage.run]` section says "here is what we
  do not measure, and why". That is a statement about a file's absence from the
  gate, not a use of it. Counting it would let a file justify its own presence by
  being excluded -- which is exactly the shape `coverage_gate.py` had. The section
  and not merely its `omit` array, because the first version of this check blanked
  the array alone and then passed on the real tree: `coverage_gate.py`'s single
  surviving reference was the *comment* four lines above the array, explaining why
  it was omitted. A prose suppression is still a suppression.
* **Another directory's file that happens to share a basename.** `.oss/foo.py` and an
  upstream `.github/scripts/foo.py` are not `scripts/foo.py`. Matching a bare basename
  makes any of them a use of ours -- and the file deleted for #253 spelled its own
  upstream path five times in its own text, so this is the shape that would have
  declared it wired by quoting itself. See `_mention_res`.

**The domain is every tracked file under `scripts/` and `bin/`, with no extension
test.** Selecting by suffix is #193 one directory over: `git ls-files '*.sh'` matched
one path while `bin/oss-workspace` -- tracked, POSIX sh, extensionless -- was linted
by nothing on any leg for its whole life, and the leg stayed green because a lint that
found nothing and a lint that never received the file both exit 0. `scripts/` and
`bin/` hold things that get run; anything in them that nothing names is dead whatever
it is called. Dropping the classification is stronger than improving it, and it is why
this module does not reach for `scripts/shell_sources.py`'s shebang detection: that
answers "is this shell", and after removing the suffix test there is no question left
to ask.

Four states, not two, in four places -- the fourth arrived with #396:

* `git ls-files` failing, or returning nothing, is *unknown* and skips with the
  reason; it is not a pass.
* A file that is *there* and cannot be opened, and a file that is not valid UTF-8,
  both come back in `unsearchable` with the reason -- separately from files that were
  read and did not match. `errors="replace"` is deliberately not used: it cannot
  raise, so an undecodable file was silently turned into U+FFFD and filed as "read, no
  match", which is the two answers rendering alike. `UnicodeDecodeError` is a
  `ValueError`, not an `OSError`, so both are caught by name.
* `unsearchable` does **not** on its own fail the assertion, and that is reasoned
  rather than lax: decoding more files can only ever *add* references, never remove
  them. So an unsearchable file cannot turn a wired script into an unwired one -- it
  can only leave an offender unexplained. It is therefore reported beside the
  offenders when there are any, and surfaced as a skip when there are none, instead
  of reddening the suite because somebody committed a PNG.
* **A file that is not on disk at all is `absent`, and that reasoning does not reach
  it (#396).** `git ls-files` reports the **index** while every read here happens in
  the **working tree**, so an uncommitted delete -- the changelog fold produces
  twenty-one at once -- hands this survey paths that are gone. Until #396 those went
  into `unsearchable`, under the argument in the bullet above, and that argument is
  false for them: an undecodable file's references are *unread*, an absent file's
  references are *lost*. Losing references does not leave an offender unexplained, it
  **manufactures** one -- which is the very shape the first bullet's `changelog.d/`
  half already describes, arriving through the read rather than through the
  exclusion list. So absence is decided from the exception in hand
  (`FileNotFoundError`, never a second question to the filesystem), reported by name
  in its own bucket, and the offender list declines to accuse while anything is in
  it. A candidate that is itself absent is not accused either: it is being deleted,
  not left unwired.
"""

import re
import subprocess
import unicodedata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories whose contents are surveyed. Everything tracked under them, with no
#: extension test -- see the module docstring for why that is #193 one directory over.
SURVEYED_DIRS = ("scripts/", "bin/")

#: Files that name a script in order to say something about it rather than to use it.
#: A deletion documents itself in every one of these, so counting them would let the
#: documentation of a removal keep the removed file looking alive.
#: This module is in the set because it names scripts in order to assert things about
#: them -- including, in `test_the_vendored_coverage_gate_is_gone`, that one is absent.
#: Derived from `__file__` rather than spelled out, so renaming the file cannot leave a
#: stale entry that silently stops excluding anything.
_SELF = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

NARRATIVE_FILES = frozenset({"CHANGELOG.md", "CLAUDE.md", _SELF})

#: Same reason, by prefix: changelog fragments, which are additionally deleted at the fold.
NARRATIVE_PREFIXES = ("changelog.d/",)

#: The `omit = [...]` array under `[tool.coverage.run]`, used to read the entries back.
#: Matched rather than parsed with `tomllib`, which is 3.11+ while this repository's CI
#: runs 3.9 through 3.12. `test_omit_pattern_matches_the_real_pyproject` is the control
#: that keeps it honest: a pattern that stopped matching would check nothing.
OMIT_RE = re.compile(r"^omit\s*=\s*\[.*?\]", re.DOTALL | re.MULTILINE)

#: The whole `[tool.coverage.run]` table, from its header to the next table or EOF. This
#: is the region blanked before counting references -- see the module docstring for why
#: the `omit` array alone was not enough.
COVERAGE_RUN_RE = re.compile(r"^\[tool\.coverage\.run\].*?(?=^\[|\Z)", re.DOTALL | re.MULTILINE)

#: Scripts allowed to be referenced by nothing, each with the reason. Empty today.
#: `test_every_exception_is_still_needed` fails when an entry stops being an exception --
#: an exception list that has drifted is a licence rather than a decision.
UNWIRED_EXCEPTIONS = {}

#: Characters that, immediately before a name, mean the match is part of something else:
#: word characters and `.` and `-` catch `oss_state.py` for `state.py`, and `/` catches
#: `.oss/foo.py` for `foo.py` -- another directory's file that merely shares a basename.
_LEFT_BOUNDARY = r"(?<![\w./\-])"


def _mention_res(rel):
    """Patterns that count as a reference to the tracked path `rel`.

    Two of them, and the pair is the point. Matching the *basename* alone reports
    `.oss/foo.py` or another project's `.github/scripts/foo.py` as a use of our
    `scripts/foo.py`; the file deleted for #253 spelled its own upstream path five
    times in its own text. Matching the *full path* alone misses every ordinary prose
    mention of a bare filename in backticks. So: the full tracked path anywhere, or the
    basename where it is not preceded by a separator.

    The left boundary also carries the `state.py` / `oss_state.py` fix -- a bare
    substring test reported an orphan as wired the moment its basename was a suffix of
    another file's, the check answering confidently about a file it never looked at.
    """
    base = rel.rsplit("/", 1)[-1]
    return (
        re.compile(_LEFT_BOUNDARY + re.escape(rel) + r"(?!\w)"),
        re.compile(_LEFT_BOUNDARY + re.escape(base) + r"(?!\w)"),
    )


def _surveyed_paths(tracked):
    """Every tracked file under the surveyed directories. No extension test -- see the
    module docstring: selecting by suffix is how `bin/oss-workspace` went unlinted."""
    return sorted(rel for rel in tracked if rel.startswith(SURVEYED_DIRS))


def _is_narrative(rel):
    return rel in NARRATIVE_FILES or rel.startswith(NARRATIVE_PREFIXES)


def _searchable_text(root, rel):
    """(text, None, None), or (None, kind, reason) for a file that cannot be searched.

    `kind` is "unsearchable" for a file that is there and will not read or decode, and
    "absent" for one `git ls-files` reports and the working tree does not hold. The
    reason is propagated in both cases, never folded into "did not match".

    The two are separated because they fail in opposite directions, which is the whole
    of #396 -- see the module docstring's third bullet. The exception already in hand
    decides which: `FileNotFoundError` is absence, any other `OSError` is a read that
    failed. No second question is put to the filesystem; `exists()` swallows a short
    list of errnos and re-raises the rest.

    Decoding is strict on purpose: `errors="replace"` cannot raise, so an undecodable
    file was quietly turned into U+FFFD and counted as read. `UnicodeDecodeError` is a
    `ValueError` rather than an `OSError`, so it is caught by name -- catching only
    `OSError` here would turn the third state into a crash.
    """
    try:
        raw = (root / rel).read_bytes()
    except FileNotFoundError as error:
        return None, "absent", error.strerror or str(error)
    except OSError as error:
        return None, "unsearchable", error.strerror or str(error)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return None, "unsearchable", "not valid UTF-8 ({})".format(error.reason)
    if rel == "pyproject.toml" or rel.endswith("/pyproject.toml"):
        text = COVERAGE_RUN_RE.sub("[tool.coverage.run]\n", text)
    return text, None, None


def survey_unwired(root, tracked):
    """Return (unwired, unsearchable, absent) for the surveyed directories.

    Three lists rather than one verdict. A script nothing mentions, a file that would
    not read, and a file that is not there are three findings, and they must not render
    alike. `unsearchable` and `absent` entries are `(path, reason)` pairs.
    """
    candidates = _surveyed_paths(tracked)
    unsearchable = []
    absent = []
    texts = {}
    for rel in tracked:
        if _is_narrative(rel):
            continue
        text, kind, reason = _searchable_text(root, rel)
        if kind == "absent":
            absent.append((rel, reason))
            continue
        if text is None:
            unsearchable.append((rel, reason))
            continue
        texts[rel] = text

    # A candidate the working tree does not hold is being deleted, not left unwired, so
    # it is named in `absent` and not accused. "Wire it, delete it, or except it" is
    # advice about a file somebody has already deleted.
    gone = {rel for rel, _reason in absent}

    unwired = []
    for rel in candidates:
        if rel in gone:
            continue
        full, base = _mention_res(rel)
        if any(
            other != rel and (full.search(body) or base.search(body))
            for other, body in texts.items()
        ):
            continue
        unwired.append(rel)
    return unwired, sorted(unsearchable), sorted(absent)


def offenders_are_conclusive(unwired, absent):
    """Whether an offender list is a finding or a maybe.

    Split out and given both halves a fixture, because the real tree is expected to
    have nothing absent -- a guard written inline would never execute and would be
    believed the first time it mattered.
    """
    return not (unwired and absent)


def stale_exceptions(exceptions, unwired):
    """Entries in `exceptions` that no longer name an unwired file.

    Split out so it can be driven by a fixture: the real `UNWIRED_EXCEPTIONS` is empty,
    so a detector written inline would never execute and would be believed the first
    time somebody added an entry.
    """
    return sorted(set(exceptions) - set(unwired))


def _tracked_files(root=None):
    """Tracked paths, NUL-separated.

    `-z` rather than a line split, because with `core.quotePath` at its default -- which
    is on -- a plain `git ls-files` returns a non-ASCII name wrapped in double quotes
    with every byte octal-escaped. That is not a path: reading it raises, the file lands
    in `unsearchable`, and the suite goes red on every leg because somebody committed a
    filename with an accent in it. `-z` also removes the newline-in-a-filename case for
    free. Decoded with `surrogateescape` so a path that is not valid UTF-8 survives the
    round trip instead of raising here, where there is no third state to report it into.
    """
    root = REPO_ROOT if root is None else root
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(
            "could not run `git ls-files` ({!r}) -- the survey below would otherwise "
            "have reported an empty tree as a clean one".format(exc)
        )
    if completed.returncode != 0:
        pytest.skip(
            "`git ls-files` exited {} -- cannot tell an unreferenced script from an "
            "unreadable checkout".format(completed.returncode)
        )
    names = [
        name
        for name in completed.stdout.decode("utf-8", "surrogateescape").split("\0")
        if name
    ]
    if not names:
        pytest.skip(
            "`git ls-files` listed no files -- every assertion below would pass "
            "vacuously against an empty tree"
        )
    return names


# --------------------------------------------------------------------------
# Controls. Each of these must fail before the assertion it guards is worth reading.
# --------------------------------------------------------------------------


def test_omit_pattern_matches_the_real_pyproject():
    """A pattern that matches nothing has checked nothing."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert OMIT_RE.search(text), (
        "OMIT_RE no longer matches the `omit = [...]` array in pyproject.toml. Until it "
        "does, a file named only in that array counts as referenced, and this module "
        "cannot see the defect it was written for"
    )


def test_coverage_run_pattern_matches_the_real_pyproject():
    """The suppressed region has to exist, and has to stop where the table stops."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = COVERAGE_RUN_RE.search(text)
    assert match, (
        "COVERAGE_RUN_RE no longer matches the [tool.coverage.run] table in "
        "pyproject.toml, so nothing is being suppressed and a file named only in its "
        "own omission would count as referenced"
    )
    assert "[tool.pytest.ini_options]" not in match.group(0), (
        "the suppressed region swallowed the pytest table -- it is blanking references "
        "that are real uses"
    )


def test_survey_flags_an_orphan_and_spares_a_used_script(tmp_path):
    """Must-fire and must-not-fire in one fixture.

    The orphan is named by both suppressions -- the omit array and the changelog -- so a
    survey that counted either would report this tree clean and this test would fail.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "used.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "scripts" / "orphan.py").write_text("print(2)\n", encoding="utf-8")
    (tmp_path / "scripts" / "linted.py").write_text("print(3)\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "subprocess.run(['python3', 'scripts/used.py'])\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.run]\n"
        "# scripts/orphan.py came from elsewhere and carries its own suite.\n"
        'omit = [\n    "scripts/orphan.py",\n]\n'
        "\n[tool.ruff]\n# scripts/linted.py is formatted here\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "- vendored scripts/orphan.py from elsewhere\n", encoding="utf-8"
    )
    tracked = [
        "CHANGELOG.md",
        "caller.py",
        "pyproject.toml",
        "scripts/linted.py",
        "scripts/orphan.py",
        "scripts/used.py",
    ]

    unwired, unreadable, _ = survey_unwired(tmp_path, tracked)

    assert unwired == ["scripts/orphan.py"], (
        "the survey must flag a script nothing uses even when a suppression names it -- "
        "here both an omit entry and a comment inside [tool.coverage.run], which is the "
        "pair that let issue #253 sit in the tree; got {!r}".format(unwired)
    )
    assert "scripts/used.py" not in unwired, (
        "the survey flagged a script that caller.py plainly invokes -- it is reporting "
        "every script, which would make the assertion below meaningless"
    )
    assert "scripts/linted.py" not in unwired, (
        "scripts/linted.py is referenced only from [tool.ruff], the table immediately "
        "after the suppressed one. Flagging it means COVERAGE_RUN_RE ran past its "
        "section and is blanking real references"
    )
    assert unreadable == [], "unexpected unreadable files in the fixture: {!r}".format(unreadable)


def test_a_basename_that_is_a_suffix_of_another_is_not_a_reference(tmp_path):
    """`state.py` is a substring of `oss_state.py`, and a bare `in` cannot tell them apart.

    Found by the auditor on the first version of this module, which matched with
    `name in body`: an orphaned `scripts/state.py` read as wired because something
    mentioned `oss_state.py`. That is this check reporting a file it never looked at,
    which is the defect the module exists to catch, one level up.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "oss_state.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "scripts" / "state.py").write_text("print(2)\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "run('scripts/oss_state.py')\n", encoding="utf-8"
    )
    tracked = ["caller.py", "scripts/oss_state.py", "scripts/state.py"]

    unwired, unreadable, _ = survey_unwired(tmp_path, tracked)

    assert "scripts/state.py" in unwired, (
        "scripts/state.py is referenced by nothing -- the only mention of the string "
        "in this tree is inside `oss_state.py`. A substring match reports it as wired; "
        "got unwired={!r}".format(unwired)
    )
    assert "scripts/oss_state.py" not in unwired, (
        "the positive half: oss_state.py really is referenced by caller.py, so a match "
        "that has become too strict to see it would be caught here rather than showing "
        "up as a red build on an unrelated branch"
    )
    assert unreadable == []


def test_survey_reports_an_unreadable_file_separately(tmp_path):
    """A file we could not read must not be silently counted as one that did not match.

    This fixture used to establish "could not read" by naming a file that was never
    written -- `tracked = [..., "vanished.py"]` -- which **is** the conflation #396 was
    filed for, in miniature: it asserted that a path in the index and absent from the
    working tree lands in `unsearchable`, so the wrong behaviour had a passing test.
    The condition is now reached the only way it honestly can be, by denying the read
    on a file that is still there, and the deny is measured rather than assumed.
    `test_a_tracked_file_missing_from_the_working_tree_is_absent_not_unsearchable` is
    the other half.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orphan.py").write_text("print(2)\n", encoding="utf-8")
    denied = tmp_path / "denied.py"
    denied.write_text("print(3)\n", encoding="utf-8")
    tracked = ["denied.py", "scripts/orphan.py"]

    try:
        denied.chmod(0)
        try:
            denied.read_bytes()
        except OSError:
            pass
        else:
            pytest.skip(
                "mode 0 did not deny a read here, so this platform cannot produce a "
                "tracked-and-unreadable file. UNTESTED here: whether a file that "
                "exists and will not read is reported separately rather than counted "
                "as one that did not match."
            )

        unwired, unsearchable, absent = survey_unwired(tmp_path, tracked)

        assert [name for name, _ in unsearchable] == ["denied.py"], (
            "an unreadable tracked file must come back in its own list, not folded into "
            "the clean path; got {!r}".format(unsearchable)
        )
        assert unsearchable[0][1], (
            "the entry must carry the reason it could not be searched -- a bare path is "
            "the same absence one field along, and the reason is the part a reader can "
            "act on"
        )
        assert absent == [], (
            "a file that is on disk and will not read is not an absent one, or #396's "
            "split has collapsed in the other direction; got {!r}".format(absent)
        )
        assert unwired == ["scripts/orphan.py"]
    finally:
        denied.chmod(0o600)


def test_a_file_with_no_extension_is_still_surveyed(tmp_path):
    """#193 one directory over: an extensionless script must not be invisible.

    `git ls-files '*.sh'` matched exactly one path in this repository while
    `bin/oss-workspace` -- tracked, POSIX sh, no extension -- was linted by nothing, on
    every leg, for its whole life. A survey scoped by extension reproduces that: the
    file is neither an offender nor unknown, it is simply not looked at, and the
    assertion goes green having never read it.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (tmp_path / "scripts" / "used.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text("run('scripts/used.py')\n", encoding="utf-8")
    tracked = ["caller.py", "scripts/tool", "scripts/used.py"]

    unwired, _, _ = survey_unwired(tmp_path, tracked)

    assert "scripts/tool" in unwired, (
        "an extensionless file under scripts/ is referenced by nothing and must be "
        "flagged. A survey that selects by suffix skips it and reports clean; got {!r}"
        .format(unwired)
    )
    assert "scripts/used.py" not in unwired


def test_narrative_files_do_not_count_as_a_reference(tmp_path):
    """A deletion documents itself, and the documentation must not resurrect the file.

    The docstring's own rationale for excluding `CHANGELOG.md` -- append-only history
    makes the check permanently unable to fire -- applies verbatim to a `CLAUDE.md` trap
    bullet and to a `changelog.d/` fragment. The fragment is the sharper half: fragments
    are deleted at the fold, so a script whose only reference is its own fragment is
    wired today and unwired the moment a release is cut, which is a red build on a
    release branch caused by nothing in that branch's diff.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "scripts" / "gone.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "scripts" / "used.py").write_text("print(2)\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text("run('scripts/used.py')\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("- removed scripts/gone.py\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(
        "- **A trap.** `scripts/gone.py` was deleted because nothing used it.\n",
        encoding="utf-8",
    )
    (tmp_path / "changelog.d" / "9.removed.md").write_text(
        "- `scripts/gone.py` is deleted (#9).\n", encoding="utf-8"
    )
    tracked = [
        "CHANGELOG.md",
        "CLAUDE.md",
        "caller.py",
        "changelog.d/9.removed.md",
        "scripts/gone.py",
        "scripts/used.py",
    ]

    unwired, _, _ = survey_unwired(tmp_path, tracked)

    assert "scripts/gone.py" in unwired, (
        "the only mentions of scripts/gone.py are the three files whose subject is that "
        "it was deleted. Counting any of them means a deletion immunises itself, and the "
        "changelog fragment additionally vanishes at the next fold, flipping the verdict "
        "on a release branch; got {!r}".format(unwired)
    )
    assert "scripts/used.py" not in unwired, (
        "the positive half: an ordinary reference from caller.py must still count, so an "
        "exclusion list that grew until it excluded everything is caught here"
    )


def test_a_same_named_file_in_another_directory_is_not_a_reference(tmp_path):
    """`.oss/foo.py` is not `scripts/foo.py`, and prose about another repo's tree is not a use.

    The false-positive twin of the `state.py`/`oss_state.py` bug: a left boundary that
    permits a slash makes any directory's `foo.py` a mention of ours. The file deleted
    for #253 spelled its own upstream path, under `.github/scripts/`, five times.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text(
        "upstream keeps this at .github/scripts/foo.py and vendors .oss/foo.py\n",
        encoding="utf-8",
    )
    tracked = ["notes.md", "scripts/foo.py"]

    unwired, _, _ = survey_unwired(tmp_path, tracked)

    assert "scripts/foo.py" in unwired, (
        "scripts/foo.py is referenced by nothing -- both mentions are other directories' "
        "files that share its basename; got {!r}".format(unwired)
    )


def test_a_file_that_is_not_utf8_is_reported_as_unsearchable(tmp_path):
    """The documented third state has to exist, not just be described.

    `errors='replace'` cannot raise, so an undecodable file was silently turned into
    U+FFFD and filed under 'read and did not match' -- the two answers the docstring
    promises to keep apart, rendered alike. Note the exception type: a
    `UnicodeDecodeError` is a `ValueError`, not an `OSError`.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orphan.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00 scripts/orphan.py \xc3\x28")
    tracked = ["blob.bin", "scripts/orphan.py"]

    unwired, unsearchable, _ = survey_unwired(tmp_path, tracked)

    named = [entry[0] if isinstance(entry, tuple) else entry for entry in unsearchable]
    assert "blob.bin" in named, (
        "a tracked file that is not valid UTF-8 cannot be searched, and saying so is the "
        "whole of the third state. It must not be decoded with replacement characters "
        "and counted as read; got {!r}".format(unsearchable)
    )
    assert "scripts/orphan.py" in unwired


def test_a_tracked_file_missing_from_the_working_tree_is_absent_not_unsearchable(
    tmp_path,
):
    """#396. `git ls-files` reports the index and every read here happens in the
    working tree, so an uncommitted delete arrives as a path that is not on disk.
    Filing it under `unsearchable` is wrong in a way the docstring's own reasoning
    does not cover: an undecodable file's references are *unread*, an absent file's
    references are *gone*, and only the second can manufacture an offender.

    Paired with a file that is there and will not read, which is the control -- a
    fix that renamed every failed read to `absent` would otherwise pass. The deny is
    measured rather than assumed.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orphan.py").write_text("print(1)\n", encoding="utf-8")
    denied = tmp_path / "denied.md"
    denied.write_text("nothing relevant\n", encoding="utf-8")
    tracked = ["denied.md", "gone.md", "scripts/orphan.py"]

    try:
        denied.chmod(0)
        try:
            denied.read_bytes()
        except OSError:
            deny_took = True
        else:
            deny_took = False

        unwired, unsearchable, absent = survey_unwired(tmp_path, tracked)

        assert [name for name, _why in absent] == ["gone.md"], (
            "a tracked path the working tree does not hold is not a file that would "
            "not decode -- it is a file whose references are lost, which is the one "
            "way this survey can invent an offender; got absent={!r} "
            "unsearchable={!r}".format(absent, unsearchable)
        )
        if deny_took:
            assert [name for name, _why in unsearchable] == ["denied.md"], (
                "the control: a file that IS there and will not read must still fill "
                "the unsearchable bucket; got {!r}".format(unsearchable)
            )
        else:
            pytest.skip(
                "mode 0 did not deny a read here, so this platform cannot produce a "
                "tracked-and-unreadable file. UNTESTED here: whether a file that "
                "exists and will not read still lands in `unsearchable` rather than "
                "being folded into the `absent` bucket #396 added. The absent half "
                "above was asserted."
            )
        assert "scripts/orphan.py" in unwired
    finally:
        denied.chmod(0o600)


def test_an_absent_reference_holder_leaves_the_offender_list_inconclusive(tmp_path):
    """The harm, stated as behaviour rather than as a bucket name.

    `scripts/tool.py` is referenced by exactly one file, and that file is deleted and
    not yet committed. The survey cannot read it, so the only mention of `tool.py`
    is gone and `tool.py` reads as unwired -- a red build caused by a delete nobody
    has committed, which `CLAUDE.md` already documents as the fold-window shape.

    So the survey has to say the offender list is *unreliable* while any reference
    holder is absent. The must-not-fire half is the test below it: with the same
    tree and nothing missing, the offender list is trustworthy and empty.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text("print(1)\n", encoding="utf-8")
    tracked = ["notes.md", "scripts/tool.py"]

    unwired, _unsearchable, absent = survey_unwired(tmp_path, tracked)

    assert "scripts/tool.py" in unwired, (
        "the mechanism: with its only reference holder off disk, the script does read "
        "as unwired. That is the false red, and the caller has to be told it may be "
        "one; got {!r}".format(unwired)
    )
    assert offenders_are_conclusive(unwired, absent) is False, (
        "an offender list computed while a reference holder was unreadable-because-"
        "absent must not be presented as a finding: the reference may be sitting in "
        "the file that is not there"
    )


def test_the_offender_list_is_conclusive_when_nothing_is_absent(tmp_path):
    """The must-not-fire half. Without it, a guard that always reported the list as
    inconclusive would pass the test above and disable the check outright.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("uses scripts/tool.py\n", encoding="utf-8")
    tracked = ["notes.md", "scripts/tool.py"]

    unwired, _unsearchable, absent = survey_unwired(tmp_path, tracked)

    assert unwired == []
    assert absent == []
    assert offenders_are_conclusive(unwired, absent) is True, (
        "with every tracked file on disk, an empty offender list is a finding and "
        "must be reported as one"
    )
    assert offenders_are_conclusive(["scripts/tool.py"], []) is True, (
        "and so is a non-empty one -- the guard is about absence, not about whether "
        "anything was found"
    )


def test_a_candidate_that_is_itself_absent_is_not_reported_as_unwired(tmp_path):
    """The other side of the same disagreement. A script deleted from the working
    tree and not yet committed has nothing to wire, and telling somebody to wire it,
    delete it or except it is advice about a file they have already deleted.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "here.py").write_text("print(1)\n", encoding="utf-8")
    tracked = ["scripts/gone.py", "scripts/here.py"]

    unwired, _unsearchable, absent = survey_unwired(tmp_path, tracked)

    assert "scripts/gone.py" not in unwired, (
        "a candidate that is in the index and not on disk is being deleted, not left "
        "unwired; got {!r}".format(unwired)
    )
    assert [name for name, _why in absent] == ["scripts/gone.py"], (
        "and it must still be named -- dropping it silently is the absence this "
        "plugin is named after; got {!r}".format(absent)
    )
    assert "scripts/here.py" in unwired, (
        "the control: an ordinary orphan beside it must still be reported, or the "
        "absent arm has swallowed the check"
    )


def test_tracked_paths_survive_a_non_ascii_name(tmp_path):
    """git quotes non-ASCII paths by default, and a quoted path is not a path.

    With `core.quotePath` at its default, a plain `git ls-files` returns the name
    wrapped in double quotes with every non-ASCII byte octal-escaped. Reading that back
    as a literal path raises, so every such file lands in the unsearchable list and the
    suite goes red on every leg because somebody committed a file with an accent in its
    name. Measured on this machine before the fix.
    """
    # The one non-ASCII literal in this module, and it is the subject rather than
    # decoration. Python 3 reads source as UTF-8 regardless of the console codepage, so
    # holding it is safe; PRINTING it is not, which is why the failure message below goes
    # through ascii() -- on a cp1252 console an unescaped accent raises UnicodeEncodeError
    # and kills the process at the write, losing the very failure it was reporting.
    accented = "café.md"
    try:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        (tmp_path / accented).write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(
            "could not build a repository with a non-ASCII filename ({!r}), so whether "
            "quoted paths are handled went untested on this platform".format(exc)
        )

    names = _tracked_files(tmp_path)

    # macOS normalises filenames to NFD on disk and git recomposes them; Linux is
    # byte-transparent. Comparing normalised forms removes that axis from the assertion,
    # which is about quoting and escaping, not about Unicode composition.
    normalised = [unicodedata.normalize("NFC", name) for name in names]
    assert unicodedata.normalize("NFC", accented) in normalised, (
        "the tracked path came back quoted and escaped rather than as the real name; "
        "got {}".format(ascii(names))
    )


def test_a_stale_exception_is_detected():
    """The drift detector needs a fixture, because the real list is empty.

    An exception list that has drifted is a licence, and a detector that has never been
    shown to fire will be believed the first time somebody adds an entry.
    """
    stale = stale_exceptions(
        {"scripts/now_used.py": "was unreferenced when this was written"},
        ["scripts/still_orphan.py"],
    )
    assert stale == ["scripts/now_used.py"], (
        "an exception naming a script that is no longer unwired must be reported as "
        "stale; got {!r}".format(stale)
    )
    assert stale_exceptions({"scripts/x.py": "why"}, ["scripts/x.py"]) == [], (
        "the positive half: an exception that is still doing its job must not be "
        "reported as stale, or the detector fires on every correct entry"
    )


# --------------------------------------------------------------------------
# The assertions themselves.
# --------------------------------------------------------------------------


def test_every_exception_is_still_needed():
    """An exception list that has drifted is a licence rather than a decision."""
    tracked = _tracked_files()
    unwired, _, _ = survey_unwired(REPO_ROOT, tracked)
    stale = stale_exceptions(UNWIRED_EXCEPTIONS, unwired)
    assert not stale, (
        "these files are listed as allowed to be unreferenced but something now "
        "references them -- drop the entry so the list keeps meaning what it says:\n  "
        + "\n  ".join(stale)
    )
    for name, reason in UNWIRED_EXCEPTIONS.items():
        assert reason and reason.strip(), "{}: an exception needs a stated reason".format(name)


def test_the_survey_actually_looked_at_something():
    """A domain that matched nothing would make the assertion below vacuous."""
    tracked = _tracked_files()
    candidates = _surveyed_paths(tracked)
    assert len(candidates) > 5, (
        "only {} tracked file(s) matched {} -- the survey is looking at almost nothing "
        "and would pass whatever the tree contained".format(len(candidates), SURVEYED_DIRS)
    )
    assert any(rel.startswith("bin/") for rel in candidates), (
        "no tracked file under bin/ was surveyed, so the extensionless entry point this "
        "domain was widened to cover is not actually being covered"
    )


def test_nothing_in_the_surveyed_directories_is_referenced_by_nothing():
    tracked = _tracked_files()
    unwired, unsearchable, absent = survey_unwired(REPO_ROOT, tracked)
    offenders = sorted(set(unwired) - set(UNWIRED_EXCEPTIONS))
    if not offenders_are_conclusive(offenders, absent):
        # #396. An absent file's references are gone rather than merely unread, so it is
        # the one thing that can *manufacture* an offender -- and between the changelog
        # fold and the release commit there are twenty-one of them at once. Accusing a
        # script here would be a red build caused by a delete nobody has committed.
        # A clean list needs no such caveat, which is why this guards the offenders
        # rather than the run: absence can only add offenders, never hide one.
        pytest.skip(
            "{} tracked file(s) are in the index and not on disk, so the reference "
            "that would clear {} may be sitting in one of them. This is what an "
            "uncommitted delete looks like. Absent: {}. Provisional offender(s): "
            "{}".format(
                len(absent),
                "them" if len(offenders) != 1 else "it",
                "; ".join("{} ({})".format(name, why) for name, why in absent),
                ", ".join(offenders),
            )
        )
    caveat = ""
    if unsearchable:
        caveat = (
            "\n\n  Note: {} tracked file(s) could not be searched, so one of these may in "
            "fact be referenced from inside one of them:\n  ".format(len(unsearchable))
            + "\n  ".join("{}: {}".format(name, why) for name, why in unsearchable)
        )
    assert not offenders, (
        "these files under {} are referenced by no other tracked file, counting neither "
        "narrative sources ({}, changelog fragments, this module) nor the "
        "[tool.coverage.run] suppression. A file no workflow, hook, test, command or "
        "document names does nothing -- and a file that does nothing is still read, and "
        "still believed. Wire it, delete it, or add it to UNWIRED_EXCEPTIONS with the "
        "reason:\n  ".format(
            "/".join(SURVEYED_DIRS), ", ".join(sorted(NARRATIVE_FILES))
        )
        + "\n  ".join(offenders)
        + caveat
    )


def test_unsearchable_files_are_surfaced_rather_than_silent():
    """The third state gets a voice without a false red.

    Decoding more files can only add references, never remove them, so an unsearchable
    file cannot turn a wired file into an unwired one -- which is why this reports
    instead of asserting. Reporting it as a skip means `-rs` prints the reason, rather
    than the fact disappearing into a green tick.
    """
    tracked = _tracked_files()
    _, unsearchable, absent = survey_unwired(REPO_ROOT, tracked)
    if unsearchable:
        pytest.skip(
            "{} tracked file(s) could not be searched, so any offender above is "
            "'unwired unless one of these mentions it': {}".format(
                len(unsearchable),
                "; ".join("{} ({})".format(name, why) for name, why in unsearchable),
            )
        )


def test_absent_files_are_surfaced_rather_than_silent():
    """#396's third state gets a voice of its own, on the ordinary green run.

    The assertion above already declines to accuse while anything is absent, but a
    skip that only happens when there are offenders would leave the usual fold-window
    tree -- twenty-one deleted fragments, no offenders -- reporting nothing at all. A
    file deleted in a diff nobody meant to make is worth saying out loud even when it
    changes no verdict, which is exactly what #395 settled for the two sites it fixed.
    """
    tracked = _tracked_files()
    _, _, absent = survey_unwired(REPO_ROOT, tracked)
    if absent:
        pytest.skip(
            "{} tracked file(s) are in the index and not on disk, so their references "
            "are lost rather than merely unread. This is what an uncommitted delete "
            "looks like -- most often the changelog fold before the release commit: "
            "{}".format(
                len(absent),
                "; ".join("{} ({})".format(name, why) for name, why in absent),
            )
        )


def test_the_vendored_coverage_gate_is_gone():
    """#253. Kept as a named regression: re-vendoring it would restore a document of
    another repository's CI claims to a directory a reader trusts."""
    assert (REPO_ROOT / "scripts" / "assemble_changelog.py").exists(), (
        "the control failed: scripts/assemble_changelog.py is missing too, so REPO_ROOT "
        "is not this repository and the assertion below would pass anywhere"
    )
    assert not (REPO_ROOT / "scripts" / "coverage_gate.py").exists(), (
        "scripts/coverage_gate.py is back. It is a vendored copy of another project's "
        "coverage gate: its floors name paths that do not exist here, and its "
        "not-enforced reasons describe that project's scripts/ directory while this "
        "repository's product code lives in ours. See issue #253"
    )


def test_pyproject_does_not_omit_a_file_that_is_gone():
    """A stale omit entry is a claim that a file exists and is deliberately unmeasured."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = OMIT_RE.search(text)
    assert block, "OMIT_RE did not match -- see test_omit_pattern_matches_the_real_pyproject"
    named = re.findall(r'"([^"]+)"', block.group(0))
    assert "scripts/assemble_changelog.py" in named, (
        "the control failed: the omit array no longer names assemble_changelog.py, so "
        "this parse is not reading what it thinks it is"
    )
    missing = sorted(name for name in named if not (REPO_ROOT / name).exists())
    assert not missing, (
        "pyproject.toml omits files that do not exist. An omit entry reads as `this file "
        "is here and deliberately unmeasured`:\n  " + "\n  ".join(missing)
    )
