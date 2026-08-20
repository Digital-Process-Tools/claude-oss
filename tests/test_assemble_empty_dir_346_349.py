"""An empty `--dir` or `--changelog` must refuse, not silently fold the cwd (#346, #349).

`_fold_target()` only asked `value is None` to decide a flag was missing, so an
*empty string* -- present, but not a directory anyone named -- passed straight
through: `missing` stayed empty, `Path('')` is `Path('.')`, and the fold quietly
scanned and would have unlinked fragments out of the current working directory.

`commands/changelog.md`'s resolver is exactly the caller that can hand this
down without meaning to (#349): it refuses on stderr and exits 1 when a
directory is unusable, but the block that captures it,
`FRAGMENTS_DIR="$(...)"`, has no exit-status check, so a reader who continues
past the refusal carries an empty `FRAGMENTS_DIR` into the fold below as
`--dir ''`.

`_gate_directories` and `changelog_dir_problem` (#343/#345) already treat an
explicit empty value as a *declared but unusable* directory, distinct from
"nothing was said" -- this is the same distinction applied at the one point
that still collapsed it: the assembler's own flag parsing. This is deliberately
not a REPO-rooted containment check (#346's other question): the module's own
docstring already establishes that `REPO`, derived by walking up from this
file for a `.git`, names the wrong repository when this copy runs from inside
the plugin, and #346 itself names this repository's own test suite as a
legitimate out-of-tree caller. A containment rule keyed to "inside REPO" would
refuse exactly the callers #346 says must keep working. Closing the empty-value
gap protects every caller, in-tree or out, without assuming anything about
where a legitimately-named directory lives.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

OK, SKIPPED, REFUSED = 0, 1, 2


def _repo(tmp_path):
    """A synthetic repo holding the real script and one valid fragment, with
    its own `.git` so `REPO`-derivation inside the copy under test never
    walks out into this checkout."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    fragments = root / "changelog.d"
    fragments.mkdir()
    (fragments / "1.fixed.md").write_text(
        "- Closes #1.\n", encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n"
        "[Unreleased]: https://example.com/o/r/compare/v0.1.0...HEAD\n",
        encoding="utf-8",
    )
    script_path = root / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    return root, script_path


def _run(script_path, cwd, *args):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_empty_dir_on_the_fold_refuses_rather_than_scanning_cwd(tmp_path):
    """The must-not-fire case: `--dir ''` must never reach `collect()`."""
    root, script_path = _repo(tmp_path)
    # A file at cwd that would parse as a fragment if the fold ever scanned
    # cwd instead of refusing -- the positive control for the harm.
    (root / "1.added.md").write_text("- would be a false catch (#1).\n", encoding="utf-8")
    result = _run(
        script_path, root,
        "--version", "0.2.0", "--date", "2026-08-20",
        "--dir", "", "--changelog", "CHANGELOG.md",
    )
    assert result.returncode == REFUSED, (result.stdout, result.stderr)
    # Pinned to the `_fold_target` refusal text specifically, not merely to
    # `refused` -- an incidental refusal from `collect()` finding an
    # unrelated file in cwd that fails to parse as a fragment would also
    # print `refused` and would be the wrong reason: it would mean the fold
    # DID scan cwd, and only happened to trip over something else there.
    assert "--dir" in result.stdout and "required and not given" in result.stdout, result.stdout
    assert (root / "1.added.md").exists(), "cwd must not have been scanned or consumed"
    assert (root / "changelog.d" / "1.fixed.md").exists(), "the real fragment dir must be untouched"
    assert "## [0.2.0]" not in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_empty_changelog_on_the_fold_also_refuses(tmp_path):
    root, script_path = _repo(tmp_path)
    result = _run(
        script_path, root,
        "--version", "0.2.0", "--date", "2026-08-20",
        "--dir", "changelog.d", "--changelog", "",
    )
    assert result.returncode == REFUSED, (result.stdout, result.stderr)
    assert (root / "changelog.d" / "1.fixed.md").exists()


def test_a_legitimate_in_tree_fold_still_works(tmp_path):
    """The must-fire control's sibling: a real `--dir`/`--changelog` pair,
    named exactly as `commands/changelog.md` names them, must still fold."""
    root, script_path = _repo(tmp_path)
    result = _run(
        script_path, root,
        "--version", "0.2.0", "--date", "2026-08-20",
        "--dir", "changelog.d", "--changelog", "CHANGELOG.md",
    )
    assert result.returncode == OK, (result.stdout, result.stderr)
    assert "## [0.2.0]" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not (root / "changelog.d" / "1.fixed.md").exists()


def test_empty_dir_on_a_read_only_mode_falls_back_to_the_derived_default(tmp_path):
    """Read-only modes never write, so an empty explicit `--dir` behaves like
    an absent one -- fall back to the derived default, not a refusal that
    would break `--check` in every managed repo whose gate passes `--dir` at
    all, matching #325/#343's own choice for the derived-default path."""
    root, script_path = _repo(tmp_path)
    result = _run(script_path, root, "--check", "--dir", "")
    assert result.returncode == OK, (result.stdout, result.stderr)


def test_empty_dir_fallback_names_itself_on_stderr(tmp_path):
    """The fallback must not be silent (audited finding on #346/#349's own
    diff): a receipt naming only fragment filenames gives a caller no way to
    tell "your --dir was honoured" from "your --dir was empty and silently
    replaced" -- exactly this repo's own defect class, an absence read as an
    absence in the world. An explicitly-empty value must say, on stderr, that
    it fell back and to what -- an absent value (the ordinary default-using
    case, covered by every other `--check` invocation in this suite) must
    not, or the note would fire on every ordinary run and stop meaning
    anything."""
    root, script_path = _repo(tmp_path)
    explicit_empty = _run(script_path, root, "--check", "--dir", "")
    assert explicit_empty.returncode == OK, (explicit_empty.stdout, explicit_empty.stderr)
    assert "--dir" in explicit_empty.stderr and "changelog.d" in explicit_empty.stderr, (
        explicit_empty.stderr
    )

    absent = _run(script_path, root, "--check")
    assert absent.returncode == OK, (absent.stdout, absent.stderr)
    assert absent.stderr == "", absent.stderr
