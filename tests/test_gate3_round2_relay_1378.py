"""#1378 finding 1 (gate 3 round two, v0.31.0): the round-one relay fix
(#1372) hardened `doctor_check_mcp_channel_connection.mcp_channel_connection_
state`'s own reading of `OSS_WORKSPACE_MCP_LIST_OUTPUT` with a freshness
sentinel, but `bin/oss-workspace`'s OWN embedded `CHANNEL_CENSUS` heredoc --
the actual same-process consumer of that relay (#1432) -- was never touched:
it reads the env var bare and trusts any non-empty value, with no way to
tell "computed by this launch, moments ago" from "already sitting in the
inherited environment before this script ran" (a parent shell'"'"'s profile, or
a caller that exported the same name first). #1432 dropped the sentinel this
issue'"'"'s own suggested remedy names (`OSS_WORKSPACE_MCP_LIST_CHECKED`) as dead
code, so the fix here is not to resurrect it but to make this launcher
overwrite its own export on every path through the branch that computes it --
success AND failure -- so nothing inherited can survive past that point.

Every test drives the REAL launcher end to end, reusing `tests/
test_workspace_launcher.py`'"'"'s own fixtures, per CLAUDE.md'"'"'s rule that a
launcher tested by reading it is a launcher nobody has run.
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


def _own_row(cwd):
    return "oss-channel:    bun {}\n".format(_consumer_path(cwd))


def test_a_stale_inherited_relay_never_survives_a_failed_ask(tmp_path):
    """Must-fire: plant a value in the environment this launch INHERITS
    (never exported by this run) that would read as a clean, single-server
    census if trusted, then make `claude mcp list` fail inside this launch.
    The census must still report the ask failed and disarm the flag -- never
    silently replay the inherited value as though it were this launch'"'"'s own
    fresh answer."""
    repo = _repo(tmp_path)
    consumer = _consumer_path(repo)
    stale = _own_row(repo)
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(consumer)),
        mcp_list_exit=1,
        env_extra=dict(_NO_AUTO_UPDATE, OSS_WORKSPACE_MCP_LIST_OUTPUT=stale),
    )
    assert not any("development-channels" in a for a in argv), (argv, done.stderr)
    assert "server:oss-channel" not in argv
    assert "unknown" in done.stderr.lower(), done.stderr


def test_a_real_success_still_relays_correctly_alongside_the_new_guard(tmp_path):
    """Positive control: the fix must not break the ordinary path -- a real,
    successful `claude mcp list` inside this launch must still relay to the
    census and arm the flag on a clean (single, itself) reading."""
    repo = _repo(tmp_path)
    consumer = _consumer_path(repo)
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(consumer)),
        mcp_list=_own_row(repo),
        env_extra=dict(_NO_AUTO_UPDATE, OSS_WORKSPACE_MCP_LIST_OUTPUT="garbage-stale"),
    )
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    assert "server:oss-channel" in argv
