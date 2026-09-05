"""#810 -- `bin/oss-workspace` arms `--dangerously-load-development-channels`
after verifying its OWN `oss-channel` registration and never asked whether some
OTHER configured MCP server also resolves to the claude-channel consumer script.
Two servers racing that script for one socket is invisible from inside a
session: one binds, the other is silently refused, and `channel:health` can only
report `CANNOT DETERMINE`.

Every test here goes through the REAL launcher and the REAL
`doctor.channel_consumer_census_state`, via `tests/test_workspace_launcher.py`'s
own `run()`/`_stub_claude` fixtures, extended with `mcp_list`/`mcp_list_exit` for
exactly this file. `tests/test_channel_consumer_census_810.py` already covers the
census function in isolation; this file is about the launcher's OWN wiring --
does it actually disarm the flag on a real collision, and does the positive
control (exactly one server: itself) stay armed.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_workspace_launcher import (  # noqa: E402
    _consumer_path,
    _mcp_get_output,
    _mcp_calls,
    _repo,
    run,
)

#: Off, unconditionally, in every test here -- #753's synchronous update call is
#: not this file's subject, and leaving it on would add a second, unrelated
#: `claude` invocation (`plugin marketplace update`) to every launch these tests
#: drive, for no assertion that reads it.
_NO_AUTO_UPDATE = {"OSS_NO_AUTO_UPDATE": "1"}


def _own_row(cwd):
    """The one `claude mcp list` row THIS session's own `oss-channel`
    registration would produce, matching `_mcp_get_output`'s Command/Args."""
    return "oss-channel:    bun {}\n".format(_consumer_path(cwd))


def test_a_single_matching_server_still_arms_the_flag(tmp_path):
    """The must-fire positive control: exactly one server (itself, echoed back by
    `claude mcp list`) must never read as a collision."""
    repo = _repo(tmp_path)
    _, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(_consumer_path(repo))),
        mcp_list=_own_row(repo),
        env_extra=_NO_AUTO_UPDATE,
    )
    assert any("development-channels" in a for a in argv), argv
    assert "server:oss-channel" in argv


def test_zero_matching_servers_still_arms_the_flag(tmp_path):
    """`claude mcp list` printing nothing recognisable (the stub's own default) is
    an empty census, not a probe failure -- the flag stays armed."""
    repo = _repo(tmp_path)
    _, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(_consumer_path(repo))),
        env_extra=_NO_AUTO_UPDATE,
    )
    assert any("development-channels" in a for a in argv), argv


def test_two_matching_servers_disarm_the_flag_and_name_both(tmp_path):
    """The must-not-fire control's positive twin: a real collision must omit the
    flag from the exec line and name both servers on stderr."""
    repo = _repo(tmp_path)
    consumer = _consumer_path(repo)
    two_rows = (
        "claude-channel: bun /Users/x/Documents/claude-supertool/notifiers/claude-channel/channel.ts\n"
        + "oss-channel:    bun {}\n".format(consumer)
    )
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(consumer)),
        mcp_list=two_rows,
        env_extra=_NO_AUTO_UPDATE,
    )
    assert not any("development-channels" in a for a in argv), argv
    assert "server:oss-channel" not in argv
    assert "claude-channel" in done.stderr
    assert "oss-channel" in done.stderr


def test_a_failed_census_disarms_the_flag_and_says_unknown(tmp_path):
    """The third state the issue names explicitly: `claude mcp list` failing must
    never be read as "exactly one server" -- it must disarm the flag too, and say
    UNKNOWN rather than claim a clean census."""
    repo = _repo(tmp_path)
    consumer = _consumer_path(repo)
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(consumer)),
        mcp_list_exit=1,
        env_extra=_NO_AUTO_UPDATE,
    )
    assert not any("development-channels" in a for a in argv), argv
    assert "server:oss-channel" not in argv
    assert "unknown" in done.stderr.lower() or "UNKNOWN" in done.stderr


def test_the_launcher_relays_its_own_census_to_doctor_sh_rather_than_asking_twice(
    tmp_path,
):
    """Review finding on #810: `bin/oss-workspace` runs the census, then shells
    out to `doctor.sh`, which runs `check_channel_consumer_census()` again --
    the identical shape #629 already fixed once for the registration check.
    `claude mcp list` must be called exactly ONCE across the whole launch, not
    once per checker."""
    repo = _repo(tmp_path)
    consumer = _consumer_path(repo)
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get=_mcp_get_output(str(consumer)),
        mcp_list=_own_row(repo),
        env_extra=_NO_AUTO_UPDATE,
    )
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    list_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "list"
    ]
    assert len(list_calls) == 1, (list_calls, done.stderr)


def test_a_session_that_never_arms_the_flag_omits_it_and_says_why(tmp_path):
    """No registered consumer means channel_ready is already 0 well before the
    census -- the flag stays unarmed, for the reason the earlier registration
    arm already gives (not this issue's own collision message). `/oss:doctor`'s
    OWN mirror still runs `claude mcp list` unconditionally as part of its
    diagnostic -- that is a separate, always-on check, not the launcher's
    arm-or-not decision this file is about."""
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=False, env_extra=_NO_AUTO_UPDATE)
    assert not any("development-channels" in a for a in argv), argv
