"""#1432: four `OSS_WORKSPACE_*` env relays computed in `bin/oss-workspace`, each
exported then explicitly unset right before `exec claude`. Their one intended
consumer was this launcher's own SYNCHRONOUS `doctor.sh` call -- #1392 deleted
that call, moving the diagnostic into the session's own `/oss:run` step 1
instead, which runs later, as a separate process, well after this file's own
unset already ran. `scripts/doctor_check_mcp_channel_registration.py` and
`scripts/doctor_check_mcp_channel_connection.py` still read these names, but
only from inside that later, separate process -- never from this one.

One of the four names this issue lists, `OSS_WORKSPACE_MCP_LIST_OUTPUT`, is NOT
actually dead: read again inside this same file, in the same process, by the
embedded python heredoc that computes the #810 channel census (so `claude mcp
list` is asked once per launch, not twice) -- see the comment beside its own
`export` in `bin/oss-workspace`. Its sibling sentinel, `OSS_WORKSPACE_MCP_LIST_
CHECKED`, is never read anywhere in this file, only by the later, unreachable
session-side consumer, so it is dropped like the other three.

Every test here drives the REAL launcher end to end, reusing `tests/
test_workspace_launcher.py`'s own `run()`/`_stub_claude` fixtures, per
CLAUDE.md's rule that a launcher tested by reading it is a launcher nobody has
run.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_workspace_launcher import (  # noqa: E402
    _consumer_path,
    _mcp_get_output,
    _repo,
    run,
)

_NO_AUTO_UPDATE = {"OSS_NO_AUTO_UPDATE": "1"}

_DEAD_NAMES = (
    "OSS_WORKSPACE_MCP_CHECKED",
    "OSS_WORKSPACE_MCP_STATUS",
    "OSS_WORKSPACE_MCP_OUTPUT",
    "OSS_WORKSPACE_CENSUS_CHECKED",
    "OSS_WORKSPACE_CENSUS_REPORT",
    "OSS_WORKSPACE_MCP_LIST_CHECKED",
    "OSS_WORKSPACE_CHANNEL_ARM_TARGET",
)


def _launcher_source():
    return (REPO_ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")


def test_the_four_dead_relay_names_are_never_exported_in_source_1432():
    """Must-fire: a black-box capture at exec time cannot tell "computed, then
    unset right before exec" from "never computed at all" -- both look
    identical from outside this process, since the unset already ran either
    way (proven clean by `tests/test_workspace_channel_arm_1343.py`'s own
    "leaked var" regression guard, which predates this fix). The seven names
    #1432 traces back to the four dead relays must not be EXPORTED anywhere in
    this file any more; that is the only place the fix (removing dead code, not
    changing observable behaviour) is visible at all.
    """
    source = _launcher_source()
    for name in _DEAD_NAMES:
        assert "export {}".format(name) not in source, (name, "still exported")


def test_the_env_at_exec_capture_stays_clean_too_1432(tmp_path):
    """Positive control for the source check above: the launcher must still
    open a real session with nothing in `_DEAD_NAMES` visible at exec time --
    unchanged behaviour from before this fix, kept here so a future export of
    one of these names that is unset before exec (passing the source check by
    accident, e.g. via a helper function) still fails somewhere.
    """
    repo = _repo(tmp_path)
    bindir = tmp_path / "_stubbin"
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(_consumer_path(repo))),
        env_extra=_NO_AUTO_UPDATE,
    )
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    seen_file = bindir / "env_at_exec.txt"
    assert seen_file.exists(), "the claude stub never recorded an env snapshot"
    snapshot = seen_file.read_text(encoding="utf-8")
    for name in _DEAD_NAMES:
        assert name not in snapshot, (name, snapshot, done.stderr)


def test_the_real_mcp_list_output_relay_still_reaches_its_in_process_consumer_1432(
    tmp_path,
):
    """Must-not-regress: `OSS_WORKSPACE_MCP_LIST_OUTPUT` is the one name in this
    family with a REAL same-process consumer (the embedded #810 census heredoc),
    so it must keep working even though its session-side sentinel
    (`OSS_WORKSPACE_MCP_LIST_CHECKED`) is gone -- proven here by a positive
    control the census math can only pass if that relay was actually read.
    """
    repo = _repo(tmp_path)
    bindir = tmp_path / "_stubbin"
    consumer = _consumer_path(repo)
    own_row = "oss-channel:    bun {}\\n".format(consumer)
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(consumer)),
        mcp_list=own_row,
        env_extra=dict(_NO_AUTO_UPDATE),
    )
    # A collision-free census (exactly one matching server, itself) keeps the
    # flag armed; a broken relay would make the embedded heredoc re-ask
    # `claude mcp list` for itself, which the stub still answers identically,
    # so this alone would not distinguish a working relay from a dead one --
    # paired below with the launcher's own mcp-call log as the real proof.
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    calls = (
        (bindir / "mcp.txt").read_text(encoding="utf-8")
        if (bindir / "mcp.txt").exists()
        else ""
    )
    list_calls = [line for line in calls.splitlines() if line == "list"]
    assert len(list_calls) == 1, (calls, done.stderr)
