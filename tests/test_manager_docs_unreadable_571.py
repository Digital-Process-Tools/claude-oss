"""#571: `manager_docs.documents()` silently narrowed to `[SPINE]` when the
phases directory could not be read, because `Path.glob` swallows
`PermissionError` while it walks and yields nothing for the subtree it could
not enter -- the same swallow CLAUDE.md's own `Path.rglob`/`Path.is_dir`
bullet (#124/#383) already documents, and the same one
`doctor._workflow_scan`/`_rglob_md` already solves for a directory listing by
using an operation that can actually report a deny.

Every content guard built on `documents()` -- `MANAGER_DOC_PATHS` in
`tests/test_content_invariants.py` chief among them -- would then silently
sweep one file instead of seven, with nothing raised and nothing warned. This
pins the fix: `documents()` now returns `(paths, unreadable)`, and an
unreadable phases directory is reported in the second element rather than
folded into an empty-looking first one.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import manager_docs  # noqa: E402


def _fixture_tree(tmp_path):
    """A real spine plus a real, readable phases directory with two files --
    the positive control this fixture pairs with the deny case.
    """
    root = tmp_path / "repo"
    skill_dir = root / "skills" / "manager"
    phases_dir = skill_dir / "phases"
    phases_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("the spine", encoding="utf-8")
    (phases_dir / "dispatch.md").write_text("dispatch phase", encoding="utf-8")
    (phases_dir / "review.md").write_text("review phase", encoding="utf-8")
    return root, phases_dir


def test_readable_tree_reports_every_document_positive_control(tmp_path):
    """Paired positive control: a healthy tree must report the whole set and
    an empty `unreadable`, or the deny case below would prove nothing -- a
    "reports the gap" assertion that passes when nothing happens at all is
    the exact failure this fixture is built to rule out.
    """
    root, _phases_dir = _fixture_tree(tmp_path)

    paths, unreadable = manager_docs.documents(root)

    assert unreadable == []
    assert [p.name for p in paths] == ["SKILL.md", "dispatch.md", "review.md"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows chmod does not deny a directory listing the way this fixture needs")
def test_unreadable_phases_directory_is_reported_not_silently_narrowed(tmp_path):
    """The deny case. Confirmed by attempting the exact operation the code
    under test performs -- `iterdir()` on the phases directory -- before
    trusting the fixture at all: root ignores the mode bit, and some
    filesystems ignore it too, so the fixture is a measurement, not a given.
    """
    root, phases_dir = _fixture_tree(tmp_path)
    original_mode = phases_dir.stat().st_mode
    os.chmod(phases_dir, 0)
    try:
        try:
            list(phases_dir.iterdir())
        except PermissionError as exc:
            errno_seen = exc.errno
        else:
            pytest.skip(
                "chmod 000 did not deny iterdir() on this filesystem/user -- "
                "running as root or a filesystem that ignores the mode bit; "
                "the deny path went untested here"
            )

        paths, unreadable = manager_docs.documents(root)

        assert unreadable, (
            "iterdir() confirmed the deny (errno {0}) but documents() reported "
            "no unreadable directory".format(errno_seen)
        )
        assert [p.name for p in paths] == ["SKILL.md"], (
            "the spine must still be reported even when the phases directory "
            "cannot be read"
        )
    finally:
        os.chmod(phases_dir, original_mode)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows chmod does not deny a directory listing the way this fixture needs")
def test_text_raises_rather_than_silently_narrowing(tmp_path):
    """Self-review finding on the #571 round: `text()` and `ManagerLoop`
    used to discard `unreadable` and concatenate the narrowed set anyway --
    reopening the identical defect one call further down, for every content
    check that reads through `ManagerLoop` instead of calling `documents()`
    directly. Paired with the positive control below.
    """
    root, phases_dir = _fixture_tree(tmp_path)
    original_mode = phases_dir.stat().st_mode
    os.chmod(phases_dir, 0)
    try:
        try:
            list(phases_dir.iterdir())
        except PermissionError:
            pass
        else:
            pytest.skip(
                "chmod 000 did not deny iterdir() on this filesystem/user -- "
                "the deny path went untested here"
            )

        with pytest.raises(RuntimeError):
            manager_docs.text(root)

        loop = manager_docs.ManagerLoop(root)
        with pytest.raises(RuntimeError):
            loop.read_text()
        with pytest.raises(RuntimeError):
            loop.paths
    finally:
        os.chmod(phases_dir, original_mode)


def test_text_and_manager_loop_succeed_on_a_readable_tree_positive_control(tmp_path):
    """Positive control for the case above: a healthy tree must not raise."""
    root, _phases_dir = _fixture_tree(tmp_path)

    joined = manager_docs.text(root)
    assert "dispatch phase" in joined and "review phase" in joined

    loop = manager_docs.ManagerLoop(root)
    assert "dispatch phase" in loop.read_text()
    assert len(loop.paths) == 3
