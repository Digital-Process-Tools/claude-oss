"""#1307: `bin/oss-workspace` registered `oss-channel` unconditionally, on
every launch, even when an installed plugin's own `.mcp.json` already
provides a claude-channel consumer -- so the post-registration #810 census
then counted two servers (its own just-added `oss-channel`, plus the
plugin's) and disarmed the flag over the collision the launcher itself just
created.

This file drives the REAL launcher end to end, via `tests/test_
workspace_launcher.py`'s own `run()`/`_stub_claude` fixtures, extended with
a plugin-provided `.mcp.json` server the way `tests/test_plugin_channel_
consumer_census_1241.py` builds one for the Python-level census tests. Every
"must not fire" case here is paired with a "must fire" case in the same
fixture shape, per CLAUDE.md's own rule that a negative assertion needs a
positive control -- `tests/test_workspace_channel_census_810.py`'s own
`test_a_single_matching_server_still_arms_the_flag` is the regression
control for the "no plugin consumer" path this file does not re-test.
"""

import json
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

#: Off, unconditionally, in every test here -- see test_workspace_channel_
#: census_810.py's own identical constant for why.
_NO_AUTO_UPDATE = {"OSS_NO_AUTO_UPDATE": "1"}


def _plant_plugin_channel_server(repo, home):
    """Give the SAME supertool install `_with_channel_consumer` already
    planted (a `notifiers/claude-channel/channel.ts` file, no `.mcp.json`)
    its own `.mcp.json` declaring a `claude-channel` server pointed at that
    exact consumer -- the real-world shape #1307 reports: the plugin's own
    `.mcp.json` has declared this unconditionally since supertool#1541.
    """
    install = (
        home / ".claude" / "plugins" / "cache" / "dpt-plugins" / "supertool" / "9.9.9"
    )
    (install / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "claude-channel": {
                        "command": "bun",
                        "args": [str(_consumer_path(repo))],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _plant_second_plugin_channel_server(repo, home, key="other-plugin@marketplace"):
    """A SECOND, unrelated installed plugin that also declares a
    claude-channel consumer -- the "plural" state: two plugin-provided
    consumers already collide with each other before oss-channel is even
    considered.
    """
    install = home / ".claude" / "plugins" / "cache" / "other" / "1.0.0"
    consumer = install / "notifiers" / "claude-channel" / "channel.ts"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("// stub\n", encoding="utf-8")
    (install / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "claude-channel": {"command": "bun", "args": [str(consumer)]}
                }
            }
        ),
        encoding="utf-8",
    )
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    doc = json.loads(registry.read_text(encoding="utf-8"))
    doc["plugins"][key] = [{"scope": "user", "installPath": str(install)}]
    registry.write_text(json.dumps(doc), encoding="utf-8")


def test_a_single_plugin_consumer_arms_against_it_without_registering_oss_channel(
    tmp_path,
):
    """The must-fire positive control for #1307's own repro: an installed
    plugin's own `.mcp.json` already provides the one in-scope claude-channel
    consumer -- the flag must arm against THAT server, and `oss-channel` must
    never be registered on top of it."""
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    done, argv = run(
        repo,
        with_channel=False,  # the plugin fixture above already planted it
        env_extra=_NO_AUTO_UPDATE,
        # #1343: the `single` arm now VERIFIES the plugin-reported server via
        # `claude mcp get` before trusting it -- named here so that verification
        # succeeds, matching the real world this fixture represents (a plugin's
        # own `.mcp.json` server really is a `claude mcp`-visible registration).
        mcp_get_by_name={
            "plugin:supertool:claude-channel": _mcp_get_output(
                str(_consumer_path(repo))
            )
        },
    )
    # `run()` plants its own `_home`/`_stubbin` when `with_channel=True`; since
    # this test needs to plant an EXTRA .mcp.json on top of that same fixture,
    # it calls `_with_channel_consumer` itself, before `run()`, and passes
    # `with_channel=False` so `run()` does not plant a second, separate one.
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    assert "server:plugin:supertool:claude-channel" in argv, argv
    assert "server:oss-channel" not in argv, argv
    add_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "add"
    ]
    assert add_calls == [], add_calls


def test_a_stale_oss_channel_registration_is_removed_when_a_plugin_covers_it(
    tmp_path,
):
    """A stale `oss-channel`, left behind by an earlier launcher version, must
    be removed rather than left to keep the census counting two forever --
    the exact permanently-disarmed state #1307 reports, reproduced for a
    different reason if this launcher only reported the stale entry instead
    of clearing it."""
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
        mcp_get=_mcp_get_output(str(_consumer_path(repo))),
        env_extra=_NO_AUTO_UPDATE,
    )
    assert any("development-channels" in a for a in argv), (argv, done.stderr)
    assert "server:plugin:supertool:claude-channel" in argv, argv
    remove_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "remove"
    ]
    assert any("oss-channel" in call for call in remove_calls), (
        remove_calls,
        done.stderr,
    )


def test_two_plugin_consumers_disarm_without_registering_oss_channel(tmp_path):
    """Must-not-fire control's positive twin: two installed plugins already
    collide with each other before `oss-channel` is even considered --
    registering a third racer on top would only make it worse, so it must
    stay unregistered and the flag must stay unarmed."""
    repo = _repo(tmp_path)
    home = tmp_path / "_home"
    bindir = tmp_path / "_stubbin"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    bindir.mkdir(exist_ok=True)
    _with_channel_consumer(home, bindir)
    _plant_plugin_channel_server(repo, home)
    _plant_second_plugin_channel_server(repo, home)
    done, argv = run(repo, with_channel=False, env_extra=_NO_AUTO_UPDATE)
    assert not any("development-channels" in a for a in argv), (argv, done.stderr)
    add_calls = [
        call for call in _mcp_calls(repo) if len(call) > 1 and call[1] == "add"
    ]
    assert add_calls == [], add_calls
