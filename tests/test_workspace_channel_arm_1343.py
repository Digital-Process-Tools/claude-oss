"""#1343: four findings in `bin/oss-workspace`'s channel-arming block, all
sharing the same `single`/`plural`/else if/elif/else that decides what to
arm `--dangerously-load-development-channels` against.

Every test here drives the REAL launcher end to end, reusing `tests/
test_workspace_launcher.py`'s own `run()`/`_stub_claude` fixtures and
`tests/test_workspace_plugin_channel_arm_1307.py`'s own plugin-consumer
fixtures, per CLAUDE.md's rule that a launcher tested by reading it is a
launcher nobody has run.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_workspace_launcher import (  # noqa: E402
    _consumer_path,
    _mcp_calls,
    _mcp_get_output,
    _repo,
    _with_channel_consumer,
    run,
)
from test_workspace_plugin_channel_arm_1307 import (  # noqa: E402
    _plant_plugin_channel_server,
    _plant_second_plugin_channel_server,
)

_NO_AUTO_UPDATE = {"OSS_NO_AUTO_UPDATE": "1"}


# ---------------------------------------------------------------- finding 1


def test_the_plural_branch_still_opens_a_session(tmp_path):
    """Must-fire: `channel_ready` is set inside the `single` branch and
    inside the plain fallback `else` branch, but never on the `plural` arm
    itself -- and it is read later, unconditionally, under `set -eu`. Two
    colliding plugin consumers must still open a session (no channel, since
    there is no single target to arm against), not kill the launcher with
    'channel_ready: unbound variable' before it ever reaches `exec claude`.
    """
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    _plant_second_plugin_channel_server(repo, home)
    done, argv = run(repo, with_channel=False, env_extra=_NO_AUTO_UPDATE)
    assert "unbound variable" not in done.stderr, done.stderr
    assert done.returncode == 0, (done.returncode, done.stderr)
    # The session opened (exec claude ran), just without the channel flag --
    # a board that cannot be verified is not a board that is armed, but "no
    # board" must still mean "a session", per the launcher's own stated rule
    # that a session with no channel beats no session.
    assert argv, (argv, done.stderr)
    assert not any("development-channels" in a for a in argv), argv


def test_the_single_branch_still_opens_a_session_with_the_flag(tmp_path):
    """Positive control, paired with the must-fire case above: the ordinary
    single-plugin-consumer path (which sets `channel_ready=1` explicitly)
    must be unaffected by hoisting the initialisation -- still armed."""
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    done, argv = run(
        repo,
        with_channel=False,
        env_extra=_NO_AUTO_UPDATE,
        mcp_get_by_name={
            "plugin:supertool:claude-channel": _mcp_get_output(
                str(_consumer_path(repo))
            )
        },
    )
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    assert "server:plugin:supertool:claude-channel" in argv, argv


# ---------------------------------------------------------------- finding 2


def test_an_unresolvable_plugin_target_falls_back_to_registering_oss_channel(
    tmp_path,
):
    """Must-fire: the `single` branch names `plugin_channel_target` from the
    plugin-population precheck, but that precheck never asks `claude mcp
    get` whether the name actually resolves -- unlike every OTHER arm, which
    all verify before trusting a registration. A plugin that reports a
    consumer `claude mcp` does not actually know about must fall back to
    registering `oss-channel` from scratch, not silently arm a name that
    will refuse the launch.
    """
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    done, argv = run(
        repo,
        with_channel=False,
        env_extra=_NO_AUTO_UPDATE,
        mcp_get_by_name={"plugin:supertool:claude-channel": None},
    )
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    assert "server:oss-channel" in argv, argv
    assert "server:plugin:supertool:claude-channel" not in argv, argv
    add_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "add"
    ]
    assert any("oss-channel" in call for call in add_calls), add_calls


def test_a_resolvable_plugin_target_is_verified_and_armed(tmp_path):
    """Positive control: when `claude mcp get` DOES confirm the plugin's
    named server, it must still be armed against (and `oss-channel` must
    still never be registered on top of it) -- the verification must not
    become a second false-negative source over the ordinary case."""
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    done, argv = run(
        repo,
        with_channel=False,
        env_extra=_NO_AUTO_UPDATE,
        mcp_get_by_name={
            "plugin:supertool:claude-channel": _mcp_get_output(
                str(_consumer_path(repo))
            )
        },
    )
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert "server:plugin:supertool:claude-channel" in argv, argv
    add_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "add"
    ]
    assert not any("oss-channel" in call for call in add_calls), add_calls
    get_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "get"
    ]
    assert any("plugin:supertool:claude-channel" in call for call in get_calls), (
        get_calls
    )


# ---------------------------------------------------------------- finding 3


def test_the_arm_target_env_var_does_not_leak_into_the_session(tmp_path):
    """Must-fire: `OSS_WORKSPACE_CHANNEL_ARM_TARGET` is exported only to
    relay the arm decision into the `doctor.sh` subprocess run before
    `exec claude` -- it must be unset before the session itself starts, the
    same #629 treatment already given `OSS_WORKSPACE_MCP_CHECKED` and the
    #810 census relay. Left exported, a `claude mcp get` answer read once at
    launch would go on answering an in-session `/oss:doctor` for the rest
    of the session -- the reading-taken-once-and-treated-as-fresh-forever
    defect this repo is named after."""
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    done, argv = run(
        repo,
        with_channel=False,
        env_extra=_NO_AUTO_UPDATE,
        mcp_get_by_name={
            "plugin:supertool:claude-channel": _mcp_get_output(
                str(_consumer_path(repo))
            )
        },
    )
    # Positive control, in the SAME run: the arming itself must still have
    # worked -- proving the leaked var is not what made arming succeed.
    assert "server:plugin:supertool:claude-channel" in argv, (argv, done.stderr)
    seen_file = bindir / "arm_target_at_exec.txt"
    assert seen_file.exists(), "the claude stub never recorded an env snapshot"
    assert seen_file.read_text(encoding="utf-8") == "", (
        "OSS_WORKSPACE_CHANNEL_ARM_TARGET leaked into the exec'd session: "
        + seen_file.read_text(encoding="utf-8")
    )
