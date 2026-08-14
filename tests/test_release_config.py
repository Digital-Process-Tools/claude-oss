"""The release block in .oss.json.

What a repo does differs: the tag spelling, the release commit subject, whether it
squashes. Those are config.

What must never be configurable is the gate list. A gate that can be switched off is
switched off on the day it is inconvenient, which is the day it was for.

Inference rules follow the same law as the rest of the probe: a tag pattern is derived
from tags that exist, and stays null when there are none. A null here is honest and the
release command refuses on it; a guessed `v{version}` against a repo tagging `rel-1.2`
creates a second, wrong tag namespace nobody notices until a release goes missing.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def _valid():
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "~/src/name",
        "worktree_root": "~/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [".claude-plugin/plugin.json"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "ci": {"required_checks": 4},
        "state_file": ".max/oss-watch.json",
    }


def _release(**overrides):
    block = {
        "tag_pattern": "v{version}",
        "commit_subject": "release {version} — {title}",
        "merge_method": "squash",
        "triggers": {"merged_prs": 10, "soak_hours": 48},
    }
    block.update(overrides)
    return block


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": [],
        "milestones": [],
        "workflow_jobs": [],
        "files": [],
        "tags": ["v0.3.0", "v0.2.0", "v0.1.0"],
        "merge_method": "squash",
        "version_evidence": {},
    }
    probe.update(overrides)
    return probe


# ------------------------------------------------------------------------ validation


def test_a_config_without_a_release_block_still_validates():
    """Releasing is not every repo's problem on day one."""
    assert oss_config.validate(_valid()) == []


def test_a_complete_release_block_validates():
    config = _valid()
    config["release"] = _release()
    assert oss_config.validate(config) == []


def test_a_release_block_that_is_not_an_object_is_reported():
    config = _valid()
    config["release"] = "squash"
    assert any("release" in p for p in oss_config.validate(config))


def test_an_unknown_release_key_is_reported_not_ignored():
    config = _valid()
    config["release"] = _release()
    config["release"]["tag_prefix"] = "v"
    assert any("tag_prefix" in p for p in oss_config.validate(config))


def test_a_tag_pattern_without_a_version_placeholder_is_refused():
    """`v1` as a pattern silently tags every release the same. The second release
    fails on an existing tag, and the first one to notice is whoever needed v2.
    """
    config = _valid()
    config["release"] = _release(tag_pattern="v")
    assert any("tag_pattern" in p for p in oss_config.validate(config))


def test_a_commit_subject_without_a_version_placeholder_is_refused():
    config = _valid()
    config["release"] = _release(commit_subject="release the thing")
    assert any("commit_subject" in p for p in oss_config.validate(config))


def test_an_unsupported_merge_method_is_refused():
    config = _valid()
    config["release"] = _release(merge_method="rebase-and-pray")
    assert any("merge_method" in p for p in oss_config.validate(config))


def test_null_release_fields_are_allowed_because_unknown_is_a_real_answer():
    """The probe leaves what it could not observe as null, and /oss:release refuses
    on it. Refusing later beats guessing now.
    """
    config = _valid()
    config["release"] = _release(tag_pattern=None, merge_method=None)
    assert oss_config.validate(config) == []


def test_triggers_must_be_numbers():
    config = _valid()
    config["release"] = _release(triggers={"merged_prs": "ten", "soak_hours": 48})
    assert any("merged_prs" in p for p in oss_config.validate(config))


def test_no_gate_can_be_declared_in_config():
    """The gates are not configurable, so a key that looks like one is refused rather
    than quietly ignored -- an ignored key reads as an accepted setting.
    """
    for key in ("gates", "skip_gates", "require_green", "skip_audit"):
        config = _valid()
        config["release"] = _release()
        config["release"][key] = False
        assert any(key in p for p in oss_config.validate(config)), key


# ------------------------------------------------------------------------- inference


def test_the_tag_pattern_is_inferred_from_tags_that_exist():
    assert oss_config.build(_probe())["release"]["tag_pattern"] == "v{version}"


def test_an_unprefixed_tag_scheme_is_inferred_as_such():
    config = oss_config.build(_probe(tags=["1.2.0", "1.1.0"]))
    assert config["release"]["tag_pattern"] == "{version}"


def test_an_unrecognised_tag_scheme_stays_null_rather_than_being_forced():
    config = oss_config.build(_probe(tags=["nightly-2026-08-01", "sprint-4"]))
    assert config["release"]["tag_pattern"] is None


def test_no_tags_means_no_inferred_pattern():
    config = oss_config.build(_probe(tags=[]))
    assert config["release"]["tag_pattern"] is None


def test_the_merge_method_comes_from_the_probe_and_is_null_when_unobserved():
    assert oss_config.build(_probe())["release"]["merge_method"] == "squash"
    assert oss_config.build(_probe(merge_method=None))["release"]["merge_method"] is None


def test_the_derived_release_block_validates():
    assert oss_config.validate(oss_config.build(_probe())) == []


def test_the_derived_block_validates_on_a_bare_repo_too():
    assert oss_config.validate(oss_config.build(_probe(tags=[], merge_method=None))) == []


# ------------------------------------------------------------------- a null commit_subject
#
# #34, second half. Both nullable release keys now have written behaviour, and they
# differ on purpose: a wrong subject line is cosmetic and revisable in the next commit,
# a wrong tag is a second namespace that is permanent. So `commit_subject` gets a plugin
# default and `tag_pattern` keeps stop-and-ask -- the fault was never the asymmetry, it
# was that only one of the two said anything at all.


def test_a_null_commit_subject_resolves_to_the_plugin_default():
    """The value the probe honestly could not observe still has to become a string
    before anything commits. Before this, the agent wrote whatever it felt like, which
    is a house style arriving from a tool that has never read the repo history.
    """
    config = _valid()
    config["release"] = _release(commit_subject=None)
    assert oss_config.release_commit_subject(config) == oss_config.DEFAULT_COMMIT_SUBJECT


def test_a_configured_commit_subject_wins_over_the_default():
    config = _valid()
    config["release"] = _release(commit_subject="ship {version}")
    assert oss_config.release_commit_subject(config) == "ship {version}"


def test_a_config_with_no_release_block_still_gets_the_default():
    assert oss_config.release_commit_subject(_valid()) == oss_config.DEFAULT_COMMIT_SUBJECT


def test_the_default_commit_subject_survives_the_validator_that_guards_the_key():
    """The obvious spelling of this default is `chore(release): {tag}`, and it is wrong:
    `_validate_release` requires the {version} placeholder, so a default written that way
    would be refused by the same module that emits it -- and only on the first repo that
    wrote it into its config.
    """
    config = _valid()
    config["release"] = _release(commit_subject=oss_config.DEFAULT_COMMIT_SUBJECT)
    assert oss_config.validate(config) == []


def test_only_the_cosmetic_nullable_key_has_a_default():
    """tag_pattern must have none. A default here is the second tag namespace this whole
    module is arranged to avoid, so its absence is asserted rather than assumed.
    """
    assert set(oss_config.RELEASE_DEFAULTS) == {"commit_subject"}
