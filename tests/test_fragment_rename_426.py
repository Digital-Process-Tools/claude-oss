"""#426: the maintainer half of #335. A fragment renamed when a pull request opens
(`git mv changelog.d/N.section.md changelog.d/M.section.md`) leaves the body still
naming the old number, and the fold consumes the filename -- so the same
`fragment` leg that refuses a lane's #274-shaped fragment refuses the
maintainer's rename too. Measured on PR #338, recorded in #335's comment.

#335 argued the rename should not stay a manual step: the number a fragment is
keyed to (the pull request's own number) does not exist until the pull request
is open, so the rename and the body rewrite are coupled and neither half is
correct alone. `scripts/rename_changelog_fragment.py` performs both in one
operation and refuses rather than leaving a fragment `--check` would reject.

This file drives it against a real git repo with a real fragment: the rename
must move the number in the body along with the filename, paired with a
control on an already-correct fragment (must be left alone, not rewritten) and
a control on a fragment that never named itself even before the rename (must
refuse rather than silently produce another broken fragment).
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSEMBLER = REPO_ROOT / "scripts" / "assemble_changelog.py"
RENAMER = REPO_ROOT / "scripts" / "rename_changelog_fragment.py"
LANE_SETUP = REPO_ROOT / "scripts" / "lane_setup.py"
OSS_CONFIG = REPO_ROOT / "scripts" / "oss_config.py"

OK, REFUSED = 0, 3


def _vendor(tmp_path):
    """A synthetic repo with its own .git and changelog.d/, carrying copies of
    both scripts at the same relative layout as this repo -- the renamer
    imports the assembler as a sibling module in scripts/, so both have to be
    copied together for that import to resolve."""
    root = tmp_path / "vendor"
    script_dir = root / "scripts"
    script_dir.mkdir(parents=True)
    shutil.copy(ASSEMBLER, script_dir / "assemble_changelog.py")
    shutil.copy(RENAMER, script_dir / "rename_changelog_fragment.py")
    # #444: the renamer now confirms absence via lane_setup._absence_confirmed,
    # which imports oss_config -- both stdlib-only, so vendored alongside it.
    shutil.copy(LANE_SETUP, script_dir / "lane_setup.py")
    shutil.copy(OSS_CONFIG, script_dir / "oss_config.py")
    (root / "changelog.d").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    return root, script_dir / "rename_changelog_fragment.py"


def _commit_fragment(root, name, body):
    frag = root / "changelog.d" / name
    frag.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add fragment"], cwd=str(root), check=True)
    return frag


def _check(root):
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "assemble_changelog.py"), "--check"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def _rename(script_path, root, fragment_rel, new_issue):
    return subprocess.run(
        [sys.executable, str(script_path), fragment_rel, str(new_issue)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def test_rename_moves_the_self_reference_with_the_filename(tmp_path):
    root, script_path = _vendor(tmp_path)
    _commit_fragment(root, "338.fixed.md", "- Fixed the thing (#338).\n")

    before = _check(root)
    assert before.returncode == OK, (before.stdout, before.stderr)

    result = _rename(script_path, root, "changelog.d/338.fixed.md", 425)
    assert result.returncode == OK, (result.stdout, result.stderr)

    old = root / "changelog.d" / "338.fixed.md"
    new = root / "changelog.d" / "425.fixed.md"
    assert not old.exists(), "the old filename must be gone once the rename ran"
    assert new.exists(), "the renamed fragment must exist under the new number"
    text = new.read_text(encoding="utf-8")
    assert "#425" in text, "the body must be rewritten to name the new number"
    assert "#338" not in text, "the old self-reference must not survive the rename"

    after = _check(root)
    assert after.returncode == OK, (
        "renamed fragment still fails --check -- the rewrite did not follow the rename",
        after.stdout,
        after.stderr,
    )

    # `git mv` alone stages the pre-rewrite bytes; the rewrite happens on disk
    # afterwards, so it must also be staged, or `git commit --amend` (no `-a`,
    # the instruction skills/manager/SKILL.md gives) would commit the OLD body
    # under the NEW filename -- the exact defect this tool exists to close,
    # one layer later.
    unstaged = subprocess.run(
        ["git", "diff", "--", "changelog.d/425.fixed.md"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert unstaged.stdout == "", (
        "the rewritten body was not staged -- an amend without an explicit "
        "`git add` would commit the pre-rewrite text",
        unstaged.stdout,
    )


def test_rename_refuses_when_the_body_never_named_the_old_issue(tmp_path):
    """Control on the failure path: a fragment that never named its own issue
    even before the rename has nothing for the tool to move -- it must refuse
    rather than silently produce a renamed fragment `--check` would still
    reject, which is the exact failure #335 and #426 are about."""
    root, script_path = _vendor(tmp_path)
    _commit_fragment(root, "338.fixed.md", "- Fixed the thing.\n")

    result = _rename(script_path, root, "changelog.d/338.fixed.md", 425)
    assert result.returncode == REFUSED, (result.stdout, result.stderr)
    assert "#425" in result.stdout or "#425" in result.stderr


def test_rename_leaves_an_already_correct_fragment_alone(tmp_path):
    """Positive control: renaming to the number a fragment already carries
    must be a no-op rather than a refusal or a rewrite that could corrupt a
    fragment that was already fine."""
    root, script_path = _vendor(tmp_path)
    _commit_fragment(root, "425.fixed.md", "- Fixed the thing (#425).\n")

    before_text = (root / "changelog.d" / "425.fixed.md").read_text(encoding="utf-8")
    result = _rename(script_path, root, "changelog.d/425.fixed.md", 425)
    assert result.returncode == OK, (result.stdout, result.stderr)
    after_text = (root / "changelog.d" / "425.fixed.md").read_text(encoding="utf-8")
    assert after_text == before_text, "an already-correct fragment must not be rewritten"
