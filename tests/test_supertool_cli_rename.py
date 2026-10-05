"""The supertool plugin is published as `supertool-cli` in the dpt-plugins marketplace.

The marketplace renamed it from `supertool` (dpt-plugins PR #7). A manifest still
declaring `supertool` asks the harness for `supertool@dpt-plugins`, which no longer
exists, and every install of this plugin then shows a dependency error. Installs
registered under the old key must still be recognised, so every name check here
accepts both spellings.
"""

import json
from pathlib import Path

import doctor

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/Digital-Process-Tools/claude-supertool"


def _declared():
    manifest = ROOT / ".claude-plugin" / "plugin.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["dependencies"]


def test_manifest_declares_the_published_name():
    deps = _declared()
    assert "supertool-cli" in deps, deps
    assert "supertool" not in deps, deps


def test_every_declared_dependency_has_a_diagnostic_route():
    missing = [
        name for name in _declared() if name not in doctor.DEPENDENCY_DIAGNOSTICS
    ]
    assert missing == [], missing


def test_both_names_are_supertool_plugin_keys():
    assert doctor.is_supertool_plugin_key("supertool-cli@dpt-plugins")
    assert doctor.is_supertool_plugin_key("supertool@dpt-plugins")
    assert not doctor.is_supertool_plugin_key("supertool-extra@dpt-plugins")
    assert not doctor.is_supertool_plugin_key("remember@dpt-plugins")


def _fake_git_remote(argv, **kwargs):
    class Result:
        returncode = 0
        stdout = "git@github.com:Digital-Process-Tools/claude-supertool.git\n"
        stderr = ""

    return Result()


def test_identity_check_reads_the_new_name(tmp_path):
    confirmed, reason = doctor._supertool_tree_identity_confirmed(
        tmp_path, dependency_repos={"supertool-cli": REPO}, run=_fake_git_remote
    )
    assert (confirmed, reason) == (True, None)


def test_identity_check_still_reads_the_old_name(tmp_path):
    confirmed, reason = doctor._supertool_tree_identity_confirmed(
        tmp_path, dependency_repos={"supertool": REPO}, run=_fake_git_remote
    )
    assert (confirmed, reason) == (True, None)


def test_launcher_accepts_both_registry_keys():
    text = (ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")
    assert 'key.split("@")[0] != "supertool"' not in text
    assert text.count('key.split("@")[0] not in ("supertool-cli", "supertool")') == 2
