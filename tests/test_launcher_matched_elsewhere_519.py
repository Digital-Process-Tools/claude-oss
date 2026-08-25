"""#519: a stale version pin whose bytes still match reported OK, indistinguishably
from a symlink that genuinely names the running install.

`oss_workspace_launcher_state` compares content, correctly and deliberately (#289's own
rationale rules out a version-segment comparison as the DECIDER). But content equality
answers a different question from the one `/oss:doctor` prints: two distinct states
rendered identically as `matched` --

  * the symlink names the running install's own tree -- nothing can go stale;
  * the symlink names an OLDER version-scoped plugin-cache directory whose copy of this
    one file happens not to have changed since -- a stale pin with correct bytes, which
    silently becomes wrong on the next release that touches `bin/oss-workspace`.

This file is the must-fire half: a resolved target recognisably shaped like
`.../oss/<version>/bin/oss-workspace` (the same shape `_oss_workspace_version_segment`
already parses for the `mismatched` state's label) whose *directory* is not this running
install's own `plugin_root`, with byte-identical content, must report a NEW state rather
than `matched`.

The must-not-fire controls are the existing tests in test_oss_workspace_launcher_289.py:
`test_matched_by_identity_is_the_positive_control` (this running install's own path) and
`test_matched_by_content_a_separate_copy_with_identical_bytes` (a copy at a path that does
NOT have the `.../oss/<version>/bin/` shape -- an ordinary hand-copied dev setup, where the
path carries no claim about being a plugin-cache install and so nothing to warn about).
Both are left asserting `matched`, unchanged, and re-run here as an explicit regression
guard so a change to the new branch cannot silently widen it to cover them too.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _plugin_root(tmp_path, content=b"# the running install\n", version="9.9.9"):
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    entry = root / "bin" / "oss-workspace"
    entry.write_bytes(content)
    os.chmod(str(entry), 0o755)
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        '{"name": "oss", "version": "%s"}' % version, encoding="utf-8"
    )
    return root


def _stale_cache_entry(tmp_path, content, version="0.7.0"):
    cache_dir = tmp_path / "cache" / "dpt-plugins" / "oss" / version / "bin"
    cache_dir.mkdir(parents=True)
    target = cache_dir / "oss-workspace"
    target.write_bytes(content)
    os.chmod(str(target), 0o755)
    return str(cache_dir), target


def test_a_stale_cache_pin_with_identical_bytes_is_not_matched(tmp_path):
    """The must-fire half: same content, different (older) plugin-cache install."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n", version="9.9.9")
    path_dir, target = _stale_cache_entry(tmp_path, b"same bytes\n", version="0.7.0")

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)

    assert state != "matched", (state, detail)
    assert state == "matched-elsewhere", (state, detail)


def test_the_new_state_names_both_locations_and_the_stale_version(tmp_path):
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n", version="9.9.9")
    path_dir, target = _stale_cache_entry(tmp_path, b"same bytes\n", version="0.7.0")

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)

    resolved, their_version = detail
    assert their_version == "0.7.0", detail
    assert str(target.resolve()) in resolved or resolved in str(target.resolve()), detail


def test_check_oss_workspace_launcher_warns_and_does_not_claim_a_match(tmp_path):
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n", version="9.9.9")
    path_dir, _target = _stale_cache_entry(tmp_path, b"same bytes\n", version="0.7.0")

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=path_dir)

    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    # The one sentence #519 exists to make impossible: identical-today must never
    # render as "matches this running install".
    assert "matches this running install" not in message, message
    assert "0.7.0" in message
    assert "9.9.9" in message


def test_must_not_fire_own_identity_is_still_matched(tmp_path):
    """Regression guard for the must-not-fire control already in #289's suite:
    the running install's own path must still be plain `matched`."""
    plugin_root = _plugin_root(tmp_path)
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(plugin_root / "bin")
    )
    assert state == "matched", (state, detail)


def test_must_not_fire_a_non_cache_shaped_copy_is_still_matched(tmp_path):
    """Regression guard: an ordinary hand-copied path with no `oss/<version>/bin`
    shape carries no install-identity claim, so it must stay `matched`."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n")
    directory = tmp_path / "on-path"
    directory.mkdir()
    (directory / "oss-workspace").write_bytes(b"same bytes\n")

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(directory)
    )
    assert state == "matched", (state, detail)


def test_same_version_segment_different_directory_is_still_just_matched(tmp_path):
    """A resolved path that happens to parse to THIS running install's own version
    is not "a different install" even if the literal directory differs (e.g. two
    mounts of the same cache) -- there is nothing stale to warn about since the next
    release invalidates both copies identically. Only a version segment that
    DIFFERS from the running install's own is the state #519 is about."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n", version="9.9.9")
    path_dir, _target = _stale_cache_entry(tmp_path, b"same bytes\n", version="9.9.9")

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)

    assert state == "matched", (state, detail)
