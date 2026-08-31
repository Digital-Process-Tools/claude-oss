"""A stale role marker must not resolve to `sub-manager` forever (#695, review finding).

`agents/sub-manager.md` writes a marker under the repository's own git
directory and nothing ever cleared it: no `--clear`, no expiry, no process
identity. A sub-manager that dies mid-tick (or is killed, or its harness
crashes) leaves the marker behind, and a later, wholly legitimate
`/oss:release` from the same clone -- run by the scheduler or by the
maintainer directly -- would resolve `sub-manager` from that residue and
`release_publish.py` would refuse to publish with a confident reason citing
#695. The asymmetry is the point: absent marker fails open (fine, the
ordinary case), stale marker failed closed forever (not fine, and this
repository's own defect class pointed at the direction that blocks work).

The fix has two parts, because clear-on-exit alone does not cover a
crashed or killed sub-manager -- precisely the case that leaves residue:

  * every marker carries a `written_at` timestamp and expires after
    `MARKER_TTL_SECONDS` -- this alone closes the crash path, since it
    requires nothing from the process that wrote it;
  * `clear_role_marker()` / `--clear` gives the success path a fast,
    immediate release rather than waiting out the TTL.

An expired or unparsable marker must not silently render as `None` either
-- `_read_marker()` gives it its own state (`stale` / `malformed`),
distinct from `live` and `absent`, so a caller can tell "nothing was ever
declared" from "something was declared and this tool does not trust it"
without conflating the two into the same silence. `current_role()`'s
public two-state (`str | None`) contract is unchanged, and BOTH `stale`
and `malformed` resolve through it the same way `absent` does -- towards
*permitting* the release, matching the existing, deliberate fail-open
direction rather than reintroducing the residue bug in disguise as
"unknown, so refuse."

Every negative assertion here ("a stale marker no longer denies") is
paired with a positive control in the same fixture ("a live marker still
denies"), per this repository's own working rule -- a test that only
checks the stale case would also pass if the guard had stopped working
entirely.
"""

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "agent_role.py"

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
    subject = "the role marker, in a git repository this fixture never finished creating"
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
        ["git", "-C", str(tmp_path), "add", "-A"], subject=subject, check=True, timeout=30
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
        subject=subject,
        check=True,
        timeout=30,
    )


# -- the paired positive control: a live marker still denies ---------------


def test_a_live_marker_still_denies_release(tmp_path):
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    assert agent_role.current_role(root=str(tmp_path)) == "sub-manager"
    assert agent_role.role_forbids_release(root=str(tmp_path)) is True


# -- the negative case: a stale marker no longer denies ---------------------


def test_a_stale_marker_no_longer_denies_release(tmp_path):
    """The crash path: nothing cleared the marker, but it has aged past the
    TTL, so it must resolve as though nothing were declared at all."""
    _init_repo(tmp_path)
    ancient = time.time() - (agent_role.MARKER_TTL_SECONDS + 3600)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path), written_at=ancient)
    assert agent_role.current_role(root=str(tmp_path)) is None
    assert agent_role.role_forbids_release(root=str(tmp_path)) is False


def test_a_marker_just_under_the_ttl_still_denies(tmp_path):
    """The boundary companion to the two tests above: a marker written well
    within the TTL is not accidentally treated as stale."""
    _init_repo(tmp_path)
    recent = time.time() - 60
    agent_role.write_role_marker("sub-manager", root=str(tmp_path), written_at=recent)
    assert agent_role.role_forbids_release(root=str(tmp_path)) is True


# -- a marker that cannot be classified is its own state, not a silent None -


def test_read_marker_reports_live_stale_malformed_absent_as_four_distinct_states(tmp_path):
    _init_repo(tmp_path)

    absent = agent_role._read_marker(root=str(tmp_path))
    assert absent["state"] == "absent"

    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    live = agent_role._read_marker(root=str(tmp_path))
    assert live["state"] == "live"
    assert live["role"] == "sub-manager"

    ancient = time.time() - (agent_role.MARKER_TTL_SECONDS + 1)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path), written_at=ancient)
    stale = agent_role._read_marker(root=str(tmp_path))
    assert stale["state"] == "stale"

    marker_path = agent_role._marker_path(root=str(tmp_path))
    marker_path.write_text("not json at all", encoding="utf-8")
    malformed = agent_role._read_marker(root=str(tmp_path))
    assert malformed["state"] == "malformed"

    states = {absent["state"], live["state"], stale["state"], malformed["state"]}
    assert states == {"absent", "live", "stale", "malformed"}, (
        "the four states must be genuinely distinct, not two names for the "
        "same fallback"
    )


def test_a_malformed_marker_does_not_deny_release(tmp_path):
    """The old plain-text marker format (a bare role string, no JSON, no
    timestamp) is exactly this shape -- it must fail open, not crash and
    not silently grant sub-manager."""
    _init_repo(tmp_path)
    marker_path = agent_role._marker_path(root=str(tmp_path))
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("sub-manager\n", encoding="utf-8")
    assert agent_role.current_role(root=str(tmp_path)) is None
    assert agent_role.role_forbids_release(root=str(tmp_path)) is False


# -- clearing: the fast path for the success case ---------------------------


def test_clear_role_marker_removes_it(tmp_path):
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    assert agent_role.current_role(root=str(tmp_path)) == "sub-manager"
    cleared = agent_role.clear_role_marker(root=str(tmp_path))
    assert cleared is True
    assert agent_role.current_role(root=str(tmp_path)) is None


def test_clear_role_marker_on_an_absent_marker_is_not_an_error(tmp_path):
    _init_repo(tmp_path)
    assert agent_role.clear_role_marker(root=str(tmp_path)) is False


def test_cli_clear_removes_a_marker_written_by_a_separate_process(tmp_path):
    _init_repo(tmp_path)
    write = spawn_guard.run(
        [sys.executable, str(SCRIPT), "--write", "sub-manager", "--root", str(tmp_path)],
        subject="the marker --clear is then asked to remove",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert write.returncode == 0, write.stdout + write.stderr

    clear = spawn_guard.run(
        [sys.executable, str(SCRIPT), "--clear", "--root", str(tmp_path)],
        subject="whether --clear removes a marker written by a separate process",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert clear.returncode == 0, clear.stdout + clear.stderr

    read_back = spawn_guard.run(
        [sys.executable, "-c", (
            "import sys; sys.path.insert(0, {0!r}); import agent_role; "
            "print(agent_role.current_role(root={1!r}))"
        ).format(str(REPO / "scripts"), str(tmp_path))],
        subject="what a separate process reads back after --clear",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert read_back.stdout.strip() == "None", read_back.stdout + read_back.stderr


# -- the marker's write format is JSON with an explicit timestamp -----------


def test_marker_on_disk_is_json_with_a_written_at_timestamp(tmp_path):
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    marker_path = agent_role._marker_path(root=str(tmp_path))
    data = json.loads(marker_path.read_text(encoding="utf-8"))
    assert data["role"] == "sub-manager"
    assert isinstance(data["written_at"], (int, float))


# -- release_refusal surfaces the marker's own classification ---------------


def test_release_refusal_reports_the_marker_state_for_diagnostics(tmp_path):
    _init_repo(tmp_path)
    ancient = time.time() - (agent_role.MARKER_TTL_SECONDS + 1)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path), written_at=ancient)
    refusal = agent_role.release_refusal("publish a GitHub Release", root=str(tmp_path))
    assert refusal["forbidden"] is False
    assert refusal["marker_state"] == "stale", (
        "a stale marker that is silently ignored for the forbid decision must "
        "still be visible somewhere, or a maintainer investigating a release "
        "that unexpectedly went through (or one that unexpectedly didn't) has "
        "no way to see that a residue was there at all"
    )
