"""#553: the two "restart Claude Code" messages never mention `/reload-plugins`, the
cheaper remedy `doctor.py` already names in three other places (around lines 3980,
3988 and 5421 in this tree -- the issue cited 3726-3727, 3734-3735 and 5166-5168,
which had already drifted by the time this landed; `doctor.py` is not in this issue's
scope so the citation is not pinned to line numbers anywhere the code enforces it).
#81's whole cost traces to a stale agent registry in an
unreloaded session, and the fix there was a restart -- but the message that told the
maintainer to restart never offered the cheap path first.

The constraint that makes this more than a string swap, from the issue and from
CLAUDE.md: `/reload-plugins` moves the **registry** (which agents/skills/commands
resolve) and does **not** move command text already injected into a running turn. A
message naming only `/reload-plugins` would trade one wrong answer (silence about the
cheap path) for another (implying the cheap path is a full substitute for a restart) --
so each assertion below is paired: the message must name both remedies, and must not
read as though `/reload-plugins` alone is enough.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import plugin_update  # noqa: E402


def _plugins_root(tmp_path, version):
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        __import__("json").dumps(
            {"plugins": {"oss@dpt": [{"version": version, "installPath": "x"}]}}
        ),
        encoding="utf-8",
    )
    return root


def _plugin_root(tmp_path, name="oss"):
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        __import__("json").dumps({"name": name, "version": "9.9.9"}), encoding="utf-8"
    )
    return root


# ------------------------------------------------------- scripts/plugin_update.py


def test_update_receipt_names_reload_plugins_for_the_updated_state(tmp_path):
    """The receipt `plugin_update.update()` writes for a real version change must name
    `/reload-plugins` as well as restart -- this is the updater's own record, read back
    by `doctor.check_auto_update` and by anyone inspecting the receipt file directly."""
    plugins = _plugins_root(tmp_path, "0.9.0")

    def runner(command, timeout=180):
        if command[:3] == ["claude", "plugin", "update"]:
            _plugins_root(tmp_path, "9.9.9")
        return True, ""

    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    assert document["state"] == "updated"
    detail = document["detail"]
    assert "/reload-plugins" in detail, detail
    assert "restart" in detail, detail


def test_update_receipt_does_not_present_reload_plugins_as_a_full_substitute(tmp_path):
    """The must-not-fire control paired with the test above: naming `/reload-plugins`
    is not enough on its own -- the detail must still say a restart remains necessary,
    so a maintainer who only reloads knows what is not yet fixed."""
    plugins = _plugins_root(tmp_path, "0.9.0")

    def runner(command, timeout=180):
        if command[:3] == ["claude", "plugin", "update"]:
            _plugins_root(tmp_path, "9.9.9")
        return True, ""

    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    detail = document["detail"]
    assert "still" in detail and "restart" in detail, (
        "detail names /reload-plugins but drops the restart still required: {!r}".format(
            detail
        )
    )


# --------------------------------------------------- scripts/doctor_check_auto_update.py


def _reset():
    doctor.FINDINGS.clear()


def test_check_auto_update_updated_message_names_reload_plugins(tmp_path, monkeypatch):
    """`doctor.check_auto_update`'s own "updated" message (built independently of the
    receipt's `detail`) must also name `/reload-plugins`, since this is the surface a
    maintainer reads on every session start (#81's own bill)."""
    _reset()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {"state": "updated", "plugin": "oss", "from": "0.11.0", "to": "0.12.0"},
    )
    doctor.check_auto_update(str(tmp_path))
    # Row 0 is the loop plugin's, which is this test's subject. #605 added a second row
    # about the declared dependencies; this receipt predates it and says nothing about
    # them, which that row states rather than rounding to a pass.
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "/reload-plugins" in message, message
    assert "restart" in message, message


def test_check_auto_update_updated_message_still_requires_a_restart(tmp_path, monkeypatch):
    """The must-not-fire control: the message must not read as though
    `/reload-plugins` alone closes the loop -- it must still say a restart is needed
    for what a reload cannot reach (command text already injected into the turn)."""
    _reset()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {"state": "updated", "plugin": "oss", "from": "0.11.0", "to": "0.12.0"},
    )
    doctor.check_auto_update(str(tmp_path))
    state, message = doctor.FINDINGS[0]
    assert "still" in message and "restart" in message, (
        "message names /reload-plugins but drops the restart still required: {!r}".format(
            message
        )
    )
