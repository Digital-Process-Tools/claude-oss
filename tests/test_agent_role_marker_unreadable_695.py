"""An unreadable marker must not be classified `absent` (#695, review finding).

`_read_marker` wrapped `path.read_text` in `except OSError` and returned
`MARKER_STATE_ABSENT` from that handler -- so a marker that exists and
could not be read (permission denied, an unreadable path, any errno that
is not a genuine miss) was reported as a marker that was never written.
That is `CLAUDE.md`'s own named trap, twice over: `doctor._dir_state` and
`lane_setup.worktree_occupancy` did exactly this in #380, and the rule
that came out of it is that a library -- or, here, an over-eager `except`
-- must never be allowed to decide the classification for you.

Also present in the same function, on the line above: `path.is_file()`,
which is the same family as the `Path.exists()` prohibition this
repository already documents -- it swallows `OSError` and answers `False`
for a path that exists and cannot be `stat()`'d, so the `absent` return
on that line carried the identical defect one line earlier. Both are
fixed the same way, and by the same mechanism: `_read_marker` no longer
asks two questions (`is_file()`, then `read_text()`); it asks the
filesystem once, and the exception already in hand -- `FileNotFoundError`
for a genuine miss, anything else for "there and I could not read it" --
decides which arm runs. That is the pattern `scripts/review_return.py`'s
own `_read_source` already uses in this repository for exactly this
reason.

The two facts are kept apart as their own states (`unreadable` is not
folded into `malformed`) because they are actionable differently: a
`malformed` marker means something wrote bad content and needs looking
at; an `unreadable` one means this process cannot see the file at all and
the read path itself needs looking at. Both fail open for the actual
`role_forbids_release` decision -- exactly like `stale` and `absent`
already do -- so nothing here changes what a release does; it changes
what a diagnostic can say about why.

Per this repository's own working rule, the deny fixture is a
measurement, not a given: the unreadable condition is established by
attempting the exact operation the code under test performs
(`path.read_text`) against a mode-0 file, and if this platform does not
honour the mode bit for that attempt, the test skips with the errno and a
sentence naming what went untested rather than asserting on a platform's
error code from a table. The positive control lives in the same fixture:
a readable marker must still classify `live`, so a broken classifier that
answered the same thing for everything could not pass both halves.
"""

import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import agent_role  # noqa: E402
import spawn_guard  # noqa: E402


def _init_repo(tmp_path):
    """Routed through `spawn_guard.run` rather than bare `subprocess.run` so that a
    runner too slow to answer skips this test carrying what went unmeasured, rather
    than erroring on a setup step (#716). Setup is deliberately not exempt: a `git
    commit` that never returned leaves this file's subject exactly as unmeasured as
    one that returned the wrong thing.
    """
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


def test_an_unreadable_marker_is_reported_as_unreadable_not_absent(tmp_path):
    _init_repo(tmp_path)

    # The positive control, in the same fixture: a readable marker still
    # classifies live. Written first, so a broken classifier that always
    # answers the same thing cannot pass this half either.
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    live = agent_role._read_marker(root=str(tmp_path))
    assert live["state"] == "live"

    # Now measure whether this platform can actually deny the read the
    # code under test performs, rather than assuming a mode bit works.
    marker_path = agent_role._marker_path(root=str(tmp_path))
    marker_path.chmod(0)
    try:
        try:
            marker_path.read_text(encoding="utf-8")
        except OSError:
            pass
        else:
            pytest.skip(
                "mode 0 did not deny a read of the marker file on this platform "
                "(root, a permissive filesystem, or a Windows attribute that "
                "does not block a read), so this construction cannot produce "
                "an unreadable-but-present marker here. UNTESTED here: whether "
                "_read_marker reports 'unreadable' rather than 'absent' for a "
                "marker this process genuinely cannot read."
            )

        unreadable = agent_role._read_marker(root=str(tmp_path))
        assert unreadable["state"] == "unreadable", (
            "a marker that exists and could not be read must not be reported "
            "the same as a marker that was never written; got {!r}".format(unreadable)
        )
        assert unreadable["state"] != "absent"

        # current_role and role_forbids_release still fail open for it --
        # unreadable behaves like absent/stale/malformed for the actual
        # decision, only the diagnostic changes.
        assert agent_role.current_role(root=str(tmp_path)) is None
        assert agent_role.role_forbids_release(root=str(tmp_path)) is False

        refusal = agent_role.release_refusal(
            "publish a GitHub Release", root=str(tmp_path)
        )
        assert refusal["forbidden"] is False
        assert refusal["marker_state"] == "unreadable"
    finally:
        marker_path.chmod(0o600)


def test_a_genuinely_absent_marker_is_still_absent(tmp_path):
    """The other half of the split this fixes: removing the `is_file()`
    pre-check must not turn a real absence into `unreadable` -- a
    FileNotFoundError from `read_text` on a path that was never written
    is still the ordinary, deliberate fail-open case."""
    _init_repo(tmp_path)
    absent = agent_role._read_marker(root=str(tmp_path))
    assert absent["state"] == "absent"
    assert agent_role.current_role(root=str(tmp_path)) is None
    assert agent_role.role_forbids_release(root=str(tmp_path)) is False


def test_a_malformed_marker_is_still_malformed_not_unreadable(tmp_path):
    """The read succeeds but the content does not parse -- this must
    stay `malformed`, distinct from both `unreadable` and `absent`."""
    _init_repo(tmp_path)
    marker_path = agent_role._marker_path(root=str(tmp_path))
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("not json at all", encoding="utf-8")
    result = agent_role._read_marker(root=str(tmp_path))
    assert result["state"] == "malformed"


def test_a_stale_marker_is_still_stale_not_unreadable(tmp_path):
    _init_repo(tmp_path)
    ancient = time.time() - (agent_role.MARKER_TTL_SECONDS + 1)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path), written_at=ancient)
    result = agent_role._read_marker(root=str(tmp_path))
    assert result["state"] == "stale"
