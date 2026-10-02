"""#1804: `claude-jit-context` is renamed `jit-context`, and both names count.

The `claude-` prefix is reserved for Anthropic's own plugins, so the dependency
was renamed upstream (Digital-Process-Tools/claude-jit-context#452) and the DPT
marketplace maps the old name onto the new one. A user who has migrated and one
who has not must both read as having jit-context installed -- in the install
record, in the plugin cache, and in this plugin's own declared dependencies.
A name that merely ends in `jit-context` must not.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

NEW = "jit-context"
OLD = "claude-jit-context"
LOOKALIKE = "my-jit-context"
VERSION = "9.9.9"
LAYER = "01-oss"
#: A hook body naming our layer in its fixed list -- reads as `reads`.
NAMES = 'split("00-manual 01-oss 10-auto", layers, " ")\n'


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _install(tmp_path, name, install_path=True, hook=NAMES, script=None):
    """A fabricated cache unpack of `name` plus the install record naming it."""
    cache = tmp_path / "cache"
    plugin = cache / "dpt-plugins" / name / VERSION
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "pre-tool-hook.sh").write_text(hook, encoding="utf-8")
    if script is not None:
        (plugin / "scripts" / "jit-doctor.sh").write_text(script, encoding="utf-8")
    (plugin / "hooks").mkdir()
    command = "bash ${CLAUDE_PLUGIN_ROOT}/scripts/pre-tool-hook.sh"
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]
                }
            }
        ),
        encoding="utf-8",
    )
    entry = {"scope": "user", "version": VERSION}
    if install_path:
        entry["installPath"] = str(plugin)
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"{}@dpt-plugins".format(name): [entry]}}),
        encoding="utf-8",
    )
    return cache, record, plugin


def _project(tmp_path):
    root = tmp_path / "repo"
    for dimension in ("paths", "tools"):
        directory = root / ".claude" / "jit-context" / dimension / LAYER
        directory.mkdir(parents=True)
        (directory / "rule.md").write_text("---\n---\n", encoding="utf-8")
    return root


# --- the install record --------------------------------------------------------


@pytest.mark.parametrize("installed", [NEW, OLD])
def test_either_record_name_counts_as_the_declared_new_name(tmp_path, installed):
    _cache, record, _plugin = _install(tmp_path, installed)
    assert doctor.active_versions([NEW], record) == {NEW: VERSION}


def test_a_lookalike_record_name_does_not_count(tmp_path):
    """Negative control: the match is the whole name, not a suffix."""
    _cache, record, _plugin = _install(tmp_path, LOOKALIKE)
    assert doctor.active_versions([NEW], record) == {}
    assert doctor.active_versions([OLD], record) == {}


# --- where the running copy is unpacked ------------------------------------------


@pytest.mark.parametrize("installed", [NEW, OLD])
def test_jit_hook_roots_finds_either_name_through_install_path(tmp_path, installed):
    cache, record, plugin = _install(tmp_path, installed)
    assert doctor.jit_hook_roots(record, cache) == ([plugin], VERSION)


@pytest.mark.parametrize("installed", [NEW, OLD])
def test_jit_hook_roots_finds_either_name_through_the_cache_glob(tmp_path, installed):
    """No `installPath` in the record, so only the cache glob can answer."""
    cache, record, plugin = _install(tmp_path, installed, install_path=False)
    assert doctor.jit_hook_roots(record, cache) == ([plugin], VERSION)


def test_jit_hook_roots_ignores_a_lookalike(tmp_path):
    cache, record, _plugin = _install(tmp_path, LOOKALIKE, install_path=False)
    assert doctor.jit_hook_roots(record, cache) == ([], None)


# --- this plugin's own declared dependencies ---------------------------------------


@pytest.mark.parametrize("declared", [NEW, OLD])
@pytest.mark.parametrize("installed", [NEW, OLD])
def test_layer_verdict_reads_with_either_name_declared_and_installed(
    tmp_path, monkeypatch, declared, installed
):
    monkeypatch.setattr(
        doctor, "declared_dependencies", lambda: ["supertool", "remember", declared]
    )
    cache, record, _plugin = _install(tmp_path, installed)
    findings = doctor.jit_layer_readers(
        _project(tmp_path), record=record, cache_root=cache
    )
    assert [f["state"] for f in findings] == ["reads"], findings


def test_layer_verdict_refuses_when_only_a_lookalike_is_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor, "declared_dependencies", lambda: ["supertool", "remember", LOOKALIKE]
    )
    cache, record, _plugin = _install(tmp_path, NEW)
    findings = doctor.jit_layer_readers(
        _project(tmp_path), record=record, cache_root=cache
    )
    assert [f["state"] for f in findings] == ["could-not-determine"], findings
    assert "no longer a declared dependency" in findings[0]["detail"]


# --- its own diagnostic, relayed under its own three-state contract ---------------


class _Done:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


@pytest.mark.parametrize("declared", [NEW, OLD])
@pytest.mark.parametrize("installed", [NEW, OLD])
def test_diagnostic_relays_exit_1_under_either_name(tmp_path, declared, installed):
    """jit-doctor.sh's exit 1 is a documented verdict, not a failure to run --
    so it relays only if the name is recognised as jit-context's."""
    cache, record, _plugin = _install(tmp_path, installed, script="exit 1\n")
    state, detail = doctor.dependency_diagnostic_state(
        declared,
        tmp_path,
        record=record,
        cache_root=cache,
        run=lambda cmd, **kw: _Done(1, b"VERDICT: inert layer\n"),
        which=lambda name: "/bin/bash",
    )
    assert state == "relayed", (state, detail)
    assert "exit 1" in detail


def test_diagnostic_has_no_route_for_a_lookalike(tmp_path):
    cache, record, _plugin = _install(tmp_path, LOOKALIKE, script="exit 0\n")
    state, _detail = doctor.dependency_diagnostic_state(
        LOOKALIKE, tmp_path, record=record, cache_root=cache
    )
    assert state == "could-not-run"


# --- what this plugin itself names ------------------------------------------------


def test_manifest_declares_the_new_name_only():
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert NEW in manifest["dependencies"]
    assert OLD not in manifest["dependencies"]


def test_settings_enable_the_new_name_only():
    settings = json.loads(
        (REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    enabled = settings.get("enabledPlugins") or {}
    assert enabled.get("{}@dpt-plugins".format(NEW)) is True, enabled
    assert "{}@dpt-plugins".format(OLD) not in enabled, enabled
