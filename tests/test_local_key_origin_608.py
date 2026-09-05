"""#608: a fresh clone has no `.oss.local.json`, and nothing used to derive one.

Every consumer of `clone` / `worktree_root` / `state_file` must report which of
three states produced the value it is using -- `configured` (read from
`.oss.local.json`), `derived, not configured` (no such file, or no such key;
computed from the repository root instead), or `could-not-derive` (with a
reason). A clone with no `.oss.local.json` must not print the same `OK` shape a
configured clone prints, because that would make a guess indistinguishable from
a measurement -- the defect class this repository is named after, reproduced
inside its own fix.

Every pair of tests below runs BOTH the configured and the derived case in the
same fixture (CLAUDE.md's rule on negative assertions): a run that only
exercised the already-passing (configured) case must not read as covering both.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import oss_config  # noqa: E402
import lane_setup  # noqa: E402


def _combined(root):
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": str(root),
        "worktree_root": str(root / "wt"),
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": None,
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }


def _write_split(root):
    """The configured case: `/oss:setup` already ran here."""
    root.mkdir(parents=True, exist_ok=True)
    project, local = oss_config.split(_combined(root))
    (root / oss_config.CONFIG_NAME).write_text(
        json.dumps(project, indent=2), encoding="utf-8"
    )
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local, indent=2), encoding="utf-8"
    )
    return root


def _write_project_only(root):
    """The derived case: a fresh clone, `.oss.local.json` was never written here."""
    root.mkdir(parents=True, exist_ok=True)
    project, _local = oss_config.split(_combined(root))
    (root / oss_config.CONFIG_NAME).write_text(
        json.dumps(project, indent=2), encoding="utf-8"
    )
    return root


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


# --------------------------------------------------------- doctor._local_key_states_for


def test_local_key_states_for_reports_configured_then_derived(tmp_path):
    configured_root = _write_split(tmp_path / "configured")
    states = doctor._local_key_states_for(configured_root)
    for key in oss_config.LOCAL_KEYS:
        state, value, reason = states[key]
        assert state == oss_config.LOCAL_STATE_CONFIGURED, key
        assert value == _combined(configured_root)[key]
        assert reason is None

    derived_root = _write_project_only(tmp_path / "derived")
    derived_states = doctor._local_key_states_for(derived_root)
    for key in oss_config.LOCAL_KEYS:
        state, value, reason = derived_states[key]
        assert state == oss_config.LOCAL_STATE_DERIVED, key
        assert value is not None
        assert reason is None
    assert derived_states["clone"][1] == str(derived_root.resolve())


# ------------------------------------------------------------------- check_directory


def test_check_directory_annotates_a_derived_value_and_leaves_a_configured_one_alone(
    tmp_path,
):
    configured_root = _write_split(tmp_path / "configured")
    doctor.check_directory(
        "clone",
        str(configured_root),
        origin=(oss_config.LOCAL_STATE_CONFIGURED, str(configured_root), None),
    )
    configured_state, configured_message = doctor.FINDINGS[-1]
    assert configured_state == "OK"
    assert "derived" not in configured_message
    assert configured_message == "clone: {}".format(configured_root)

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    doctor.check_directory(
        "clone",
        str(derived_root),
        origin=(oss_config.LOCAL_STATE_DERIVED, str(derived_root), None),
    )
    derived_state, derived_message = doctor.FINDINGS[-1]
    assert derived_state == "OK"
    assert "derived, not configured" in derived_message

    # The two OK lines for the SAME kind of value must not read identically -- the
    # whole of #608's acceptance condition. Same shape (a bare directory path) on
    # both sides, so the only thing that can be doing the distinguishing is the
    # annotation itself.
    assert configured_message != derived_message


def test_check_directory_names_the_reason_when_a_value_could_not_be_derived(tmp_path):
    doctor.check_directory(
        "clone",
        None,
        origin=(oss_config.LOCAL_STATE_COULD_NOT_DERIVE, None, "boom"),
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could not derive" in message
    assert "boom" in message


# --------------------------------------------------------------------- check_state_file


def _state_file(root, body):
    directory = root / ".max"
    directory.mkdir(exist_ok=True)
    (directory / "oss-watch.json").write_text(body, encoding="utf-8")


def test_check_state_file_annotates_a_derived_value_and_leaves_a_configured_one_alone(
    tmp_path,
):
    configured_root = tmp_path / "configured"
    configured_root.mkdir()
    _state_file(configured_root, "[]")
    doctor.check_state_file(
        configured_root,
        {"state_file": ".max/oss-watch.json"},
        origin=(oss_config.LOCAL_STATE_CONFIGURED, ".max/oss-watch.json", None),
    )
    configured_state, configured_message = doctor.FINDINGS[-1]
    assert configured_state == "OK"
    assert "derived" not in configured_message

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _state_file(derived_root, "[]")
    doctor.check_state_file(
        derived_root,
        {"state_file": ".max/oss-watch.json"},
        origin=(oss_config.LOCAL_STATE_DERIVED, ".max/oss-watch.json", None),
    )
    derived_state, derived_message = doctor.FINDINGS[-1]
    assert derived_state == "OK"
    assert "derived, not configured" in derived_message
    assert configured_message != derived_message


# ------------------------------------------------------------------------ oss_config.load


def test_load_populates_derived_values_where_a_fresh_clone_used_to_fail(tmp_path):
    """The end-to-end case #608 opens with: `.oss.json` alone, no `.oss.local.json`
    at all. `load()` used to leave `clone`/`worktree_root`/`state_file` out of
    `config` entirely and report `missing required key: ...` for each -- a fresh
    clone read as a broken config. Paired against the ordinary configured clone in
    the same test.
    """
    configured_root = _write_split(tmp_path / "configured")
    configured_config, configured_problems = oss_config.load(
        configured_root / oss_config.CONFIG_NAME
    )
    assert configured_problems == []
    assert configured_config["clone"] == str(configured_root)

    derived_root = _write_project_only(tmp_path / "derived")
    derived_config, derived_problems = oss_config.load(
        derived_root / oss_config.CONFIG_NAME
    )
    assert derived_problems == []
    assert derived_config["clone"] == str(derived_root.resolve())
    assert derived_config["worktree_root"] == "{}-wt".format(derived_root.resolve())
    assert derived_config["state_file"] == ".max/name-watch.json"


# --------------------------------------------------------------- lane_setup.derive_worktree


def test_derive_worktree_reports_origin_and_a_fresh_clone_can_still_cut_a_lane(
    tmp_path,
):
    """#608's other named consumer (`scripts/lane_setup.py`'s `worktree_occupancy`
    unknown-reporting arm, reached through `derive_worktree`): a fresh clone with no
    `.oss.local.json` must resolve a worktree path (so a lane CAN be cut) and must
    say the path was derived, not configured -- paired against the configured case.
    """
    configured_root = _write_split(tmp_path / "configured")
    configured_config, _ = oss_config.load(configured_root / oss_config.CONFIG_NAME)
    configured_states = oss_config.local_key_states(
        configured_root / oss_config.CONFIG_NAME
    )
    configured_worktree = lane_setup.derive_worktree(
        configured_config, 999, origin=configured_states["worktree_root"]
    )
    assert configured_worktree["state"] == "resolved"
    assert configured_worktree["origin"] == oss_config.LOCAL_STATE_CONFIGURED

    derived_root = _write_project_only(tmp_path / "derived")
    derived_config, _ = oss_config.load(derived_root / oss_config.CONFIG_NAME)
    derived_states = oss_config.local_key_states(derived_root / oss_config.CONFIG_NAME)
    derived_worktree = lane_setup.derive_worktree(
        derived_config, 999, origin=derived_states["worktree_root"]
    )
    # The core of #608: a fresh clone must be able to cut a lane at all.
    assert derived_worktree["state"] == "resolved"
    assert derived_worktree["path"] is not None
    assert derived_worktree["origin"] == oss_config.LOCAL_STATE_DERIVED
    assert derived_worktree["path"] != configured_worktree["path"]
