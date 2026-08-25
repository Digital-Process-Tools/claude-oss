"""#547 instance 1 -- `checklist_skew.DEFINITION_FILES` was a fixed list beside
the set the gate actually depends on, and it was short by `agents/developer.md`,
which `agents/auditor.md` delegates its whole platform band to (by naming it in
prose, not by reading it). The docstring at `:81` (pre-fix) claimed the list was
"fixed to what this gate depends on"; it was short by one file.

Fixed by deriving the comparison set from what the three base files actually
reference (`agents/*.md` paths named in their own text), not from a second list
kept beside `DEFINITION_FILES`. The must-fire control from the issue: add a new
reference to one of the base files without touching the derivation code, and the
new file must be picked up and compared.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import checklist_skew  # noqa: E402


def _manifest(root, version):
    import json

    manifest_dir = Path(root) / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": version}), encoding="utf-8"
    )


def test_a_file_named_only_in_prose_is_still_compared(tmp_path):
    """The must-fire control (#547): `agents/auditor.md` names
    `agents/developer.md` in its own text without this gate reading it
    directly. That referenced file must appear in `definitions`, and its own
    drift must be reported -- not silently absorbed into "nothing to compare".
    """
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    (plugin_root / "agents").mkdir(parents=True)
    (repo / "agents").mkdir(parents=True)

    reference_text = "Read `agents/developer.md` under its cross-platform section."
    (plugin_root / "agents" / "auditor.md").write_text(reference_text, encoding="utf-8")
    (repo / "agents" / "auditor.md").write_text(reference_text, encoding="utf-8")

    (plugin_root / "agents" / "developer.md").write_text("old platform band", encoding="utf-8")
    (repo / "agents" / "developer.md").write_text("new platform band", encoding="utf-8")

    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == "differs"
    rows = {row["path"]: row["state"] for row in payload["definitions"]}
    assert "agents/developer.md" in rows, rows
    assert rows["agents/developer.md"] == "differs", rows


def test_a_file_not_referenced_anywhere_is_not_added(tmp_path):
    """The negative control's own control: a file that happens to sit next to
    the referenced ones but is never named must not silently widen the set --
    otherwise the derivation would just be "compare every agents/*.md file",
    which is a different (and untested-here) claim.
    """
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    (plugin_root / "agents").mkdir(parents=True)
    (repo / "agents").mkdir(parents=True)

    (plugin_root / "agents" / "auditor.md").write_text("no references here", encoding="utf-8")
    (repo / "agents" / "auditor.md").write_text("no references here", encoding="utf-8")

    # Present on disk, unreferenced anywhere, and different content -- if the
    # derivation swept the whole directory this would show up as `differs`.
    (plugin_root / "agents" / "triager.md").write_text("old", encoding="utf-8")
    (repo / "agents" / "triager.md").write_text("new", encoding="utf-8")

    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == "differs"
    rows = {row["path"]: row["state"] for row in payload["definitions"]}
    assert "agents/triager.md" not in rows, rows


def test_a_reference_found_only_in_the_installed_copy_is_still_derived(tmp_path):
    """A reference has to be findable from EITHER tree, not just the repo's --
    a repository without its own copy of `agents/auditor.md` (the ordinary
    case for most managed repos, per the module docstring) still gets the
    installed copy's references derived.
    """
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    (plugin_root / "agents").mkdir(parents=True)
    # repo has no agents/ directory at all.

    (plugin_root / "agents" / "auditor.md").write_text(
        "Read `agents/developer.md`.", encoding="utf-8"
    )
    (plugin_root / "agents" / "developer.md").write_text("installed only", encoding="utf-8")

    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == "differs"
    rows = {row["path"]: row["state"] for row in payload["definitions"]}
    assert "agents/developer.md" in rows, rows
    # repo has no copy -> could-not-tell, not silently dropped
    assert rows["agents/developer.md"] == "could-not-tell", rows


def test_a_reference_named_only_in_the_other_copy_is_still_derived(tmp_path):
    """Self-review finding on the auditor round: when BOTH trees carry a base
    file and they DIFFER -- exactly the `differs` state this function only
    runs under -- a reference named only in one copy's text must still be
    picked up, not just whichever tree happened to resolve first. The first
    version of this derivation broke out of the per-file loop on the first
    successful read, so a stale `repo` copy that had not yet grown a
    delegation silently hid a reference the newer `plugin_root` copy already
    carried -- the identical "coverage set narrower than what it depends on"
    shape #547 exists to close, reproduced one level down inside its own fix.
    """
    plugin_root = tmp_path / "plugin"
    repo = tmp_path / "repo"
    _manifest(plugin_root, "9.9.8")
    _manifest(repo, "9.9.9")

    (plugin_root / "agents").mkdir(parents=True)
    (repo / "agents").mkdir(parents=True)

    # repo's copy is stale: no delegation yet.
    (repo / "agents" / "auditor.md").write_text("no references here yet", encoding="utf-8")
    # plugin_root's copy already grew the delegation this issue is about.
    (plugin_root / "agents" / "auditor.md").write_text(
        "Read `agents/developer.md`.", encoding="utf-8"
    )
    (plugin_root / "agents" / "developer.md").write_text("installed copy", encoding="utf-8")
    (repo / "agents" / "developer.md").write_text("repo copy", encoding="utf-8")

    payload = checklist_skew.compute(repo=str(repo), plugin_root=str(plugin_root))

    assert payload["state"] == "differs"
    rows = {row["path"]: row["state"] for row in payload["definitions"]}
    assert "agents/developer.md" in rows, rows
    assert rows["agents/developer.md"] == "differs", rows
