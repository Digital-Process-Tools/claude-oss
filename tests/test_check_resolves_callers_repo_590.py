"""#590: a bare `--check`/`--count`/`--check-links` must answer about the
*caller's* repository, never about the tree the script happens to be
installed in.

`REPO` used to be derived by walking up from `__file__` -- correct for the
copy vendored beside the repo it serves (`.oss/assemble_changelog.py`), and
wrong for the copy shipped inside a plugin, whose own checkout is a clone
unrelated to whatever repository the caller meant. That walk always
succeeded, on the plugin's own tree, so a caller standing anywhere else got a
clean `ok` about fragments that were never theirs.

These tests copy the real script into a "vendor" tree that stands in for the
plugin's install location, then invoke it with the *caller's* cwd pointed at
a second, unrelated tree -- the composition these tests exist to pin, not a
unit fact about `_find_repo_root` in isolation.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"


def _make_repo(root, fragment_name, fragment_body):
    """A minimal repo: `.git` marker plus one changelog fragment."""
    (root / ".git").mkdir(parents=True)
    frag_dir = root / "changelog.d"
    frag_dir.mkdir()
    (frag_dir / fragment_name).write_text(fragment_body, encoding="utf-8")


def _run(script_path, cwd, *args):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_bare_check_from_a_different_repo_never_answers_about_the_vendor_tree(tmp_path):
    """The composition control: cwd is a real repository that is not the one
    the script is stored in. The receipt must not name the vendor's own
    fragment -- and, paired in the same run, a correctly-invoked call (cwd
    genuinely inside a repo) must still resolve and answer about *that*
    repo's own fragment, not go silent."""
    vendor = tmp_path / "a" / "vendor"
    script_dir = vendor / "b" / "scripts"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    (vendor / ".git").mkdir()
    (vendor / "changelog.d").mkdir()
    (vendor / "changelog.d" / "1.added.md").write_text(
        "- adds a vendor-only thing (#1)\n", encoding="utf-8")

    caller = tmp_path / "c" / "caller"
    _make_repo(caller, "2.fixed.md", "- fixes a caller-owned thing (#2)\n")

    result = _run(script_path, caller, "--check")
    combined = result.stdout + result.stderr

    # Must never surface the vendor's own fragment name.
    assert "1.added.md" not in combined
    # Positive control: it did resolve, and it resolved the caller's own tree.
    assert "2.fixed.md" in combined
    assert result.returncode == 0


def test_bare_check_outside_any_repository_refuses_rather_than_answering_for_the_vendor(tmp_path):
    """No `.git` anywhere above the caller's cwd: must say so, never fall
    back to the script's own install tree."""
    vendor = tmp_path / "d" / "vendor"
    script_dir = vendor / "e" / "scripts"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    (vendor / ".git").mkdir()
    (vendor / "changelog.d").mkdir()
    (vendor / "changelog.d" / "1.added.md").write_text(
        "- adds a vendor-only thing (#1)\n", encoding="utf-8")

    orphan = tmp_path / "f" / "orphan"
    orphan.mkdir(parents=True)
    # Deliberately no .git anywhere under tmp_path / "f".

    result = _run(script_path, orphan, "--check")
    combined = (result.stdout + result.stderr)

    assert "1.added.md" not in combined
    assert result.returncode != 0
    lowered = combined.lower()
    assert "could not find" in lowered or "repository root" in lowered
