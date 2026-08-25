"""#538: nothing compared the auditing plugin's version to the tree it audits.

`commands/release.md` gate 3 already requires the checklist version to be recorded
before the release-auditor spawn, in three states -- matches / differs / could not
tell -- and says the honest answer is always "could not tell" when nothing measures
it. This pins the module that performs the read: `scripts/checklist_skew.py`.

Every case that reports one state also reports a different one in the same shape,
one mutation away -- a positive control beside each negative one, so a fixture that
silently measured nothing cannot pass by reporting the safe answer regardless of
what is on disk.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "checklist_skew.py"

MATCHES = "matches"
DIFFERS = "differs"
COULD_NOT_TELL = "could-not-tell"


def _module():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import checklist_skew

    return checklist_skew


def test_script_exists():
    assert SCRIPT.is_file(), "scripts/checklist_skew.py is missing"


def _manifest(root, version):
    manifest_dir = Path(root) / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": version}), encoding="utf-8"
    )


# ------------------------------------------------------------------------- matches


def test_matches_when_versions_agree(tmp_path):
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.9")
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == MATCHES
    assert payload["installed_version"] == "9.9.9"
    assert payload["repo_version"] == "9.9.9"
    assert payload["definitions"] is None


# ------------------------------------------------------------------------- differs


def test_differs_when_versions_disagree_and_names_both(tmp_path):
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == DIFFERS
    assert payload["installed_version"] == "9.9.8"
    assert payload["repo_version"] == "9.9.9"
    assert "9.9.8" in payload["reason"]
    assert "9.9.9" in payload["reason"]


# ------------------------------------------------------------------ could not tell


def test_could_not_tell_when_plugin_root_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    repo = tmp_path / "repo"
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=None)

    assert payload["state"] == COULD_NOT_TELL
    assert payload["installed_version"] is None
    # It never renders as a match just because nothing could be told.
    assert payload["state"] != MATCHES


def test_could_not_tell_when_installed_manifest_absent(tmp_path):
    plugin_root = tmp_path / "plugin"  # no manifest written
    repo = tmp_path / "repo"
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == COULD_NOT_TELL
    assert payload["installed_version"] is None


def test_could_not_tell_when_installed_manifest_unreadable_json(tmp_path):
    plugin_root = tmp_path / "plugin"
    manifest_dir = plugin_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text("not json", encoding="utf-8")
    repo = tmp_path / "repo"
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == COULD_NOT_TELL


def test_could_not_tell_when_repo_manifest_absent(tmp_path):
    """The ordinary case for a repo that only installed the plugin: it never
    shipped a .claude-plugin/plugin.json of its own, so there is no second
    number on its disk to compare against -- and that must not read as a match.
    """
    plugin_root = tmp_path / "plugin"
    _manifest(plugin_root, "9.9.9")
    repo = tmp_path / "repo"  # no manifest written -- repo does not ship definitions

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == COULD_NOT_TELL
    assert payload["installed_version"] == "9.9.9"
    assert payload["repo_version"] is None


# ---------------------------------------------------------- plugin_root source


def test_plugin_root_arg_takes_precedence_over_env(tmp_path, monkeypatch):
    arg_root = tmp_path / "arg-plugin"
    env_root = tmp_path / "env-plugin"
    _manifest(arg_root, "9.9.9")
    _manifest(env_root, "9.9.7")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(env_root))
    repo = tmp_path / "repo"
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(arg_root))

    assert payload["installed_version"] == "9.9.9"
    assert payload["plugin_root_source"] == "--plugin-root"


def test_plugin_root_falls_back_to_env(tmp_path, monkeypatch):
    env_root = tmp_path / "env-plugin"
    _manifest(env_root, "9.9.9")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(env_root))
    repo = tmp_path / "repo"
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=None)

    assert payload["state"] == MATCHES
    assert payload["plugin_root_source"] == "CLAUDE_PLUGIN_ROOT"


# ------------------------------------------------------------- definitions evidence


def test_differs_reports_per_definition_identical_and_differs(tmp_path):
    """Positive control beside the negative one, in the same fixture: one
    definition file is made byte-identical between the two trees and one is
    made to differ, so a comparison that reported "identical" for everything
    regardless of content cannot pass this alone.
    """
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    (plugin_root / "agents").mkdir(parents=True)
    (repo / "agents").mkdir(parents=True)
    (plugin_root / "agents" / "release-auditor.md").write_text("same", encoding="utf-8")
    (repo / "agents" / "release-auditor.md").write_text("same", encoding="utf-8")
    (plugin_root / "agents" / "auditor.md").write_text("old text", encoding="utf-8")
    (repo / "agents" / "auditor.md").write_text("new text", encoding="utf-8")
    # skills/manager/SKILL.md left unwritten on both sides -> could-not-tell for that row

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == DIFFERS
    rows = {row["path"]: row["state"] for row in payload["definitions"]}
    assert rows["agents/release-auditor.md"] == "identical"
    assert rows["agents/auditor.md"] == "differs"
    assert rows["skills/manager/SKILL.md"] == COULD_NOT_TELL


def test_matches_never_computes_definitions(tmp_path):
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.9")
    _manifest(repo, "9.9.9")

    checklist_skew = _module()
    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["definitions"] is None


# --------------------------------------------------------------------------- CLI


def test_cli_json_and_exit_code_never_blocks(tmp_path):
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--plugin-root",
            str(plugin_root),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["state"] == DIFFERS


def test_cli_receipt_names_both_versions(tmp_path):
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--plugin-root", str(plugin_root)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "9.9.8" in done.stdout
    assert "9.9.9" in done.stdout


def test_cli_never_blocks_on_could_not_tell(tmp_path):
    repo = tmp_path / "repo"  # no manifest anywhere; plugin root unset
    repo.mkdir()

    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
        env={"PATH": ""},
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["state"] == COULD_NOT_TELL
