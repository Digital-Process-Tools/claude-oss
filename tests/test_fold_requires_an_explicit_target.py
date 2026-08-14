"""The fold path will not choose its own target (#67).

`REPO` is derived by walking up from the *script's own* location for a `.git`
(`_find_repo_root`). That derivation answers the question "which repository am
I stored in", and the fold needs the answer to "which repository am I being
released against". Those coincide for the copy vendored into a managed repo at
`.oss/assemble_changelog.py` and they do not coincide for the copy that ships
inside this plugin, whose checkout is always a clone -- so the walk always
succeeds and always on the wrong repository. The `None` arm that refuses
cleanly is unreachable in exactly the deployment where the guess is wrong.

`--check`, `--check-links` and `--count` read, so a wrong derived root costs
them a wrong answer. **The fold rewrites `CHANGELOG.md` and deletes every
fragment.** So the fold requires `--dir` and `--changelog`, unconditionally,
in both copies -- see the module docstring in the script for why the two
populations are not told apart.

Every refusal below is paired with a fold in the same fixture that *is* given
both flags and is asserted to write and to consume: an assertion that nothing
was written also passes when the harness never ran the script at all.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

OK = 0
SKIPPED = 1
REFUSED = 2

CHANGELOG = """# Changelog

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""

FRAGMENT = "67.fixed.md"


def _repo(tmp_path, script_rel_dir, name="repo"):
    """A synthetic clone holding the real script at *script_rel_dir*, one valid
    fragment and a foldable CHANGELOG.md.

    The `.git` directory is the point: it is what makes the derivation
    *succeed*, which is what makes the refusal a real refusal rather than the
    pre-existing "could not find a repository root" skip.
    """
    root = tmp_path / name
    script_dir = root / script_rel_dir
    script_dir.mkdir(parents=True)
    script_path = script_dir / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    (root / ".git").mkdir()
    (root / "changelog.d").mkdir()
    (root / "changelog.d" / FRAGMENT).write_text(
        "- The fold names its own target (#67).\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    return root, script_path


def _run(script_path, cwd, *args):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _fold(root, script_path, *extra):
    return _run(script_path, root, "--version", "0.2.0",
                "--date", "2026-08-14", *extra)


def _untouched(root):
    return ((root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG
            and (root / "changelog.d" / FRAGMENT).exists())


def _folded(root):
    return ("## [0.2.0] - 2026-08-14"
            in (root / "CHANGELOG.md").read_text(encoding="utf-8")
            and not (root / "changelog.d" / FRAGMENT).exists())


# --------------------------------------------------------------------------
# the plugin's own copy: the derivation succeeds, on the wrong repository
# --------------------------------------------------------------------------

def test_a_fold_with_neither_flag_refuses_and_writes_nothing(tmp_path):
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert _untouched(root), "the fold wrote to a target nobody named"


def test_the_same_fixture_folds_when_both_flags_are_given(tmp_path):
    """The positive control. Without it, the assertion above also passes when
    the script never ran -- a broken harness, an unspawnable interpreter, a
    fixture that built no fragment."""
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path,
                   "--dir", "changelog.d", "--changelog", "CHANGELOG.md")
    assert result.returncode == OK, result.stdout + result.stderr
    assert _folded(root), (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_the_refusal_names_both_flags_to_pass(tmp_path):
    """A destructive mode that stops without naming the two flags that would
    let the caller proceed has converted a wrong-target write into a dead
    end."""
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path)
    combined = result.stdout + result.stderr
    assert "--dir" in combined, combined
    assert "--changelog" in combined, combined
    assert "refused" in combined, combined


def test_a_fold_missing_only_dir_refuses_and_names_it(tmp_path):
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path, "--changelog", "CHANGELOG.md")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "--dir" in result.stdout + result.stderr
    assert _untouched(root)


def test_a_fold_missing_only_changelog_refuses_and_names_it(tmp_path):
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path, "--dir", "changelog.d")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "--changelog" in result.stdout + result.stderr
    assert _untouched(root)


def test_dry_run_is_still_the_fold_path_and_still_refuses(tmp_path):
    """`--dry-run` writes nothing, but it reports on a repository, and a
    report about the wrong repository is the thing a maintainer then acts
    on."""
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path, "--dry-run")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert _untouched(root)


# --------------------------------------------------------------------------
# the vendored copy: the population the decision is actually about
# --------------------------------------------------------------------------

def test_the_vendored_copy_refuses_the_same_way(tmp_path):
    """`.oss/assemble_changelog.py` sits inside the repo it operates on, so its
    derived root is right -- and it is right by a coincidence of storage, which
    is not something the script can distinguish from the plugin's copy being
    wrong for the same reason. The requirement is unconditional."""
    root, script_path = _repo(tmp_path, ".oss")
    result = _fold(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert _untouched(root)


def test_the_vendored_copy_folds_when_both_flags_are_given(tmp_path):
    root, script_path = _repo(tmp_path, ".oss")
    result = _fold(root, script_path,
                   "--dir", "changelog.d", "--changelog", "CHANGELOG.md")
    assert result.returncode == OK, result.stdout + result.stderr
    assert _folded(root)


# --------------------------------------------------------------------------
# the read-only modes keep the derived default
# --------------------------------------------------------------------------
# This repo's own CI runs `python3 scripts/assemble_changelog.py --check` with
# no flags (.github/workflows/changelog.yml), as does every scaffolded repo's
# maintainer on the command line. Requiring the flags there would break the
# gate in every managed repo at once.

def test_bare_check_still_uses_the_derived_root(tmp_path):
    root, script_path = _repo(tmp_path, "scripts")
    result = _run(script_path, root, "--check")
    assert result.returncode == OK, result.stdout + result.stderr
    assert FRAGMENT in result.stdout, result.stdout


def test_bare_count_still_uses_the_derived_root(tmp_path):
    root, script_path = _repo(tmp_path, "scripts")
    result = _run(script_path, root, "--count")
    assert result.returncode == OK, result.stdout + result.stderr
    assert result.stdout.strip() == "1", result.stdout


def test_bare_check_links_still_uses_the_derived_root(tmp_path):
    root, script_path = _repo(tmp_path, "scripts")
    result = _run(script_path, root, "--check-links")
    assert result.returncode == OK, result.stdout + result.stderr


def test_a_bare_check_from_the_vendored_depth_still_works(tmp_path):
    root, script_path = _repo(tmp_path, ".oss")
    result = _run(script_path, root, "--check")
    assert result.returncode == OK, result.stdout + result.stderr


def test_the_refusal_is_about_the_flags_not_about_a_missing_root(tmp_path):
    """A `.git` is present, so the pre-existing "could not find the repository
    root" skip must not be what fires here: that one exits SKIPPED and would
    make this suite green for the wrong reason."""
    root, script_path = _repo(tmp_path, "scripts")
    result = _fold(root, script_path)
    combined = (result.stdout + result.stderr).lower()
    assert "could not find the repository root" not in combined, combined
    assert result.returncode != SKIPPED, combined


def test_the_refusal_spells_no_path_separator(tmp_path):
    """Guard for the four Windows legs. Any example invocation in the refusal
    has to be one the reader's own shell would accept, so it names flags and
    bare relative names and composes no path at all -- a POSIX literal baked
    into the receipt reads as wrong advice on Windows, and a POSIX literal
    baked into an assertion fails there against a correct script."""
    root, script_path = _repo(tmp_path, "scripts")
    for line in _fold(root, script_path).stdout.splitlines():
        if "--dir" in line or "--changelog" in line:
            assert "changelog.d/" not in line, line
