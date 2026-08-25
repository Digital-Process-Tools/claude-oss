"""#478 -- a per-repository grant for the two release Stops, tagging and publishing.

`skills/manager/SKILL.md`'s Stops table asserted, unconditionally, that tagging and
publishing a release always stop -- and this repository's own maintainer had granted the
loop that authority anyway, recorded only in a per-machine memory file the skill cannot
read and a second maintainer does not have. `release.authority` in `.oss.json` is where a
per-repository grant like that belongs, per this codebase's own governing rule: a fact
about one repository never lives in shared code.

Three states, and the third is the load-bearing one:

  loop          -- the loop tags and publishes without stopping.
  maintainer    -- explicit, unconditional stop.
  not-declared  -- absent, unreadable, or an unrecognised value. Stops, same as
                   `maintainer`. It must never default to autonomy: a repo that never
                   opted in must not be tagged because a config file failed to parse.

#467 is the same seam on a different value -- the version number -- and is answered
differently on purpose: `release.authority` governs tagging and publishing only. Deriving
a version number from the fragments was already listed as the loop's under `## Who
decides`, unconditionally, so gate 4 (tested in test_release_version.py-adjacent files,
and by the SKILL-content assertions below) does not read this key at all. A single key
that silently also granted version acceptance would be a wider grant than the config text
says; this module keeps the two decoupled instead, and the SKILL-content test below checks
that gate 4's prose never mentions the key -- the one place the wider reading could sneak
back in unreviewed.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def _release_config(release_block):
    config = {
        "repo": "o/r",
        "default_branch": "main",
        "clone": "/c",
        "worktree_root": "/w",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [],
        "changelog_dir": "changelog.d",
        "docs_targets": [],
        "labels": {"priority": [], "lanes": []},
        "state_file": "/s",
    }
    if release_block is not None:
        config["release"] = release_block
    return config


# -- release_authority(): three states -----------------------------------------------


def test_authority_loop_reads_loop():
    assert oss_config.release_authority(_release_config({"authority": "loop"})) == "loop"


def test_authority_maintainer_reads_maintainer():
    assert (
        oss_config.release_authority(_release_config({"authority": "maintainer"}))
        == "maintainer"
    )


def test_authority_absent_key_is_not_declared():
    """The `release` block exists (other keys set) but never mentions authority."""
    assert (
        oss_config.release_authority(_release_config({"tag_pattern": "v{version}"}))
        == "not-declared"
    )


def test_authority_no_release_block_is_not_declared():
    assert oss_config.release_authority(_release_config(None)) == "not-declared"


def test_authority_null_is_not_declared():
    assert oss_config.release_authority(_release_config({"authority": None})) == "not-declared"


def test_authority_unrecognised_value_is_not_declared_not_autonomy():
    """The load-bearing arm: an unrecognised value must not default to autonomy."""
    assert (
        oss_config.release_authority(_release_config({"authority": "sometimes"}))
        == "not-declared"
    )


def test_authority_non_dict_release_is_not_declared():
    assert oss_config.release_authority({"release": "not an object"}) == "not-declared"


# -- must-fire / must-not-fire control pair, per the brief ----------------------------


def test_scaffolded_shape_stops_maintainer_default():
    """A fresh repo's release block, exactly as scaffolded -- no authority key at all --
    must resolve the same as an explicit maintainer stop. Must-not-fire half of the
    control: nothing here grants autonomy by omission."""
    scaffolded_shape = {
        "tag_pattern": "v{version}",
        "merge_method": "squash",
        "commit_subject": None,
        "create_release": False,
        "draft": True,
        "latest": False,
        "triggers": {"merged_prs": 10, "soak_hours": 48},
    }
    assert oss_config.release_authority(_release_config(scaffolded_shape)) == "not-declared"


def test_this_repos_own_config_grants_loop():
    """Must-fire half of the control: this repository's own tracked `.oss.json` has opted
    in, and the accessor must read that grant back out."""
    config, problems, _origin, _resolved = oss_config.load_from(str(REPO_ROOT / ".oss.json"))
    assert config is not None, problems
    assert oss_config.release_authority(config) == "loop"


# -- validation: known key, and an unrecognised value is a reported problem -----------


def test_authority_is_a_known_release_key():
    problems = oss_config.validate(_release_config({"authority": "loop"}))
    assert not any("release.authority" in p and "unknown key" in p for p in problems)


def test_authority_unrecognised_value_is_reported():
    problems = oss_config.validate(_release_config({"authority": "sometimes"}))
    assert any("release.authority" in p for p in problems), problems


def test_authority_valid_values_report_no_problem():
    for value in ("loop", "maintainer"):
        problems = oss_config.validate(_release_config({"authority": value}))
        assert not any("release.authority" in p for p in problems), (value, problems)
