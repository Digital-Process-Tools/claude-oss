"""#1241: an installed plugin's own `.mcp.json` server (e.g. supertool's
`claude-channel`) is loaded by the harness directly and appears on NO
`claude mcp` surface at all -- `claude mcp list` omits it entirely, and
`claude mcp get plugin:<name>:<server>` answers "No MCP server named ...".
The original census (`channel_consumer_names` parsing `claude mcp list`
alone) could not see it and reported `single` while a second,
plugin-provided consumer silently held the socket -- the issue's own repro.

This file tests the plugin-population half added to close that gap:
`_plugin_install_paths` (every installed plugin's own `installPath`, read
from the harness's own registry), `_plugin_channel_consumer_names` (which of
those plugins' own `.mcp.json` declares a claude-channel consumer), and
`channel_consumer_census_state`'s folding of that population in alongside
`claude mcp list`'s own.

Every "must not fire" case here is paired with a "must fire" case in the
same fixture shape, per CLAUDE.md's own rule that a negative assertion needs
a positive control.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_mcp_channel_registration as mod  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _registry(tmp_path, plugins):
    path = tmp_path / "installed_plugins.json"
    path.write_text(json.dumps({"plugins": plugins}), encoding="utf-8")
    return str(path)


def _mcp_json(install_dir, servers):
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / ".mcp.json").write_text(
        json.dumps({"mcpServers": servers}), encoding="utf-8"
    )


def _channel_server(script_path):
    return {"command": "bun", "args": [script_path]}


class _FakeCompleted:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def _run_answering(text, returncode=0):
    def run(cmd, **kwargs):
        return _FakeCompleted(returncode, text.encode("utf-8"))

    return run


ONE_MCP_LIST_ROW = (
    "oss-channel:    bun /Users/x/somewhere/notifiers/claude-channel/channel.ts\n"
)
NO_MCP_LIST_ROWS = "some-other-server: bun /Users/x/somewhere/else/entrypoint.ts\n"


# --------------------------------------------------------- _plugin_install_paths


def test_no_registry_file_is_empty_not_an_error(tmp_path):
    missing = str(tmp_path / "does-not-exist.json")
    pairs, reason = mod._plugin_install_paths(missing)
    assert pairs == []
    assert reason is None


def test_registry_lists_every_plugin_not_only_supertool(tmp_path):
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [{"installPath": str(tmp_path / "supertool")}],
            "oss@dpt-plugins": [{"installPath": str(tmp_path / "oss")}],
        },
    )
    pairs, reason = mod._plugin_install_paths(registry)
    assert reason is None
    assert set(pairs) == {
        ("supertool@dpt-plugins", str(tmp_path / "supertool")),
        ("oss@dpt-plugins", str(tmp_path / "oss")),
    }


def test_malformed_registry_json_is_a_reason_not_an_empty_list(tmp_path):
    path = tmp_path / "installed_plugins.json"
    path.write_text("{not json", encoding="utf-8")
    pairs, reason = mod._plugin_install_paths(str(path))
    assert pairs is None
    assert reason


def test_plugins_entry_not_an_object_is_a_reason(tmp_path):
    path = tmp_path / "installed_plugins.json"
    path.write_text(json.dumps({"plugins": ["not", "a", "dict"]}), encoding="utf-8")
    pairs, reason = mod._plugin_install_paths(str(path))
    assert pairs is None
    assert reason


# --------------------------------------------------------- _plugin_channel_consumer_names


def test_a_plugin_with_no_mcp_json_contributes_nothing(tmp_path):
    """Must-not-fire control: most plugins ship no `.mcp.json` at all, and
    that must not be treated as an error."""
    registry = _registry(
        tmp_path, {"some-plugin@marketplace": [{"installPath": str(tmp_path / "p")}]}
    )
    (tmp_path / "p").mkdir()
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert names == []
    assert reason is None


def test_a_plugin_shipping_the_channel_consumer_is_found(tmp_path):
    """The issue's own repro, reproduced structurally: an installed plugin's
    `.mcp.json` declares a server resolving to the claude-channel consumer
    script."""
    install_dir = tmp_path / "supertool" / "0.57.0"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install_dir)}]}
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]


def test_a_plugin_server_pointing_elsewhere_does_not_match(tmp_path):
    """Must-not-fire control paired with the test above."""
    install_dir = tmp_path / "other-plugin"
    _mcp_json(install_dir, {"some-server": {"command": "node", "args": ["index.js"]}})
    registry = _registry(
        tmp_path, {"other@marketplace": [{"installPath": str(install_dir)}]}
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert reason is None
    assert names == []


def test_an_unreadable_mcp_json_is_a_reason_not_a_silent_skip(tmp_path):
    install_dir = tmp_path / "broken-plugin"
    install_dir.mkdir()
    (install_dir / ".mcp.json").write_text("{not json", encoding="utf-8")
    registry = _registry(
        tmp_path, {"broken@marketplace": [{"installPath": str(install_dir)}]}
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert names is None
    assert reason


# --------------------------------------------------------- channel_consumer_census_state


def test_the_issues_own_repro_is_now_a_collision_not_single(tmp_path):
    """The issue's own headline claim: `claude mcp list` alone sees exactly
    one (`oss-channel`), but an installed plugin's own `.mcp.json` ALSO
    resolves to the consumer script -- the census must report `collision`,
    not silently render `single`."""
    install_dir = tmp_path / "supertool" / "0.57.0"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install_dir)}]}
    )
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(ONE_MCP_LIST_ROW),
        which=lambda x: "/usr/bin/claude",
        plugin_registry_path=registry,
    )
    assert state == "collision"
    assert "oss-channel" in detail
    assert "plugin:supertool@dpt-plugins:claude-channel" in detail


def test_no_mcp_list_rows_plus_one_plugin_consumer_is_single(tmp_path):
    """Must-fire positive control: zero on the `claude mcp list` side and
    exactly one plugin-provided consumer must still be counted as `single`,
    not silently dropped because the first population was empty."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install_dir)}]}
    )
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(NO_MCP_LIST_ROWS),
        which=lambda x: "/usr/bin/claude",
        plugin_registry_path=registry,
    )
    assert state == "single"
    assert detail == "plugin:supertool@dpt-plugins:claude-channel"


def test_no_plugins_installed_at_all_is_unaffected(tmp_path):
    """Negative control: a missing registry (no plugins installed through
    this mechanism) must not change the pre-#1241 answer."""
    missing = str(tmp_path / "does-not-exist.json")
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(ONE_MCP_LIST_ROW),
        which=lambda x: "/usr/bin/claude",
        plugin_registry_path=missing,
    )
    assert state == "single"
    assert detail == "oss-channel"


def test_an_unreadable_plugin_population_is_could_not_ask_not_a_clean_single(
    tmp_path,
):
    """The defect class this repository is named after: a `claude mcp list`
    read that succeeded must not paper over a plugin-population half that
    could not be established -- rendering `single` here would silently arm
    a collision this whole check exists to catch."""
    path = tmp_path / "installed_plugins.json"
    path.write_text("{not json", encoding="utf-8")
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(ONE_MCP_LIST_ROW),
        which=lambda x: "/usr/bin/claude",
        plugin_registry_path=str(path),
    )
    assert state == "could-not-ask"
    assert detail


def test_check_channel_consumer_census_reports_collision_naming_the_plugin(
    tmp_path,
):
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install_dir)}]}
    )
    doctor.check_channel_consumer_census(
        run=_run_answering(ONE_MCP_LIST_ROW),
        which=lambda x: "/usr/bin/claude",
        plugin_registry_path=registry,
    )
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN"
    assert "plugin:supertool@dpt-plugins:claude-channel" in message


def test_the_same_plugin_key_installed_many_times_counts_once(tmp_path):
    """#1241 self-review finding, dogfooded against this machine's own real
    registry: `installed_plugins.json` records one row per project that
    ever installed a plugin, plus every version ever installed -- this
    machine's own real registry carried 17 rows for a single plugin key,
    mostly repeating the same installPath. Each row must not be counted as
    a separate consumer: only one label per (key, server) name, however
    many install-path rows produced it."""
    install_dir = tmp_path / "supertool" / "0.57.0"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    # Three registry rows, same plugin key, same installPath -- exactly the
    # shape a per-project install history produces.
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {"installPath": str(install_dir)},
                {"installPath": str(install_dir)},
                {"installPath": str(install_dir)},
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]


def test_two_distinct_plugins_shipping_a_consumer_are_both_counted(tmp_path):
    """Must-fire positive control paired with the dedup test above: TWO
    different plugin keys, each genuinely shipping a claude-channel
    consumer, must still both be reported -- dedup must not fold distinct
    plugins into one."""
    first = tmp_path / "plugin-a"
    second = tmp_path / "plugin-b"
    _mcp_json(
        first,
        {
            "claude-channel": _channel_server(
                str(first / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    _mcp_json(
        second,
        {
            "claude-channel": _channel_server(
                str(second / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path,
        {
            "plugin-a@marketplace": [{"installPath": str(first)}],
            "plugin-b@marketplace": [{"installPath": str(second)}],
        },
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert reason is None
    assert set(names) == {
        "plugin:plugin-a@marketplace:claude-channel",
        "plugin:plugin-b@marketplace:claude-channel",
    }
