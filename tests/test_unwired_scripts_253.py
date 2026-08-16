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
anything uses them. `assemble_changelog.py` is mentioned by 33 tracked files -- as
counted by `survey_unwired` below, not by a shell `git grep`, whose unescaped `.`
is a wildcard and answered 34 -- and it ships into every scaffolded repo.
`coverage_gate.py` was referenced by one file, and that one reference existed only
to exclude it from measurement. Hence the rule below, and hence the two kinds of
reference that do not count as a use:

* **History.** `CHANGELOG.md` is append-only. A file deleted today is named there
  forever, so counting it would make this check permanently unable to fire.
* **A suppression.** The whole `[tool.coverage.run]` section says "here is what we
  do not measure, and why". That is a statement about a file's absence from the
  gate, not a use of it. Counting it would let a file justify its own presence by
  being excluded -- which is exactly the shape `coverage_gate.py` had. The section
  and not merely its `omit` array, because the first version of this check blanked
  the array alone and then passed on the real tree: `coverage_gate.py`'s single
  surviving reference was the *comment* four lines above the array, explaining why
  it was omitted. A prose suppression is still a suppression.

Three states, not two. `git ls-files` failing, or returning nothing, is *unknown*
and skips with the reason; it is not a pass. Files that cannot be decoded come back
separately from files that were read and did not match, because "nobody mentions
this script" and "we could not read the files that would have" are different
answers and must not render alike.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Append-only history. See the module docstring: a deleted file is named here forever.
HISTORY_FILES = frozenset({"CHANGELOG.md"})

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

_SCRIPT_SUFFIXES = (".py", ".sh")


def _mention_re(name):
    """A reference to `name`, not merely the characters of `name` inside a longer word.

    `state.py` is a substring of `oss_state.py`, so a bare `in` reports an orphan as
    wired the moment its basename is a suffix of another file's -- the check answering
    confidently about a file it never looked at. The left boundary excludes `.` and `-`
    as well as word characters, so neither `oss_state.py` nor `a-state.py` counts as a
    mention of `state.py`; the right boundary is a plain word boundary, since what
    follows a real reference is a quote, a backtick, a slash or whitespace.
    """
    return re.compile(r"(?<![\w.\-])" + re.escape(name) + r"(?!\w)")


def _script_paths(tracked):
    return sorted(
        rel
        for rel in tracked
        if rel.startswith("scripts/") and rel.endswith(_SCRIPT_SUFFIXES)
    )


def _searchable_text(root, rel):
    """The text of one tracked file with suppression regions blanked, or None if unreadable.

    None is the third state and is propagated, never folded into "did not match".
    """
    try:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if rel == "pyproject.toml" or rel.endswith("/pyproject.toml"):
        text = COVERAGE_RUN_RE.sub("[tool.coverage.run]\n", text)
    return text


def survey_unwired(root, tracked):
    """Return (unwired, unreadable) for the scripts in `tracked`.

    Two lists rather than one verdict: a script nothing mentions and a tree we could
    not finish reading are different findings, and one of them is not a finding at all.
    """
    scripts = _script_paths(tracked)
    unreadable = []
    texts = {}
    for rel in tracked:
        if rel in HISTORY_FILES:
            continue
        text = _searchable_text(root, rel)
        if text is None:
            unreadable.append(rel)
            continue
        texts[rel] = text

    unwired = []
    for rel in scripts:
        mention = _mention_re(rel.rsplit("/", 1)[-1])
        if any(other != rel and mention.search(body) for other, body in texts.items()):
            continue
        unwired.append(rel)
    return unwired, sorted(unreadable)


def _tracked_files():
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
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
        line
        for line in completed.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
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

    unwired, unreadable = survey_unwired(tmp_path, tracked)

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

    unwired, unreadable = survey_unwired(tmp_path, tracked)

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
    """A file we could not read must not be silently counted as one that did not match."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orphan.py").write_text("print(2)\n", encoding="utf-8")
    tracked = ["scripts/orphan.py", "vanished.py"]

    unwired, unreadable = survey_unwired(tmp_path, tracked)

    assert unreadable == ["vanished.py"], (
        "an unreadable tracked file must come back in its own list, not folded into "
        "the clean path; got {!r}".format(unreadable)
    )
    assert unwired == ["scripts/orphan.py"]


# --------------------------------------------------------------------------
# The assertions themselves.
# --------------------------------------------------------------------------


def test_every_exception_is_still_needed():
    """An exception list that has drifted is a licence rather than a decision."""
    tracked = _tracked_files()
    unwired, _ = survey_unwired(REPO_ROOT, tracked)
    stale = sorted(set(UNWIRED_EXCEPTIONS) - set(unwired))
    assert not stale, (
        "these scripts are listed as allowed to be unreferenced but something now "
        "references them -- drop the entry so the list keeps meaning what it says:\n  "
        + "\n  ".join(stale)
    )
    for name, reason in UNWIRED_EXCEPTIONS.items():
        assert reason and reason.strip(), "{}: an exception needs a stated reason".format(name)


def test_no_script_is_referenced_by_nothing():
    tracked = _tracked_files()
    unwired, unreadable = survey_unwired(REPO_ROOT, tracked)
    assert not unreadable, (
        "could not read {} tracked file(s), so a script referenced only by one of them "
        "would read as unreferenced below. Fix the read before trusting the "
        "verdict:\n  ".format(len(unreadable)) + "\n  ".join(unreadable)
    )
    offenders = sorted(set(unwired) - set(UNWIRED_EXCEPTIONS))
    assert not offenders, (
        "these scripts are referenced by no other tracked file. A script no workflow, "
        "hook, test or document names does nothing -- and a file that does nothing is "
        "still read, and still believed. Wire it, delete it, or add it to "
        "UNWIRED_EXCEPTIONS with the reason:\n  " + "\n  ".join(offenders)
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
