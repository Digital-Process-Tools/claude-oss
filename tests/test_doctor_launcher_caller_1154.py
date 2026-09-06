"""#1154: `/oss:doctor` tells every launcher-updated session to run
`/reload-plugins`, which clears nothing when the update already ran BEFORE this
session started.

`bin/oss-workspace` calls `scripts/plugin_update.py` synchronously, before
`exec claude` (#753) -- by the time this session's own process starts, whatever
`claude plugin update` did is already what a fresh plugin load resolves. There
is no old-copy window for `/reload-plugins` to close. That sentence is correct
only for `hooks/session-start-update.sh`'s async, mid-session caller, where an
update genuinely lands under a session that already loaded its registry.

Fix: `update()`/`main()` now accept a `caller` value, written onto the receipt
as `document["caller"]`, and `bin/oss-workspace` passes `--caller launcher` on
its synchronous call. `doctor_check_auto_update.py`'s two "updated" branches
(the plugin row and the dependency row) read it back: `caller == "launcher"`
never claims `/reload-plugins` will do anything for *this* session; anything
else (absent, "hook", or an old receipt written before this fix existed) keeps
the original assertive message -- the positive control paired with the
negative one below, in the same fixture family #553 already established.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import plugin_update  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


def _plugins_root(tmp_path, version):
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        __import__("json").dumps(
            {"plugins": {"oss@dpt-plugins": [{"version": version, "installPath": "x"}]}}
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


def test_update_records_the_caller_it_was_given(tmp_path):
    """MUST FIRE: `caller="launcher"` passed to `update()` lands on the receipt."""
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
        caller="launcher",
    )
    assert document["state"] == "updated"
    assert document["caller"] == "launcher"


def test_update_with_no_caller_given_records_none(tmp_path):
    """The must-not-fire control: a call that names no caller (the async hook's
    own call site, unchanged) must not accidentally read as the launcher."""
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
    assert document.get("caller") != "launcher"


def test_main_forwards_a_caller_flag_to_update(tmp_path, monkeypatch):
    """`main()` is what `bin/oss-workspace` actually invokes -- the `--caller`
    argv flag must reach `update()` as the `caller=` keyword."""
    captured = {}

    def fake_update(**kwargs):
        captured.update(kwargs)
        return {"state": "current", "at": 0.0, "plugin": "oss", "detail": ""}

    monkeypatch.setattr(plugin_update, "update", fake_update)
    monkeypatch.setattr(plugin_update, "write_receipt", lambda document: None)
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    rc = plugin_update.main(
        ["--root", str(tmp_path), "--caller", "launcher", "--print-state"]
    )
    assert rc == 0
    assert captured.get("caller") == "launcher"


# --------------------------------------------------- scripts/doctor_check_auto_update.py


def test_check_auto_update_hook_receipt_still_recommends_reload(monkeypatch):
    """POSITIVE CONTROL: a receipt shaped as the async hook's own (no `caller`,
    or `caller` explicitly `"hook"`) must still tell a maintainer to
    `/reload-plugins` -- this is the case #553 already fixed and must not
    regress."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "updated",
            "plugin": "oss",
            "from": "0.11.0",
            "to": "0.12.0",
        },
    )
    doctor.check_auto_update(".")
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "/reload-plugins" in message, message


def test_check_auto_update_launcher_receipt_does_not_claim_reload_helps(monkeypatch):
    """NEGATIVE CONTROL, the bug itself: a receipt the launcher wrote
    synchronously, before `exec claude`, must not tell THIS session to run
    `/reload-plugins` -- there is no old copy running to reload out of."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "updated",
            "plugin": "oss",
            "from": "0.11.0",
            "to": "0.12.0",
            "caller": "launcher",
        },
    )
    doctor.check_auto_update(".")
    state, message = doctor.FINDINGS[0]
    assert "/reload-plugins" not in message, message


def test_dependency_row_hook_receipt_still_recommends_reload(monkeypatch):
    """POSITIVE CONTROL for the dependency row (#605's own row, fixed
    half-heartedly by #1154's own bug report if only the plugin row moved)."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "current",
            "plugin": "oss",
            "from": "0.12.0",
            "to": "0.12.0",
            "dependencies": [
                {"name": "supertool", "state": "updated", "from": "1.0", "to": "1.1"}
            ],
        },
    )
    doctor.check_auto_update(".")
    messages = [msg for _, msg in doctor.FINDINGS]
    assert any("/reload-plugins" in m for m in messages), messages


def test_dependency_row_launcher_receipt_does_not_claim_reload_helps(monkeypatch):
    """NEGATIVE CONTROL, the dependency-row half of the same bug: `_report_
    dependencies` branched on `state` alone too, so a half-fix here is exactly
    what the issue warns against."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "current",
            "plugin": "oss",
            "from": "0.12.0",
            "to": "0.12.0",
            "caller": "launcher",
            "dependencies": [
                {"name": "supertool", "state": "updated", "from": "1.0", "to": "1.1"}
            ],
        },
    )
    doctor.check_auto_update(".")
    messages = [msg for _, msg in doctor.FINDINGS]
    assert not any("/reload-plugins" in m for m in messages), messages
