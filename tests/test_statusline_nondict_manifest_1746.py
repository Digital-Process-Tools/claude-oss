"""#1746: non-dict/non-object JSON in a manifest statusline.py reads must
not crash it -- confirmed as a live regression of claude-remember#727, whose
fix once lived only in the vendored `.oss/statusline.py` copy of a consuming
repo and was wiped out the next `scaffold.py --apply` resync. The canonical
fix belongs here, in `scripts/statusline.py`, so every vendored copy inherits
it rather than needing its own patch.

Six sites read a JSON file and call `.get(...)` (directly or via `.items()`)
on the result with no dict-type check: `.oss.json`, `.claude-plugin/plugin.json`
(twice: repo_version and the per-entry manifest inside installed_plugins),
`installed_plugins.json` (twice: installed_plugins and
_installed_plugin_root), and the base64-decoded `plugin.json` content
_latest_release fetches from the GitHub API. A JSON file need not be an
object -- `null`, a list, a string or a number are all valid JSON -- and each
site must treat that as "nothing useful here", never let it raise.

Each test below pairs the malformed case with a positive control: the same
function still returns real data for a well-formed dict, so a change that
made every case return an empty/None value unconditionally would not pass.
"""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def test_repo_config_returns_dict_for_null_oss_json(tmp_path):
    (tmp_path / ".oss.json").write_text("null", encoding="utf-8")
    assert statusline.repo_config(tmp_path) == {}


def test_repo_config_still_returns_real_dict_for_well_formed_json(tmp_path):
    (tmp_path / ".oss.json").write_text('{"repo": "a/b"}', encoding="utf-8")
    assert statusline.repo_config(tmp_path) == {"repo": "a/b"}


def test_repo_version_survives_non_dict_plugin_manifest(tmp_path):
    manifest_dir = tmp_path / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text("[1, 2, 3]", encoding="utf-8")
    with patch.object(statusline, "_run", return_value=None):
        assert statusline.repo_version(tmp_path) is None


def test_repo_version_still_reads_version_from_well_formed_manifest(tmp_path):
    manifest_dir = tmp_path / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
    assert statusline.repo_version(tmp_path) == "1.2.3"


def test_installed_plugins_survives_non_dict_top_level_doc(tmp_path):
    (tmp_path / "installed_plugins.json").write_text("42", encoding="utf-8")
    assert statusline.installed_plugins(None, plugins_root=tmp_path) == {}


def test_installed_plugins_survives_non_dict_plugins_key(tmp_path):
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps({"plugins": None}), encoding="utf-8"
    )
    assert statusline.installed_plugins(None, plugins_root=tmp_path) == {}


def test_installed_plugins_survives_non_dict_per_entry_manifest(tmp_path):
    install_dir = tmp_path / "install"
    (install_dir / ".claude-plugin").mkdir(parents=True)
    (install_dir / ".claude-plugin" / "plugin.json").write_text(
        '"just a string"', encoding="utf-8"
    )
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "demo@scope": [
                        {"version": "1.0.0", "installPath": str(install_dir)}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    with patch.object(statusline, "_entry_applies", return_value=True):
        found = statusline.installed_plugins(None, plugins_root=tmp_path)
    assert found["demo"]["version"] == "1.0.0"
    assert found["demo"]["repository"] is None


def test_installed_plugins_still_reads_real_entries(tmp_path):
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {"plugins": {"demo@scope": [{"version": "1.0.0", "installPath": None}]}}
        ),
        encoding="utf-8",
    )
    with patch.object(statusline, "_entry_applies", return_value=True):
        found = statusline.installed_plugins(None, plugins_root=tmp_path)
    assert found["demo"]["version"] == "1.0.0"


def test_installed_plugin_root_survives_non_dict_top_level_doc(tmp_path):
    (tmp_path / "installed_plugins.json").write_text("[1]", encoding="utf-8")
    assert (
        statusline._installed_plugin_root(None, "demo", plugins_root=tmp_path) is None
    )


def test_installed_plugin_root_still_resolves_real_entry(tmp_path):
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"demo@scope": [{"installPath": "/somewhere"}]}}),
        encoding="utf-8",
    )
    with patch.object(statusline, "_entry_applies", return_value=True):
        assert (
            statusline._installed_plugin_root(None, "demo", plugins_root=tmp_path)
            == "/somewhere"
        )


def test_latest_release_survives_non_dict_decoded_manifest():
    encoded = base64.b64encode(json.dumps([1, 2, 3]).encode("utf-8")).decode("ascii")
    with (
        patch.object(statusline, "_malformed_repo", return_value=False),
        patch.object(statusline, "_run", return_value=encoded),
    ):
        assert statusline._latest_release("owner/repo") is None


def test_latest_release_still_reads_version_from_well_formed_manifest():
    encoded = base64.b64encode(json.dumps({"version": "9.9.9"}).encode("utf-8")).decode(
        "ascii"
    )
    with (
        patch.object(statusline, "_malformed_repo", return_value=False),
        patch.object(statusline, "_run", return_value=encoded),
    ):
        assert statusline._latest_release("owner/repo") == "9.9.9"
