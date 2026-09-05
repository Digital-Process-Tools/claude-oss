"""#284 -- doctor's memory line must answer the question a fresh installer is in.

The issue was filed from the passing branch plus `memory_layout`'s docstring, and said
so: the failing branch was never observed. It has been now, and the two decisions the
issue asks a fix to make were **already made** -- the absent message names both paths
and the target, and the present-but-unread message exists and is distinct.

What was not covered is the state a marketplace install is actually in on day one:
`identity.md` placed at `.claude/remember/identity.md` -- where it looks like it goes --
and no `.remember/` directory yet, because nothing has saved a session. `check_memory`
returned early on `not store.is_dir()`, so the stray detection below it was unreachable
and doctor printed a reassuring "it will create one on first save" that mentioned
neither identity.md nor the file sitting unread two directories away.

That is this repository's own defect class: the check that would have said so never ran,
and its silence rendered as the absence of a problem.

The second half is the listing itself. `Path.is_dir` swallows `OSError` and `Path.glob`
swallows `PermissionError` while walking, so a directory that exists and cannot be
entered produced "no identity.md here" -- a confident absence about a directory nobody
read.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _only():
    """check_memory prints exactly one line. Asserted rather than assumed, because a
    fix that printed two would otherwise be graded on whichever one happened to be
    last."""
    lines = list(doctor.FINDINGS)
    assert len(lines) == 1, "check_memory must print exactly one line, got {!r}".format(
        lines
    )
    return lines[0]


def _home(tmp_path):
    """An isolated, empty home directory (#614). Without this, every call to
    check_memory below that is not a local install would read the actual
    developer's real ~/.remember/config.json, making the test's outcome depend
    on whatever memory layout happens to be configured on the machine running
    it."""
    return tmp_path / "isolated-home"


def _stray(root):
    """A marketplace install's most likely day-one shape: identity where it looks like
    it goes, and no data dir yet because nothing has saved."""
    config_dir = root / ".claude" / "remember"
    config_dir.mkdir(parents=True)
    (config_dir / "identity.md").write_text(
        "I am nobody in particular.\n", encoding="utf-8"
    )
    assert not (root / ".remember").exists()
    return config_dir


def test_stray_identity_is_reported_when_the_data_dir_does_not_exist_yet(tmp_path):
    """The whole of #284, reduced: present-and-unread must not render as "nothing here".

    Before the fix this printed `.remember: no memory store in this project ... it will
    create one on first save` -- true, and silent about the file that is the reason the
    installer ran doctor at all.
    """
    _stray(tmp_path)
    doctor.check_memory(tmp_path, home=_home(tmp_path))
    state, message = _only()

    assert state == "WARN"
    assert ".claude/remember/identity.md" in message, message
    assert "never read" in message, message
    # The remedy, not just the diagnosis.
    assert ".remember/identity.md" in message, message


def test_the_data_dir_being_absent_is_still_said_out_loud(tmp_path):
    """Positive control for the message above, and a regression guard on what the old
    early return was carrying: the fix must not buy the stray branch by deleting the
    fact that no store exists yet."""
    _stray(tmp_path)
    doctor.check_memory(tmp_path, home=_home(tmp_path))
    _, message = _only()
    assert ".remember" in message, message
    assert "does not exist" in message or "no memory store" in message, message


def test_no_identity_anywhere_does_not_claim_one_is_present(tmp_path):
    """The negative control for the two above.

    Without it, a fix that unconditionally printed "exists but is never read" would pass
    every assertion in this file.
    """
    (tmp_path / ".claude" / "remember").mkdir(parents=True)
    doctor.check_memory(tmp_path, home=_home(tmp_path))
    state, message = _only()
    assert state == "WARN"
    assert "never read" not in message, message
    assert "no identity.md" in message, message
    # Both consulted locations, so the reader is not sent searching.
    assert ".remember" in message and ".claude/remember" in message, message


def test_a_local_install_is_still_recognised_without_a_data_dir(tmp_path):
    """`.claude/remember/scripts/` means the plugin lives IN the repo, so identity beside
    it is the hook's last-resort fallback and genuinely read. That arm existed and was
    equally unreachable behind the early return."""
    config_dir = _stray(tmp_path)
    (config_dir / "scripts").mkdir()
    doctor.check_memory(tmp_path, home=_home(tmp_path))
    state, message = _only()
    assert state == "OK", message
    assert "local install" in message, message


def test_identity_in_the_data_dir_is_still_the_passing_branch(tmp_path):
    """The branch the issue was filed from. Unchanged, and asserted so that the fix is
    not free to make everything a warning."""
    store = tmp_path / ".remember"
    store.mkdir()
    (store / "identity.md").write_text("x\n", encoding="utf-8")
    doctor.check_memory(tmp_path, home=_home(tmp_path))
    state, message = _only()
    assert state == "OK", message
    assert "memory store configured" in message, message


def _deny(directory):
    """Attempt the exact operation check_memory performs, and report whether the deny
    took -- never assert on a platform's error code from a table.

    Root ignores the mode bit, some filesystems ignore it, and Windows' os.chmod on a
    directory toggles a read-only attribute that does not stop a listing.
    """
    try:
        os.chmod(str(directory), 0o000)
    except OSError as exc:
        return "chmod itself failed: {}".format(exc)
    try:
        os.listdir(str(directory))
    except OSError:
        return None
    return "the directory listed anyway after chmod 0o000"


def test_an_unreadable_data_dir_is_not_reported_as_an_absent_identity(tmp_path):
    """`Path.glob` swallows PermissionError while walking and yields nothing, so the
    old code answered "no identity.md in .remember or .claude/remember" about a
    directory it never read. Three states, and this is the third."""
    store = tmp_path / ".remember"
    store.mkdir()
    (tmp_path / ".claude" / "remember").mkdir(parents=True)
    not_denied = _deny(store)
    try:
        if not_denied:
            pytest.skip(
                "cannot establish an unreadable directory here ({}); what went untested "
                "is doctor's unreadable-store branch, not its absent branch".format(
                    not_denied
                )
            )
        doctor.check_memory(tmp_path, home=_home(tmp_path))
        state, message = _only()
        assert state == "WARN"
        assert "no identity.md" not in message, (
            "an unreadable directory was reported as a read one that held nothing: "
            + message
        )
        assert "unknown" in message or "could not" in message, message
    finally:
        os.chmod(str(store), stat.S_IRWXU)
