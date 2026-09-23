"""#1716: a doctor run's role marker can overwrite a live sub-manager
marker, silently disabling that tick's own release refusal.

`write_role_marker` used to write unconditionally: nothing ever checked
whether a LIVE marker already there named a different role before
overwriting it. A doctor spawn running `agent_role.py --write doctor` in
the same clone as a live tick (`sub-manager`) clobbered that tick's own
marker, and `role_forbids_release` then silently read `doctor` -- not
`sub-manager` -- for the rest of that tick, so the #695 release-authority
refusal went unenforced with nothing printed about it.

The fix: a write that would overwrite a LIVE marker naming a DIFFERENT
role refuses (state `_MARKER_CONFLICT`) rather than writing, unless
`force=True` is passed explicitly. Same role overwriting itself, and any
write over an absent or stale marker, are unaffected -- the positive
controls below pin that the fix is narrow.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "agent_role.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import agent_role  # noqa: E402
import spawn_guard  # noqa: E402


def _init_repo(tmp_path):
    subject = (
        "the role marker, in a git repository this fixture never finished creating"
    )
    spawn_guard.run(
        ["git", "init", "-q", str(tmp_path)], subject=subject, check=True, timeout=30
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
        subject=subject,
        check=True,
        timeout=30,
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "t"],
        subject=subject,
        check=True,
        timeout=30,
    )
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "add", "-A"],
        subject=subject,
        check=True,
        timeout=30,
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
        subject=subject,
        check=True,
        timeout=30,
    )


def test_a_live_different_role_marker_refuses_the_overwrite(tmp_path):
    """The bug: a doctor write must not silently clobber a live sub-manager
    marker."""
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    state, detail = agent_role._write_role_marker_detail("doctor", root=str(tmp_path))
    assert state == agent_role._MARKER_CONFLICT
    assert detail == "sub-manager"
    # The marker itself must be untouched -- a refused write is not a
    # partial write.
    assert agent_role.current_role(root=str(tmp_path)) == "sub-manager"


def test_write_role_marker_bool_contract_is_false_on_conflict(tmp_path):
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    assert agent_role.write_role_marker("doctor", root=str(tmp_path)) is False
    assert agent_role.current_role(root=str(tmp_path)) == "sub-manager"


def test_the_same_role_overwriting_itself_is_not_a_conflict(tmp_path):
    """Positive control: re-declaring the SAME role over its own live
    marker must keep working -- only a DIFFERENT role is refused."""
    _init_repo(tmp_path)
    agent_role.write_role_marker("doctor", root=str(tmp_path))
    state, _detail = agent_role._write_role_marker_detail("doctor", root=str(tmp_path))
    assert state == agent_role._MARKER_OK


def test_writing_over_an_absent_marker_is_not_a_conflict(tmp_path):
    """Positive control: the ordinary, no-marker-yet case must be unaffected."""
    _init_repo(tmp_path)
    state, _detail = agent_role._write_role_marker_detail("doctor", root=str(tmp_path))
    assert state == agent_role._MARKER_OK
    assert agent_role.current_role(root=str(tmp_path)) == "doctor"


def test_a_stale_different_role_marker_does_not_block_the_write(tmp_path):
    """A marker past `MARKER_TTL_SECONDS` is exactly as dead as an absent
    one for every other reader (`current_role`, `role_forbids_release`) --
    the conflict check must read the same way, or a residue marker from a
    long-dead process would block every doctor run forever."""
    _init_repo(tmp_path)
    ancient = 0.0
    agent_role.write_role_marker("sub-manager", root=str(tmp_path), written_at=ancient)
    state, _detail = agent_role._write_role_marker_detail("doctor", root=str(tmp_path))
    assert state == agent_role._MARKER_OK
    assert agent_role.current_role(root=str(tmp_path)) == "doctor"


def test_force_overrides_the_conflict(tmp_path):
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    state, _detail = agent_role._write_role_marker_detail(
        "doctor", root=str(tmp_path), force=True
    )
    assert state == agent_role._MARKER_OK
    assert agent_role.current_role(root=str(tmp_path)) == "doctor"


def test_cli_write_refuses_with_exit_3_and_names_both_roles(tmp_path):
    _init_repo(tmp_path)
    write = spawn_guard.run(
        [
            sys.executable,
            str(SCRIPT),
            "--write",
            "sub-manager",
            "--root",
            str(tmp_path),
        ],
        subject="the marker this conflict test writes before the refusal",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert write.returncode == 0, write.stdout + write.stderr

    conflict = spawn_guard.run(
        [sys.executable, str(SCRIPT), "--write", "doctor", "--root", str(tmp_path)],
        subject="what --write prints when a live marker names a different role (#1716)",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert conflict.returncode == 3, conflict.stdout + conflict.stderr
    assert "sub-manager" in conflict.stdout
    assert "doctor" in conflict.stdout
    assert "--force" in conflict.stdout

    read_back = spawn_guard.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, {0!r}); import agent_role; "
                "print(agent_role.current_role(root={1!r}))"
            ).format(str(REPO / "scripts"), str(tmp_path)),
        ],
        subject="the marker's role after a refused overwrite -- must be unchanged",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert read_back.stdout.strip() == "sub-manager", (
        read_back.stdout + read_back.stderr
    )


def test_cli_write_with_force_overwrites(tmp_path):
    _init_repo(tmp_path)
    spawn_guard.run(
        [
            sys.executable,
            str(SCRIPT),
            "--write",
            "sub-manager",
            "--root",
            str(tmp_path),
        ],
        subject="the marker this force test writes before overriding it",
        check=True,
        timeout=30,
    )
    forced = spawn_guard.run(
        [
            sys.executable,
            str(SCRIPT),
            "--write",
            "doctor",
            "--root",
            str(tmp_path),
            "--force",
        ],
        subject="whether --force overrides the #1716 refusal",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert forced.returncode == 0, forced.stdout + forced.stderr
