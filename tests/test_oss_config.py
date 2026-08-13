"""The config layer: schema validation, the setup probe, and path containment.

Every repo-shaped fact the maintainer loop used to hardcode now lives in .oss.json.
That moves the risk rather than removing it: a probe that invents a label is worse
than one that finds none, because an invented label reads as a measurement.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


# --------------------------------------------------------------------------- schema


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


def test_a_complete_config_validates():
    assert oss_config.validate(_valid()) == []


@pytest.mark.parametrize("key", sorted(_valid()))
def test_every_required_key_is_required(key):
    """A missing key must be named, not defaulted. A default here is a fact about
    some other repo wearing this repo's name.
    """
    config = _valid()
    del config[key]
    problems = oss_config.validate(config)
    assert any(key in p for p in problems), "dropping {!r} produced {!r}".format(key, problems)


def test_repo_must_be_owner_slash_name():
    config = _valid()
    config["repo"] = "name"
    assert any("repo" in p for p in oss_config.validate(config))


def test_config_may_not_carry_a_secret():
    """No key in this schema holds a credential. An unknown key that looks like one
    is refused rather than ignored, because a config file is committed.
    """
    for key in ("token", "gh_token", "password", "api_key", "secret"):
        config = _valid()
        config[key] = "x"
        problems = oss_config.validate(config)
        assert any(key in p for p in problems), "{!r} was accepted".format(key)


def test_unknown_keys_are_reported_not_ignored():
    config = _valid()
    config["worktre_root"] = "~/typo"
    assert any("worktre_root" in p for p in oss_config.validate(config))


def test_load_reports_a_missing_file_as_a_finding_not_a_crash():
    problems = oss_config.load(REPO_ROOT / "does-not-exist.json")[1]
    assert problems and any("not found" in p for p in problems)


def test_load_reports_malformed_json_as_a_finding(tmp_path):
    broken = tmp_path / ".oss.json"
    broken.write_text("{not json", encoding="utf-8")
    config, problems = oss_config.load(broken)
    assert config is None
    assert problems and any("parse" in p.lower() for p in problems)


# ---------------------------------------------------------------------------- probe


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "labels": ["priority-high", "priority-low", "lane-hooks", "bug"],
        "milestones": ["v0.2.0"],
        "workflow_jobs": ["pytest", "shellcheck"],
        "files": ["pyproject.toml", "README.md", "CHANGELOG.md", "changelog.d"],
        "clone": "/src/name",
    }
    probe.update(overrides)
    return probe


def test_probe_classifies_labels_by_their_real_spelling():
    config = oss_config.build(_probe())
    assert config["labels"]["priority"] == ["priority-high", "priority-low"]
    assert config["labels"]["lanes"] == ["lane-hooks"]


def test_probe_accepts_the_colon_spelling_too():
    """One repo spells it priority-high, a sibling spells it priority:high. Both are
    real; neither is the canonical one.
    """
    config = oss_config.build(_probe(labels=["priority:high", "priority:low"]))
    assert config["labels"]["priority"] == ["priority:high", "priority:low"]


def test_probe_invents_nothing_on_a_bare_repo():
    """The repo with no labels, no milestones and no CI is the real fixture. Empty
    lists are the honest answer; a default set would read as a measurement.
    """
    config = oss_config.build(
        _probe(labels=[], milestones=[], workflow_jobs=[], files=["README.md"])
    )
    assert config["labels"] == {"priority": [], "lanes": []}
    assert config["ci"]["required_checks"] == 0
    assert config["changelog_dir"] is None
    assert oss_config.validate(config) == []


def test_probe_does_not_claim_milestones_that_do_not_exist():
    config = oss_config.build(_probe(milestones=[]))
    assert config["milestones"] == []


def test_probe_detects_the_test_command_from_files():
    assert oss_config.build(_probe())["test_command"] == "pytest"
    bash = oss_config.build(_probe(files=["tests/run-all.sh", "README.md"]))
    assert bash["test_command"] == "bash tests/run-all.sh"


def test_a_plain_unittest_layout_is_detected():
    """Found by running the probe on a real repo: tests/test_*.py with no pyproject
    reported `null`, which is honest and still a miss -- the tests are right there.
    Marker-based detection only sees the markers somebody thought of.
    """
    config = oss_config.build(_probe(files=["tests/test_window_spread.py", "README.md"]))
    assert config["test_command"] == "python3 -m unittest discover -s tests"


def test_pyproject_wins_over_a_bare_tests_directory():
    """Both markers present is the common case, and pytest is the more specific claim."""
    config = oss_config.build(
        _probe(files=["pyproject.toml", "tests/test_thing.py", "README.md"])
    )
    assert config["test_command"] == "pytest"


def test_probe_leaves_the_test_command_unknown_rather_than_guessing():
    config = oss_config.build(_probe(files=["README.md"]))
    assert config["test_command"] is None


def test_probe_output_validates():
    assert oss_config.validate(oss_config.build(_probe())) == []


# --------------------------------------------------------------- test verification

PASSES = "python3 -c pass"
FAILS = "python3 -c 'raise SystemExit(3)'"
SLEEPS = "python3 -c 'import time; time.sleep(5)'"


def test_a_working_command_verifies_ok(tmp_path):
    """Detection infers from a marker file; this measures. A command that does not run
    is a confident wrong config, and setup is where that should be caught rather than
    by the first agent told to use it.
    """
    assert oss_config.verify_test_command(PASSES, tmp_path)["state"] == "ok"


def test_a_failing_command_is_reported_not_silently_kept(tmp_path):
    result = oss_config.verify_test_command(FAILS, tmp_path)
    assert result["state"] == "failed"
    assert "3" in result["detail"]


def test_a_command_that_does_not_exist_is_its_own_state(tmp_path):
    """A missing runner and a failing suite have different remedies."""
    result = oss_config.verify_test_command("definitely-not-a-real-binary", tmp_path)
    assert result["state"] == "not-found"


def test_a_slow_command_times_out_rather_than_hanging_setup(tmp_path):
    """Setup must not sit on somebody full suite. A timeout is unverified, which is not
    the same as broken -- calling it broken sends them to debug a suite that is slow.
    """
    result = oss_config.verify_test_command(SLEEPS, tmp_path, timeout=1)
    assert result["state"] == "timeout"
    assert "unverified" in result["detail"].lower()


def test_a_null_command_is_nothing_to_verify(tmp_path):
    assert oss_config.verify_test_command(None, tmp_path)["state"] == "none"


# ------------------------------------------------------------------ path containment


@pytest.mark.parametrize(
    "target",
    [
        "/etc/passwd",
        "../escape",
        "sub/dir",
        "sub\\dir",
        "C:\\Windows",
        "C:/Windows",
        "\\\\server\\share",
        "",
        ".",
        "..",
    ],
)
def test_worktree_targets_that_are_not_a_bare_name_are_refused(target, tmp_path):
    """A worktree target is a single directory name under the root. Anything with a
    separator, a drive prefix or a traversal is refused before it is resolved --
    checking after resolution is a race the symlink wins.
    """
    with pytest.raises(oss_config.ContainmentError):
        oss_config.resolve_worktree(tmp_path, target)


def test_a_bare_name_resolves_under_the_root(tmp_path):
    resolved = oss_config.resolve_worktree(tmp_path, "1234")
    assert resolved.parent == tmp_path.resolve()
    assert resolved.name == "1234"


def test_a_symlinked_target_escaping_the_root_is_refused(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "evil").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not create a directory symlink without privileges")
    with pytest.raises(oss_config.ContainmentError):
        oss_config.resolve_worktree(root, "evil")


def test_resolve_returns_one_resolved_path_the_caller_can_reuse(tmp_path):
    """The check and the use must be the same value. Returning the resolved path,
    rather than a boolean, is what stops a caller re-deriving it from the raw name.
    """
    assert isinstance(oss_config.resolve_worktree(tmp_path, "77"), Path)


# ------------------------------------------------------------------------ round trip


def test_written_config_reloads_identically(tmp_path):
    config = oss_config.build(_probe())
    path = tmp_path / ".oss.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    reloaded, problems = oss_config.load(path)
    assert problems == []
    assert reloaded == config
