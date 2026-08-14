"""Which half of `.oss.json` belongs to the project and which to the laptop (#34).

`/oss:setup` wrote one file and added it to `.git/info/exclude`. That is right for
`clone`, `worktree_root` and `state_file` -- they name directories on one machine. It is
wrong for everything else: `tag_pattern`, `merge_method`, `version_sites`,
`changelog_dir`, `test_command`, `labels` and `triggers` are facts about the *repo*, and
`/oss:release` reads every one of them off a file that exists on exactly one laptop.

The consequence found while cutting a real release: a second maintainer has no
`tag_pattern`, the release command's own instruction for that case is stop-and-ask, so
the value is re-derived by a human and can differ. A repo tagging `v1.2.3` acquires a
`1.2.4` -- the second tag namespace the plugin warns about, opened by the plugin.

So the config is two files:

- `.oss.json`      -- project scope, **tracked**, reviewed like any other repo fact
- `.oss.local.json` -- machine scope, **git-excluded**, three keys, never shared

`load()` reads both and merges. Everything downstream keeps seeing one config, so the
split is a fact about storage rather than a new shape every caller has to learn.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


def _combined(root):
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": str(root / "clone"),
        "worktree_root": str(root / "clone-wt"),
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "ci": {"required_checks": 2},
        "state_file": ".max/oss-watch.json",
        "release": {
            "tag_pattern": "v{version}",
            "merge_method": "squash",
            "commit_subject": None,
            "triggers": {"merged_prs": 10, "soak_hours": 48},
        },
    }


def _write_split(root):
    """The shape /oss:setup produces: two files, disjoint."""
    project, local = oss_config.split(_combined(root))
    (root / oss_config.CONFIG_NAME).write_text(json.dumps(project, indent=2), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local, indent=2), encoding="utf-8")
    return root / oss_config.CONFIG_NAME


# ------------------------------------------------------------------------------ scopes


def test_the_two_scopes_partition_the_schema_with_nothing_left_over():
    """A key in neither set is a key nobody decided the scope of, and it would land in
    whichever half the partition happens to default to.
    """
    assert oss_config.LOCAL_KEYS | oss_config.PROJECT_KEYS == oss_config.KNOWN_KEYS
    assert not (oss_config.LOCAL_KEYS & oss_config.PROJECT_KEYS)


def test_only_the_three_path_keys_are_machine_scope():
    """These are the only values that name a directory on one person's disk. The test
    is written as equality rather than membership so that adding a key without deciding
    its scope fails here instead of being silently published or silently withheld.
    """
    assert oss_config.LOCAL_KEYS == {"clone", "worktree_root", "state_file"}


def test_everything_release_reads_is_project_scope():
    """The issue's list, asserted key by key. `/oss:release` reads all of these, and
    every one of them is a fact about the repo rather than about the laptop.
    """
    for key in (
        "release",
        "version_sites",
        "changelog_dir",
        "docs_targets",
        "labels",
        "test_command",
        "repo",
        "default_branch",
        "branch_pattern",
        "ci",
    ):
        assert key in oss_config.PROJECT_KEYS, key


# ------------------------------------------------------------------------------- split


def test_split_sends_each_key_to_exactly_one_half(tmp_path):
    project, local = oss_config.split(_combined(tmp_path))
    assert set(local) == oss_config.LOCAL_KEYS
    assert "release" in project
    assert not (set(project) & set(local))
    merged = dict(project)
    merged.update(local)
    assert merged == _combined(tmp_path)


def test_the_committed_half_carries_no_filesystem_path(tmp_path):
    """The reason a maintainer cannot simply commit the file they have: it names their
    home directory. This asserts the property directly rather than trusting the key list.
    """
    project, _ = oss_config.split(_combined(tmp_path))
    assert str(tmp_path) not in json.dumps(project)


def test_split_of_an_unknown_key_keeps_it_where_validate_will_see_it(tmp_path):
    config = _combined(tmp_path)
    config["worktre_root"] = "typo"
    project, _ = oss_config.split(config)
    assert "worktre_root" in project


# -------------------------------------------------------------------------------- load


def test_load_merges_the_two_halves_into_one_config(tmp_path):
    path = _write_split(tmp_path)
    config, problems = oss_config.load(path)
    assert problems == []
    assert config["clone"] == str(tmp_path / "clone")
    assert config["release"]["tag_pattern"] == "v{version}"


def test_a_machine_key_left_in_the_committed_file_is_reported_by_name(tmp_path):
    """The legacy shape: one file with everything in it. It still loads -- breaking every
    existing install is not a migration -- but the problem names the key and the remedy,
    because a file that quietly works is a file nobody splits.
    """
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path)), encoding="utf-8")
    config, problems = oss_config.load(path)
    assert config is not None
    assert config["clone"] == str(tmp_path / "clone")
    joined = "\n".join(problems)
    for expected in ("clone", "worktree_root", "state_file", oss_config.LOCAL_CONFIG_NAME, "--split"):
        assert expected in joined, expected


def test_the_project_half_wins_when_the_local_half_contradicts_it(tmp_path):
    """A per-machine override of a project fact is the divergence this issue is about,
    so the committed value wins and the override is named. Precedence stated once, by
    the plugin, rather than discovered per laptop.
    """
    path = _write_split(tmp_path)
    local = json.loads((tmp_path / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8"))
    local["release"] = {"tag_pattern": "{version}"}
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")

    config, problems = oss_config.load(path)
    assert config["release"]["tag_pattern"] == "v{version}"
    joined = "\n".join(problems)
    assert "release" in joined
    assert oss_config.LOCAL_CONFIG_NAME in joined


def test_a_clone_with_no_local_half_is_told_which_file_to_write(tmp_path):
    """The second maintainer, exactly as the issue describes them: they cloned, so they
    have the project half and nothing else. `missing required key: clone` is true and
    useless -- it reads as a broken config rather than as an un-run setup.
    """
    project, _ = oss_config.split(_combined(tmp_path))
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")

    config, problems = oss_config.load(path)
    joined = "\n".join(problems)
    assert oss_config.LOCAL_CONFIG_NAME in joined
    assert "/oss:setup" in joined


def test_an_unreadable_local_half_is_a_named_problem_not_a_silent_project_only_load(tmp_path):
    path = _write_split(tmp_path)
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text("{ broken", encoding="utf-8")
    config, problems = oss_config.load(path)
    joined = "\n".join(problems)
    assert oss_config.LOCAL_CONFIG_NAME in joined
    assert any("JSON" in p for p in problems)


# --------------------------------------------------------------------------- --split CLI


def _git_repo(tmp_path):
    info = tmp_path / ".git" / "info"
    info.mkdir(parents=True)
    (info / "exclude").write_text("# git ls-files --others\n.oss.json\n", encoding="utf-8")
    return info / "exclude"


def test_split_cli_writes_both_halves_and_leaves_the_project_half_tracked(tmp_path, capsys):
    exclude = _git_repo(tmp_path)
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path), indent=2), encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0

    project = json.loads(path.read_text(encoding="utf-8"))
    local = json.loads((tmp_path / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8"))
    assert set(local) == oss_config.LOCAL_KEYS
    assert not (set(project) & oss_config.LOCAL_KEYS)

    lines = exclude.read_text(encoding="utf-8").splitlines()
    assert oss_config.LOCAL_CONFIG_NAME in lines
    assert oss_config.CONFIG_NAME not in lines, (
        "the project half must stop being excluded, or the migration ends with a file "
        "that is correct and still uncommittable"
    )


def test_split_cli_reports_what_it_did(tmp_path, capsys):
    _git_repo(tmp_path)
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path), indent=2), encoding="utf-8")
    oss_config._main(["--split", str(path)])
    out = capsys.readouterr().out
    assert oss_config.LOCAL_CONFIG_NAME in out
    assert "git add" in out, "the one step the script must not take for you is named"


def test_split_cli_is_idempotent(tmp_path):
    exclude = _git_repo(tmp_path)
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path), indent=2), encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0
    first = (path.read_text(encoding="utf-8"), exclude.read_text(encoding="utf-8"))
    local_first = (tmp_path / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0
    assert (path.read_text(encoding="utf-8"), exclude.read_text(encoding="utf-8")) == first
    assert (tmp_path / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8") == local_first


def test_split_cli_refuses_a_config_it_cannot_read(tmp_path, capsys):
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text("{ broken", encoding="utf-8")
    assert oss_config._main(["--split", str(path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_split_cli_outside_a_git_repo_still_splits_and_says_the_exclusion_was_not_touched(
    tmp_path, capsys
):
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path), indent=2), encoding="utf-8")
    assert oss_config._main(["--split", str(path)]) == 0
    assert (tmp_path / oss_config.LOCAL_CONFIG_NAME).is_file()
    assert ".git/info/exclude" in capsys.readouterr().out
