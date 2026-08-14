"""The default --dir/--changelog derivation (#20).

`REPO` used to be `Path(__file__).resolve().parents[2]` -- right for a script
living two directories below the repo root (`.github/scripts/`), wrong for
one living one directory below it (`scripts/`, where it actually lives), and
wrong again at whatever depth it lands when vendored into a scaffolded repo
as `.oss/assemble_changelog.py`.

These tests copy the real script to a synthetic location and run it as a
subprocess, so the default is computed fresh from *that* copy's `__file__`
-- pinning behaviour from a location that is not this repo's root, which a
plain `import` of the already-loaded module could not exercise (the module
is already imported once, from the real location).
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"


def _vendor(tmp_path, script_rel_dir, name="vendor", git_marker="dir"):
    """Copy the real script to *tmp_path*/*name*/*script_rel_dir*, with its
    own `.git` marker and an empty `changelog.d/`. Returns (root, script_path)."""
    root = tmp_path / name
    script_dir = root / script_rel_dir
    script_dir.mkdir(parents=True)
    script_path = script_dir / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    if git_marker == "dir":
        (root / ".git").mkdir()
    elif git_marker == "file":
        (root / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/x\n", encoding="utf-8")
    (root / "changelog.d").mkdir()
    return root, script_path


def _run(script_path, cwd, *args):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_bare_check_from_the_repo_it_lives_in_finds_its_own_fragments(tmp_path):
    """The script sits at `<root>/scripts/`. From that root, `--check` with
    no `--dir`/`--changelog` must resolve `changelog.d` against *that* root,
    not against its parent."""
    root, script_path = _vendor(tmp_path, "scripts")
    result = _run(script_path, root, "--check")
    assert "does not exist" not in result.stdout
    # No fragments were placed: an empty directory is `ok` (nothing to
    # validate), never a missing-directory finding.
    assert result.returncode in (0, 1)


def test_bare_check_from_a_worktree_does_not_concatenate_paths(tmp_path):
    """A git worktree's `.git` is a *file* (`gitdir: ...`), not a directory.
    The known reproduction from a worktree checkout produced a concatenated
    relative-plus-absolute path in the finding text; assert that string
    shape can no longer appear."""
    root, script_path = _vendor(tmp_path, "scripts", git_marker="file")
    result = _run(script_path, root, "--check")
    assert "changelog.d//" not in result.stdout
    assert "does not exist" not in result.stdout


def test_bare_check_run_from_a_subdirectory_still_uses_the_scripts_own_location(tmp_path):
    """The default must come from where the script *lives*, not from the
    caller's current working directory."""
    root, script_path = _vendor(tmp_path, "scripts")
    (root / "sub").mkdir()
    result = _run(script_path, root / "sub", "--check")
    assert "does not exist" not in result.stdout


def test_vendored_at_a_different_depth_still_resolves_its_own_root(tmp_path):
    """Vendored into a scaffolded repo as `.oss/assemble_changelog.py` --
    one directory shallower than `scripts/`. A fix that hardcodes a new
    parent count is the same bug with a different number; this must pass
    without editing REPO's derivation for this depth."""
    root, script_path = _vendor(tmp_path, ".oss")
    result = _run(script_path, root, "--check")
    assert "does not exist" not in result.stdout
    assert result.returncode in (0, 1)


def test_no_git_above_the_script_is_named_not_guessed(tmp_path):
    """No `.git` anywhere above the script: the tool must say it could not
    find the repository root, not compose a path out of a guess and fail
    on that instead."""
    root = tmp_path / "orphan"
    script_dir = root / "scripts"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    # Deliberately no `.git` anywhere under tmp_path.

    result = _run(script_path, root, "--check")
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "could not find" in combined or "repository root" in combined
    assert "does not exist" not in combined
