"""#589: `_undeclared_rows()` in `scripts/skill_phases.py` caught
`(RuntimeError, OSError)` around its call to `manager_docs.documents()` and
returned `[]` -- folding the `unreadable` state the module docstring six
lines above promises to preserve (#571's own fix, one function over) into
the same shape as "no undeclared files found". Guard and bypass in one
function.

The release-gate audit that filed this issue could not demonstrate a live
route to the bypass at HEAD: `documents()` already catches `OSError` around
its own `iterdir()` and returns it via the `unreadable` list rather than
raising, and a `RuntimeError` (unreadable spine) would already surface from
`check()`'s own `read_bytes()` call before `_undeclared_rows()` is ever
reached. So this fixture drives `_undeclared_rows()` directly and forces
`documents()` to raise via monkeypatch -- the auditor's own three-arm
control: a healthy tree (arm 1, the positive control), `documents()` raising
`PermissionError` (arm 2, proving the catch destroys the state), and
`documents()` returning a real `unreadable` message (arm 3, proving the
state is reachable once it is not swallowed).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import skill_phases  # noqa: E402


def _fixture_tree(tmp_path):
    root = tmp_path / "repo"
    skill_dir = root / "skills" / "manager"
    phases_dir = skill_dir / "phases"
    phases_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("the spine", encoding="utf-8")
    (phases_dir / "dispatch.md").write_text("dispatch phase", encoding="utf-8")
    return root, phases_dir


def test_healthy_tree_reports_undeclared_rows_positive_control(tmp_path):
    """Arm 1. A tree with an undeclared phase file must report it as an
    `undeclared` row, or the arms below prove nothing about the fold."""
    root, phases_dir = _fixture_tree(tmp_path)
    (phases_dir / "surprise.md").write_text("not in DOCUMENTS", encoding="utf-8")

    rows = skill_phases._undeclared_rows(root)

    assert any(r["path"] == "skills/manager/phases/surprise.md" and r["state"] == "undeclared" for r in rows)


def test_documents_raising_permission_error_is_not_folded_to_empty(tmp_path, monkeypatch):
    """Arm 2. When `documents()` raises `PermissionError` (an `OSError`
    subclass), `_undeclared_rows()` must report it as `unreadable`, not
    silently return `[]` -- the fold this issue is about.
    """
    root, _phases_dir = _fixture_tree(tmp_path)

    def _raise(_root):
        raise PermissionError("simulated: phases directory could not be read")

    monkeypatch.setattr(skill_phases, "documents", _raise)

    rows = skill_phases._undeclared_rows(root)

    assert rows, (
        "documents() raised PermissionError but _undeclared_rows() returned "
        "[] -- the unreadable state was folded into 'nothing found'"
    )
    assert any(r.get("state") == "unreadable" for r in rows), rows


def test_documents_returning_unreadable_message_is_reported(tmp_path, monkeypatch):
    """Arm 3. `documents()` returning `(paths, unreadable)` with a real
    unreadable message (the shape #571 built) must reach a row -- this path
    does not go through the except clause at all, so it is the control that
    proves the state is reachable once nothing swallows it.
    """
    root, _phases_dir = _fixture_tree(tmp_path)
    spine = root / "skills" / "manager" / "SKILL.md"

    def _fake(_root):
        return [spine], ["simulated: phases directory could not be read"]

    monkeypatch.setattr(skill_phases, "documents", _fake)

    rows = skill_phases._undeclared_rows(root)

    assert any(r.get("state") == "unreadable" for r in rows), rows
