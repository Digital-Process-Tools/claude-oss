"""The link-ref table at the bottom of CHANGELOG.md, and who maintains it.

Two releases shipped with every `## [x.y.z]` heading rendering as literal
bracketed text and `[Unreleased]` linking nowhere (#93). The audit that finds
that has existed the whole time; nothing ever called it, and a check that is
never called is indistinguishable from a check that found nothing.

Three things are pinned here, and the second is the only one that lasts:

* this repository's own CHANGELOG.md passes `--check-links`;
* the fold keeps writing the definitions -- asserted against folded output, not
  against a receipt line, and paired with the control below;
* the fold refuses instead of reporting `ok` when it could not write them, which
  is the state this repository was in for two releases.

Every "must write" case sits beside a "must refuse" case built from the same
fixture by deleting the block: an assertion that a definition appears in a file
also passes when the harness folded nothing at all, and an assertion about a
block that is entirely absent can pass vacuously depending on how it is looked
for.
"""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

OK = 0
SKIPPED = 1
REFUSED = 2

#: A repo that has released twice and carries a well-formed table. This is the
#: shape every fold after the first one meets, and the shape this repository's
#: own file should have been in since 0.1.0.
RELEASED = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- One pending entry, folded into the release being cut.

## [0.2.0] - 2026-02-02

### Added

- The second release.

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/o/r/releases/tag/v0.2.0
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""

#: The control. Identical but for the trailing block, which is exactly the state
#: this repository was in: released twice, never had a link-ref table. There is
#: no `[Unreleased]` definition to take a repository URL from, so the fold can
#: write nothing -- and must say so as a refusal rather than as `ok`.
NO_BLOCK = RELEASED[: RELEASED.index("[Unreleased]: ")].rstrip("\n") + "\n"

#: A block with definitions but no `[Unreleased]` one to advance.
NO_UNRELEASED_DEFINITION = RELEASED.replace(
    "[Unreleased]: https://github.com/o/r/compare/v0.2.0...HEAD\n", ""
)

#: `[Unreleased]` compares from a tag one release behind. The link resolves, it
#: returns a real diff, and it shows shipped work as pending -- the failure that
#: an "a definition exists" check cannot see.
STALE_UNRELEASED = RELEASED.replace("compare/v0.2.0...HEAD", "compare/v0.1.0...HEAD")

#: CRLF throughout, as a checkout on Windows without `core.autocrlf` holds it.
CRLF = RELEASED.replace("\n", "\r\n")


def _repo(tmp_path, changelog_text, name="repo"):
    """A synthetic repo holding the real script and one valid fragment."""
    root = tmp_path / name
    (root / ".oss").mkdir(parents=True)
    (root / ".git").mkdir()
    script_path = root / ".oss" / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    fragments = root / "changelog.d"
    fragments.mkdir()
    (fragments / "93.fixed.md").write_text(
        "- The link-ref table is maintained by the fold (#93).\n",
        encoding="utf-8",
    )
    # Bytes, not text: the point of the CRLF fixture is the bytes on disk, and
    # text mode would rewrite them to the platform's own ending on the way in.
    (root / "CHANGELOG.md").write_bytes(changelog_text.encode("utf-8"))
    return root, script_path


def _run(root, script_path, *args):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def _fold(root, script_path, *extra, version="0.3.0"):
    return _run(
        root,
        script_path,
        "--version",
        version,
        "--date",
        "2026-08-14",
        "--dir",
        "changelog.d",
        "--changelog",
        "CHANGELOG.md",
        *extra,
    )


def _check_links(root, script_path):
    return _run(
        root,
        script_path,
        "--check-links",
        "--dir",
        "changelog.d",
        "--changelog",
        "CHANGELOG.md",
    )


def _changelog(root):
    return (root / "CHANGELOG.md").read_bytes().decode("utf-8")


# ---------------------------------------------------------------------------
# This repository's own file
# ---------------------------------------------------------------------------


def _workflow_check_links_arguments():
    """The `--check-links` invocation CI runs, taken out of the workflow.

    Read rather than restated. A copy of the arguments written here could drift
    from the workflow's, and then the local test and the leg would be auditing
    the file under two different declarations while both reported `ok`.
    """
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "--check-links" not in stripped:
                continue
            _, _, tail = stripped.partition("assemble_changelog.py")
            found.append((path.name, shlex.split(tail)))
    return found


def test_the_pull_request_gate_invokes_check_links():
    """The audit ran on nothing for two releases because no leg called it. A
    flag that exists and is never invoked reports what a clean file reports."""
    names = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
    assert names, "no workflows found -- this assertion cannot see anything"
    callers = _workflow_check_links_arguments()
    assert callers, (
        "no workflow in .github/workflows runs `--check-links` on this "
        "repository's CHANGELOG.md: " + ", ".join(names)
    )


def test_this_repositorys_changelog_passes_the_check_ci_runs():
    """The file we publish, audited with the workflow's own arguments and from
    the repository root, which is where CI runs it and what the derivation of
    `--dir`/`--changelog` is being trusted to resolve."""
    for name, arguments in _workflow_check_links_arguments():
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == OK, name + ": " + result.stdout + result.stderr
        assert result.stdout.startswith("assemble    : ok"), result.stdout


def test_the_untagged_declaration_is_what_makes_it_pass():
    """The control for the test above. Without the declaration the audit fires
    on 0.1.0 -- so `ok` above is the declaration being honoured, not the audit
    finding nothing to say about a version that was never tagged."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--check-links",
            "--dir",
            "changelog.d",
            "--changelog",
            "CHANGELOG.md",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "`## [0.1.0]` has no link ref" in result.stdout, result.stdout
    # And the tagged one is not swept up in the same silence.
    assert "0.2.0" not in result.stdout, result.stdout


def test_an_untagged_version_that_is_not_x_y_z_is_refused_not_dropped(tmp_path):
    """A typo in the declaration must not read as a version that was declared:
    the audit would report a finding the maintainer has already answered."""
    root, script_path = _repo(tmp_path, RELEASED)
    result = _run(
        root,
        script_path,
        "--check-links",
        "--untagged",
        "0.1",
        "--dir",
        "changelog.d",
        "--changelog",
        "CHANGELOG.md",
    )
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "is not x.y.z" in result.stdout, result.stdout


def test_untagged_is_refused_by_the_modes_that_do_not_read_it(tmp_path):
    """It is read by `--check-links` and nothing else. Accepted silently on the
    fold, a declaration that never applied would be indistinguishable from one
    that was honoured -- including a value `--check-links` would have refused."""
    root, script_path = _repo(tmp_path, RELEASED)
    folded = _fold(root, script_path, "--untagged", "0.1.0", "--dry-run")
    assert folded.returncode == REFUSED, folded.stdout + folded.stderr
    assert "--check-links" in folded.stdout, folded.stdout
    counted = _run(
        root, script_path, "--count", "--untagged", "0.1.0", "--dir", "changelog.d"
    )
    assert counted.returncode == REFUSED, counted.stdout + counted.stderr
    # The positive control: the same two runs without the flag do their job.
    assert _fold(root, script_path, "--dry-run").returncode == OK
    plain = _run(root, script_path, "--count", "--dir", "changelog.d")
    assert plain.returncode == OK and plain.stdout.strip() == "1", plain.stdout


def test_the_refusal_says_replace_when_a_definition_is_already_there(tmp_path):
    """A second `[Unreleased]:` definition beside the first is not an error any
    parse reports: the reference resolves to whichever is read first, so the
    file carries two answers and shows one. The remedy has to say which."""
    root, script_path = _repo(
        tmp_path,
        RELEASED.replace(
            "[Unreleased]: https://github.com/o/r/compare/v0.2.0...HEAD",
            "[Unreleased]: https://github.com/o/r/commits/HEAD",
        ),
    )
    result = _fold(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "replace" in result.stdout, result.stdout
    assert "commits/HEAD" in result.stdout, result.stdout
    # The control: the branch with no definition at all still says "add".
    absent = _repo(tmp_path, NO_UNRELEASED_DEFINITION, name="absent")
    other = _fold(*absent).stdout
    assert "add " in other and "replace" not in other, other


def test_a_declaration_for_a_version_that_has_a_link_ref_is_a_finding(tmp_path):
    """`--untagged` is a declaration, not a mute button: a version declared
    untagged that carries a `releases/tag/v...` link is two statements that
    cannot both be true, and the link is the one that 404s."""
    root, script_path = _repo(tmp_path, RELEASED)
    result = _run(
        root,
        script_path,
        "--check-links",
        "--untagged",
        "0.2.0",
        "--dir",
        "changelog.d",
        "--changelog",
        "CHANGELOG.md",
    )
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "declared as never tagged but has a link ref" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# What the fold does to the table
# ---------------------------------------------------------------------------


def test_the_fold_writes_the_new_releases_link_ref_and_advances_unreleased(tmp_path):
    """Asserted on the folded file, not on the receipt: a receipt line saying
    `links ...` is the tool describing itself."""
    root, script_path = _repo(tmp_path, RELEASED)
    result = _fold(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr
    text = _changelog(root)
    assert "## [0.3.0] - 2026-08-14" in text, text
    assert "[0.3.0]: https://github.com/o/r/releases/tag/v0.3.0" in text, text
    assert "[Unreleased]: https://github.com/o/r/compare/v0.3.0...HEAD" in text, text
    assert "compare/v0.2.0...HEAD" not in text, text
    # The older definitions are kept, not replaced.
    assert "[0.2.0]: https://github.com/o/r/releases/tag/v0.2.0" in text, text
    assert "[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0" in text, text


def test_the_folded_file_passes_check_links_immediately(tmp_path):
    """The end-to-end form of the above: the release the fold cuts must not
    acquire a finding at birth, which is how 0.1.0 and 0.2.0 did."""
    root, script_path = _repo(tmp_path, RELEASED)
    assert _fold(root, script_path).returncode == OK
    audit = _check_links(root, script_path)
    assert audit.returncode == OK, audit.stdout + audit.stderr
    assert audit.stdout.startswith("assemble    : ok"), audit.stdout


def test_the_fold_refuses_when_it_cannot_write_the_link_refs(tmp_path):
    """The control for both tests above. With the block deleted there is no
    repository URL to write a definition from, so the fold would add a fourth
    heading that renders as literal bracketed text -- and used to do exactly
    that under an `ok` receipt reading `links none ... left alone`."""
    root, script_path = _repo(tmp_path, NO_BLOCK)
    result = _fold(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "refused" in result.stdout, result.stdout
    assert "0.3.0" in result.stdout, result.stdout
    # Nothing moved: the changelog is untouched and the fragment is still there.
    assert _changelog(root) == NO_BLOCK
    assert (root / "changelog.d" / "93.fixed.md").exists()


def test_the_refusal_names_which_of_the_states_it_found(tmp_path):
    """Three different files reach `could not write the link refs`, and a
    maintainer fixes each of them differently."""
    no_block, block_script = _repo(tmp_path, NO_BLOCK, name="a")
    no_definition, definition_script = _repo(
        tmp_path, NO_UNRELEASED_DEFINITION, name="b"
    )

    first = _fold(no_block, block_script).stdout
    second = _fold(no_definition, definition_script).stdout
    assert first != second, first
    assert "no trailing link-reference block" in first, first
    assert "`[Unreleased]:`" in second, second


def test_the_dry_run_refuses_on_the_same_file_the_fold_would(tmp_path):
    """A dry run reporting `ok` on a file the real fold refuses is a rehearsal
    of a different release."""
    root, script_path = _repo(tmp_path, NO_BLOCK)
    assert _fold(root, script_path, "--dry-run").returncode == REFUSED


# ---------------------------------------------------------------------------
# What the check can and cannot see
# ---------------------------------------------------------------------------


def test_check_links_sees_an_unreleased_that_is_a_release_behind(tmp_path):
    """The interesting half. `[Unreleased]` here has a definition, it resolves,
    and it returns a real diff -- showing everything in 0.2.0 as unreleased. A
    check asserting only that a definition exists passes on this file."""
    root, script_path = _repo(tmp_path, STALE_UNRELEASED)
    result = _check_links(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "compares from v0.1.0" in result.stdout, result.stdout
    assert "[0.2.0]" in result.stdout, result.stdout


def test_check_links_passes_the_same_fixture_once_unreleased_is_current(tmp_path):
    """The positive control for the test above: same file, one URL corrected.
    Without it, a refusal for any other reason would read as that finding."""
    root, script_path = _repo(tmp_path, RELEASED)
    result = _check_links(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Line endings
# ---------------------------------------------------------------------------


def test_the_fold_keeps_the_line_endings_it_found(tmp_path):
    """A whole-file ending flip is a diff of every line, and it is invisible in
    review. `read_text` normalises CRLF to LF on the way in, so the fold rewrote
    a CRLF changelog as LF on every platform -- and, in text mode, would rewrite
    an LF changelog as CRLF on Windows."""
    crlf_root, crlf_script = _repo(tmp_path, CRLF, name="crlf")
    lf_root, lf_script = _repo(tmp_path, RELEASED, name="lf")

    assert _fold(crlf_root, crlf_script).returncode == OK
    assert _fold(lf_root, lf_script).returncode == OK

    crlf_bytes = (crlf_root / "CHANGELOG.md").read_bytes()
    lf_bytes = (lf_root / "CHANGELOG.md").read_bytes()
    assert b"0.3.0" in crlf_bytes and b"0.3.0" in lf_bytes, (
        "neither file was folded -- this test can see nothing"
    )
    assert b"\r\n" in crlf_bytes, "a CRLF changelog was rewritten with LF endings"
    assert crlf_bytes.count(b"\n") == crlf_bytes.count(b"\r\n"), (
        "the CRLF changelog came back with mixed endings"
    )
    assert b"\r" not in lf_bytes, "an LF changelog was rewritten with CRLF endings"
