"""#1307: `bin/oss-workspace` registers `oss-channel` unconditionally and only
asks afterward whether anything else also resolves to the claude-channel
consumer script -- so on a machine where an installed plugin already ships one
in its own `.mcp.json`, the launcher's own registration is the second consumer
the post-registration census (#1241) then counts, and it disarms the channel
over the collision it just created.

`plugin_channel_arm_decision` (this file) is the pre-registration half:
called BEFORE oss-channel is registered, over the exact in-scope plugin
population `_plugin_channel_consumer_names` already derives, so the launcher
can skip registering oss-channel when a plugin consumer already covers it and
arm the flag against that one instead.

`resolvable_plugin_server_name` closes a second, adjacent gap: the label
`_plugin_channel_consumer_names` reports (`plugin:<key>:<server>`, built from
the installed-plugin registry's own `<name>@<marketplace>` key) is not a name
`claude mcp get`/`--dangerously-load-development-channels server:NAME`
resolves -- verified live against claude 2.1.261:
`claude mcp get "plugin:supertool@dpt-plugins:claude-channel"` refuses ("No
MCP server named ..."), while `claude mcp get "plugin:supertool:claude-channel"`
(the bare plugin name, no marketplace) resolves. Every "must not fire" case
here is paired with a "must fire" case in the same fixture shape, per
CLAUDE.md's own rule that a negative assertion needs a positive control.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402,F401
import doctor_check_mcp_channel_registration as mod  # noqa: E402


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


# --------------------------------------------- resolvable_plugin_server_name


def test_strips_the_marketplace_qualifier():
    assert (
        mod.resolvable_plugin_server_name("plugin:supertool@dpt-plugins:claude-channel")
        == "plugin:supertool:claude-channel"
    )


def test_a_label_with_no_marketplace_qualifier_is_left_alone():
    """Must-not-fire control: a registry key with no `@` (should not exist in
    practice, but nothing here assumes it cannot) must not be mangled."""
    assert (
        mod.resolvable_plugin_server_name("plugin:supertool:claude-channel")
        == "plugin:supertool:claude-channel"
    )


def test_an_at_sign_inside_the_server_segment_is_never_touched():
    """Self-review finding on the auditor's own class-C check: an earlier
    version matched the first `@...:`-shaped substring ANYWHERE in the
    label, so a registry `key` with no `@` combined with a `<server>`
    segment that happens to contain one stripped a chunk out of the SERVER
    name instead of a marketplace qualifier. `<server>` is a JSON object key
    read verbatim out of a plugin's own `.mcp.json`
    (`_plugin_channel_consumer_names` does no shape check on it), so it is
    attacker/plugin-shapable data crossing into a function whose docstring
    promises it never mangles it. This is the exact adversarial shape: no
    `@` in the key, one in the server segment."""
    assert (
        mod.resolvable_plugin_server_name("plugin:legacykey:weird@evil:server")
        == "plugin:legacykey:weird@evil:server"
    )


# ------------------------------------------------- plugin_channel_arm_decision


def test_no_registry_is_none_not_could_not_ask(tmp_path):
    missing = str(tmp_path / "does-not-exist.json")
    state, _detail = mod.plugin_channel_arm_decision(missing)
    assert state == "none"


def test_zero_in_scope_plugin_consumers_is_none(tmp_path):
    registry = _registry(
        tmp_path, {"some-plugin@marketplace": [{"installPath": str(tmp_path / "p")}]}
    )
    (tmp_path / "p").mkdir()
    state, _detail = mod.plugin_channel_arm_decision(registry)
    assert state == "none"


def test_one_in_scope_plugin_consumer_is_single_and_names_the_resolvable_target(
    tmp_path,
):
    install = tmp_path / "supertool"
    script = str(install / "notifiers" / "claude-channel" / "channel.ts")
    _mcp_json(install, {"claude-channel": _channel_server(script)})
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install)}]}
    )
    state, detail = mod.plugin_channel_arm_decision(registry)
    assert state == "single"
    label, resolvable = detail
    assert label == "plugin:supertool@dpt-plugins:claude-channel"
    assert resolvable == "plugin:supertool:claude-channel"


def test_two_in_scope_plugin_consumers_is_plural(tmp_path):
    install_a = tmp_path / "a"
    install_b = tmp_path / "b"
    _mcp_json(
        install_a,
        {
            "claude-channel": _channel_server(
                str(install_a / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    _mcp_json(
        install_b,
        {
            "claude-channel": _channel_server(
                str(install_b / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path,
        {
            "plugin-a@marketplace": [{"installPath": str(install_a)}],
            "plugin-b@marketplace": [{"installPath": str(install_b)}],
        },
    )
    state, detail = mod.plugin_channel_arm_decision(registry)
    assert state == "plural"
    assert len(detail) == 2


def test_an_unreadable_registry_is_could_not_ask_not_none(tmp_path):
    """Must-not-fire control's positive twin: a registry that could not be read
    must never read as "no plugin consumer" -- that would silently stop
    registering the only one there is."""
    path = tmp_path / "installed_plugins.json"
    path.write_text("{not json", encoding="utf-8")
    state, detail = mod.plugin_channel_arm_decision(str(path))
    assert state == "could-not-ask"
    assert detail


def test_project_scope_filters_to_the_given_project_dir(tmp_path):
    """The population is scoped the same way #1241's own `_entry_in_scope`
    scopes it -- a plugin install pinned to a DIFFERENT project must not
    count toward THIS project's arm decision."""
    install = tmp_path / "supertool"
    _mcp_json(
        install,
        {
            "claude-channel": _channel_server(
                str(install / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    other_project = tmp_path / "other-project"
    this_project = tmp_path / "this-project"
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {
                    "scope": "project",
                    "installPath": str(install),
                    "projectPath": str(other_project),
                }
            ]
        },
    )
    state, _detail = mod.plugin_channel_arm_decision(
        registry, project_dir=str(this_project)
    )
    assert state == "none"
