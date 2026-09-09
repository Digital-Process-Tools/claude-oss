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


def test_a_server_name_with_a_control_character_is_a_reason_not_a_label(tmp_path):
    """#1339: `_plugin_channel_consumer_names` is the ONE place a
    `plugin:<key>:<server>` label is built, and it has (at least) two
    independent callers -- `plugin_channel_arm_decision` and
    `channel_consumer_census_state`, below -- each of which transports a
    label to a positional shell readback. A control character embedded in
    `server_name` (a raw JSON object key out of a plugin's own `.mcp.json`,
    read verbatim with no shape check) must never survive into a returned
    label: reject it here, at the source, so every caller inherits the
    protection rather than needing its own copy of the check."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "chan\nINJECTED": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install_dir)}]}
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert names is None
    assert reason
    assert "\n" not in reason


def test_a_registry_key_with_a_control_character_is_also_a_reason(tmp_path):
    """Must-fire twin: the control character can arrive via the registry's
    own `key` segment instead of the server name -- both are data this
    process does not control."""
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
        tmp_path,
        {"supertool@dpt-plugins\nINJECTED": [{"installPath": str(install_dir)}]},
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert names is None
    assert reason


def test_an_ordinary_odd_looking_server_name_is_still_found(tmp_path):
    """Positive control: a server name that is unusual but carries no
    control character (colons, an `@`, unicode) must still be found
    normally -- the new check must not become a second false-positive
    source over ordinary but odd-looking names."""
    install_dir = tmp_path / "supertool"
    server_name = "weird:name@v2-étoile"
    _mcp_json(
        install_dir,
        {
            server_name: _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    registry = _registry(
        tmp_path, {"supertool@dpt-plugins": [{"installPath": str(install_dir)}]}
    )
    names, reason = mod._plugin_channel_consumer_names(registry)
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:" + server_name]


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


def test_a_control_character_in_a_plugin_label_is_could_not_ask_not_collision(
    tmp_path,
):
    """#1339: `channel_consumer_census_state` is a SECOND, independent
    caller of `_plugin_channel_consumer_names` -- the fix that closed the
    injection at `plugin_channel_arm_decision` alone (an earlier self-review
    round of this diff) left this call site still folding a tainted label
    straight into `collision`'s `detail` list, which `bin/oss-workspace`'s
    own `CHANNEL_CENSUS` heredoc then echoes unsanitised. Now that the
    rejection lives in `_plugin_channel_consumer_names` itself, this call
    site inherits it automatically: a tainted label must surface as
    `could-not-ask`, the same safe fallback an unreadable registry already
    produces, never as a `collision` (or `single`) carrying corrupted text."""
    install_dir = tmp_path / "supertool" / "0.57.0"
    _mcp_json(
        install_dir,
        {
            "chan\nINJECTED": _channel_server(
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
    assert state == "could-not-ask"
    assert detail
    assert "\n" not in detail


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


# --------------------------------------------------------- project-scope filtering (self-review)


def test_a_project_scoped_row_for_a_different_project_is_excluded(tmp_path):
    """Self-review finding (Explore reviewer spawn, against this machine's own
    real registry): a `"scope": "project"` row pinned to a DIFFERENT project
    than the one doctor is running over must never be counted -- it can
    never actually be loaded into THIS session."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    this_project = tmp_path / "this-repo"
    other_project = tmp_path / "some-other-repo"
    this_project.mkdir()
    other_project.mkdir()
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {
                    "scope": "project",
                    "projectPath": str(other_project),
                    "installPath": str(install_dir),
                }
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(
        registry, project_dir=str(this_project)
    )
    assert reason is None
    assert names == []


def test_a_project_scoped_row_for_this_project_is_included(tmp_path):
    """Must-fire positive control paired with the exclusion test above: the
    SAME shape, but `projectPath` matches `project_dir` -- must still be
    counted."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    this_project = tmp_path / "this-repo"
    this_project.mkdir()
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {
                    "scope": "project",
                    "projectPath": str(this_project),
                    "installPath": str(install_dir),
                }
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(
        registry, project_dir=str(this_project)
    )
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]


def test_a_local_scoped_row_for_a_different_project_is_excluded(tmp_path):
    """`"scope": "local"` is the same per-project shape as `"project"` and
    must be filtered identically."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    this_project = tmp_path / "this-repo"
    other_project = tmp_path / "some-other-repo"
    this_project.mkdir()
    other_project.mkdir()
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {
                    "scope": "local",
                    "projectPath": str(other_project),
                    "installPath": str(install_dir),
                }
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(
        registry, project_dir=str(this_project)
    )
    assert reason is None
    assert names == []


def test_a_user_scoped_row_is_always_included_regardless_of_project(tmp_path):
    """Must-fire positive control: `"scope": "user"` is loaded into every
    session regardless of which project it opens over, and must never be
    filtered out by a project_dir comparison."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    this_project = tmp_path / "this-repo"
    this_project.mkdir()
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {
                    "scope": "user",
                    "installPath": str(install_dir),
                }
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(
        registry, project_dir=str(this_project)
    )
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]


def test_no_project_dir_given_applies_no_scope_filtering_at_all(tmp_path):
    """When the caller has no directory to compare against, every row stays
    in scope -- the pre-fix behaviour -- rather than silently narrowing the
    population past what could actually be established."""
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
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {
                    "scope": "project",
                    "projectPath": str(tmp_path / "unrelated-project"),
                    "installPath": str(install_dir),
                }
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(registry, project_dir=None)
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]


def test_a_project_scoped_row_with_no_recorded_project_path_stays_in_scope(tmp_path):
    """A project/local-scoped row that carries no `projectPath` at all cannot
    be compared -- conservatively kept in scope rather than silently
    dropped, the same "unreadable neighbour must not send you to the wrong
    absence" caution this module's other helpers already take."""
    install_dir = tmp_path / "supertool"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    this_project = tmp_path / "this-repo"
    this_project.mkdir()
    registry = _registry(
        tmp_path,
        {
            "supertool@dpt-plugins": [
                {"scope": "project", "installPath": str(install_dir)}
            ]
        },
    )
    names, reason = mod._plugin_channel_consumer_names(
        registry, project_dir=str(this_project)
    )
    assert reason is None
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]


def test_this_machines_own_multi_project_shape_no_longer_overcounts(tmp_path):
    """The exact shape found dogfooding this fix against this machine's own
    real `~/.claude/plugins/installed_plugins.json`: one plugin key with
    MANY rows -- one `user` scope, several `project`/`local` scope rows each
    pinned to a different, unrelated project. Only the user-scope row (and
    any row genuinely pinned to `project_dir`) may count; the doctor.py
    census run over THIS project must not see the other five projects'
    installs at all."""
    install_dir = tmp_path / "supertool" / "0.57.0"
    old_install_dir = tmp_path / "supertool" / "0.40.0"
    _mcp_json(
        install_dir,
        {
            "claude-channel": _channel_server(
                str(install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    _mcp_json(
        old_install_dir,
        {
            "claude-channel": _channel_server(
                str(old_install_dir / "notifiers" / "claude-channel" / "channel.ts")
            )
        },
    )
    this_project = tmp_path / "claude-oss"
    this_project.mkdir()
    other_projects = [tmp_path / name for name in ("dvsi", "claude-remember")]
    for p in other_projects:
        p.mkdir()
    rows = [{"scope": "user", "installPath": str(install_dir)}]
    rows.append(
        {
            "scope": "project",
            "projectPath": str(this_project),
            "installPath": str(install_dir),
        }
    )
    for p in other_projects:
        rows.append(
            {
                "scope": "project",
                "projectPath": str(p),
                "installPath": str(old_install_dir),
            }
        )
    registry = _registry(tmp_path, {"supertool@dpt-plugins": rows})
    names, reason = mod._plugin_channel_consumer_names(
        registry, project_dir=str(this_project)
    )
    assert reason is None
    # Deduped to one label: the user-scope row and the this-project row both
    # resolve to the identical install (0.57.0) and the identical label.
    assert names == ["plugin:supertool@dpt-plugins:claude-channel"]
