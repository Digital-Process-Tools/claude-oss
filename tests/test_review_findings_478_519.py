"""Two findings from this diff's own self-review, argued real and fixed here.

1. `oss_config.release_authority()` / `_validate_release` did `value in
   RELEASE_AUTHORITIES` (a set) without checking the value was hashable first --
   an unhashable `.oss.json` value (`{}`, `[]`) for `release.authority` raised an
   uncaught `TypeError` instead of being reported as a validation problem. Since
   `oss_config.load()` calls `validate()` unconditionally and every caller --
   `scripts/doctor.py` foremost, whose whole documented contract is "exit 0
   always, one VERDICT line" -- routes through `load()`/`load_from()`, a
   maintainer-authored typo of this shape took the diagnostic itself down
   uncaught.
2. `doctor.oss_workspace_launcher_state`'s new `matched-elsewhere` branch
   compared `their_version != our_version` without checking `our_version` was
   not `None` first. `_manifest_version` legitimately returns `(state, None)`
   when this running install's own manifest is unreadable or carries no version
   field -- a normal, already-modelled condition elsewhere in this file -- and
   `their_version != None` is vacuously true for any resolvable, cache-shaped
   target. So an unreadable OWN manifest rendered as a CONFIRMED different
   install ("a different install from this running one (version None)"),
   exactly the absence-as-permission shape this repo's own CLAUDE.md names as
   its defect class, just on the other input from the one #519 was filed about.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import oss_config  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


# -- unhashable release.authority must not crash the config loader -------------------


@pytest.mark.parametrize("bad_value", [{}, [], {"nested": True}, [1, 2]])
def test_unhashable_authority_is_a_reported_problem_not_a_crash(bad_value):
    config = {"release": {"authority": bad_value}}
    # Would raise TypeError: unhashable type here if the code did nothing.
    problems = oss_config.validate(config)
    assert any("release.authority" in p for p in problems), problems


@pytest.mark.parametrize("bad_value", [{}, [], {"nested": True}, [1, 2]])
def test_unhashable_authority_reads_as_not_declared_not_a_crash(bad_value):
    config = {"release": {"authority": bad_value}}
    # Would raise TypeError: unhashable type here if the code did nothing.
    assert oss_config.release_authority(config) == "not-declared"


def test_doctor_check_config_survives_an_unhashable_authority(tmp_path):
    """The end-to-end shape the finding was reported against: doctor.py must
    still exit with a reported problem, never a traceback, over a real
    .oss.json on disk."""
    import json

    config_path = tmp_path / ".oss.json"
    config_path.write_text(
        json.dumps(
            {
                "repo": "o/r",
                "default_branch": "main",
                "clone": str(tmp_path),
                "worktree_root": str(tmp_path),
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": "changelog.d",
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": str(tmp_path / "state.json"),
                "release": {"authority": {}},
            }
        ),
        encoding="utf-8",
    )
    doctor.FINDINGS.clear()
    # Would raise TypeError here if the code did nothing.
    config = doctor.check_config(str(tmp_path))
    assert any(
        state == "FAIL" and "release.authority" in message for state, message in doctor.FINDINGS
    ), doctor.FINDINGS


# -- matched-elsewhere must not fire when our own version could not be read ----------


def _plugin_root_no_manifest(tmp_path, content=b"same bytes\n"):
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "oss-workspace").write_bytes(content)
    os.chmod(str(root / "bin" / "oss-workspace"), 0o755)
    # Deliberately no .claude-plugin/plugin.json -- this running install's own
    # version cannot be read.
    return root


def _stale_cache_entry(tmp_path, content, version="0.7.0"):
    cache_dir = tmp_path / "cache" / "dpt-plugins" / "oss" / version / "bin"
    cache_dir.mkdir(parents=True)
    target = cache_dir / "oss-workspace"
    target.write_bytes(content)
    os.chmod(str(target), 0o755)
    return str(cache_dir), target


def test_matched_elsewhere_does_not_fire_when_our_own_version_is_unreadable(tmp_path):
    """The must-fire-for-the-fix / must-not-fire-for-the-bug pair: an unreadable
    OWN manifest must not be conflated with a CONFIRMED different install."""
    plugin_root = _plugin_root_no_manifest(tmp_path, content=b"same bytes\n")
    path_dir, _target = _stale_cache_entry(tmp_path, b"same bytes\n", version="0.7.0")

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)

    assert state != "matched-elsewhere", (state, detail)


def test_check_oss_workspace_launcher_does_not_claim_a_different_install_when_unknown(tmp_path):
    plugin_root = _plugin_root_no_manifest(tmp_path, content=b"same bytes\n")
    path_dir, _target = _stale_cache_entry(tmp_path, b"same bytes\n", version="0.7.0")

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=path_dir)

    level, message = doctor.FINDINGS[-1]
    assert "PINNED ELSEWHERE" not in message, message
    assert "a different install from this running one" not in message, message
