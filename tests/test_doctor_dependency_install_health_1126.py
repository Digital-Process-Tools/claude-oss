"""#1126: every currency check in `scripts/doctor.py` reads the install RECORD
(`installed_plugins.json`), never the TREE at the recorded path. `dependency_
resolution_state`'s own `repos` argument (whether *some* version of a
dependency, anywhere in the plugin cache, has a readable manifest) answers a
question that is blind to a truncated unpack of the specific version this
project's install record actually names: `repos.get(name)` is truthy the
moment ANY marketplace/version directory for that name has a manifest, even
if the active version's own directory is missing its `.claude-plugin/
plugin.json` entirely.

Fix: `dependency_resolution_state` additionally resolves the exact installed
directory for THIS project, via `plugin_update.resolved_plugin_root` (the
same accessor #677 built for exactly this "copy actually recorded as
installed" question), and stats for a manifest there. A directory that
resolves but has no manifest is `"broken-install"` -- reported as a finding,
never silently folded into `"resolves"`.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


def _plugins_root(tmp_path, version, marketplace="dpt-plugins", name="supertool"):
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps(
            {"plugins": {"{}@{}".format(name, marketplace): [{"version": version}]}}
        ),
        encoding="utf-8",
    )
    return root


def _cache_dir(plugins_root, version, marketplace="dpt-plugins", name="supertool"):
    path = plugins_root / "cache" / marketplace / name / version
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_a_truncated_unpack_at_the_active_version_is_not_reported_as_resolving(
    tmp_path,
):
    """MUST FIRE, the bug itself: the install record names 9.9.9 as active, the
    cache directory for 9.9.9 exists (so the unpack at least started), but it
    has no `.claude-plugin/plugin.json` -- a truncated/incomplete unpack. This
    must not read as `resolves`."""
    plugins_root = _plugins_root(tmp_path, "9.9.9")
    _cache_dir(plugins_root, "9.9.9")  # no plugin.json written inside
    findings = doctor.dependency_resolution_state(
        ["supertool"],
        record=plugins_root / "installed_plugins.json",
        repos={"supertool": "dpt-plugins/claude-supertool"},
        project_dir=tmp_path / "project",
        plugins_root=plugins_root,
    )
    assert findings == [
        {"name": "supertool", "state": "broken-install", "version": "9.9.9"}
    ]


def test_a_complete_unpack_at_the_active_version_still_resolves(tmp_path):
    """POSITIVE CONTROL / must-not-fire: the same layout, but the cache
    directory for the active version genuinely has a manifest -- this must
    keep reading `resolves`, exactly as before #1126."""
    plugins_root = _plugins_root(tmp_path, "9.9.9")
    cache_dir = _cache_dir(plugins_root, "9.9.9")
    (cache_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "supertool"}), encoding="utf-8"
    )
    findings = doctor.dependency_resolution_state(
        ["supertool"],
        record=plugins_root / "installed_plugins.json",
        repos={"supertool": "dpt-plugins/claude-supertool"},
        project_dir=tmp_path / "project",
        plugins_root=plugins_root,
    )
    assert findings == [{"name": "supertool", "state": "resolves", "version": "9.9.9"}]


def test_no_project_dir_given_keeps_the_old_behaviour(tmp_path):
    """Every existing caller of `dependency_resolution_state` passes no
    `project_dir` at all -- the health check must be opt-in, not a silent
    behaviour change for callers that never asked for it."""
    plugins_root = _plugins_root(tmp_path, "9.9.9")
    _cache_dir(plugins_root, "9.9.9")  # truncated, but nobody is checking
    findings = doctor.dependency_resolution_state(
        ["supertool"],
        record=plugins_root / "installed_plugins.json",
        repos={"supertool": "dpt-plugins/claude-supertool"},
    )
    assert findings == [{"name": "supertool", "state": "resolves", "version": "9.9.9"}]


def test_check_dependency_resolution_reports_a_broken_install_as_a_finding(
    tmp_path, monkeypatch
):
    plugins_root = _plugins_root(tmp_path, "9.9.9")
    _cache_dir(plugins_root, "9.9.9")
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: ["supertool"])
    _reset()
    doctor.check_dependency_resolution(
        record=plugins_root / "installed_plugins.json",
        repos={"supertool": "dpt-plugins/claude-supertool"},
        project_dir=tmp_path / "project",
        plugins_root=plugins_root,
    )
    assert any(
        state == "WARN" and "supertool" in msg and "truncated" in msg
        for state, msg in doctor.FINDINGS
    ), doctor.FINDINGS
