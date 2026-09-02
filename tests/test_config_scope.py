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
import subprocess
import sys
from pathlib import Path

import pytest

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
        # Kept deliberately after #113 deleted the key. `/oss:setup` no longer writes
        # it, but a config on somebody's disk still has it, and the split has to send
        # it to the committed half rather than hiding it on one laptop.
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


def test_a_clone_with_no_local_half_is_derived_rather_than_failed(tmp_path):
    """The second maintainer, exactly as the issue describes them: they cloned, so
    they have the project half and nothing else. #608: `missing required key: clone`
    used to be the answer, true and useless -- it reads as a broken config rather
    than as an un-run setup, and blocks the very first thing the loop does (cutting a
    lane). Cloning must not be a broken state: the three machine keys are derived
    from the repository root instead, and `load()` reports no problem for it.
    """
    project, _ = oss_config.split(_combined(tmp_path))
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")

    config, problems = oss_config.load(path)
    assert problems == []
    assert config["clone"] == str(tmp_path.resolve())
    assert config["worktree_root"] == "{}-wt".format(tmp_path.resolve())
    assert config["state_file"] == ".max/name-watch.json"


def test_local_key_states_distinguishes_configured_from_derived(tmp_path):
    """#608's acceptance condition, in the same fixture per CLAUDE.md's rule on
    negative assertions: a repo root with no `.oss.local.json` (derived) paired with
    the ordinary split repo (configured), so a run that only exercised the
    already-passing case cannot pass as covering both.
    """
    combined_path = _write_split(tmp_path)
    configured = oss_config.local_key_states(combined_path)
    for key in oss_config.LOCAL_KEYS:
        state, value, reason = configured[key]
        assert state == oss_config.LOCAL_STATE_CONFIGURED, key
        assert value == _combined(tmp_path)[key]
        assert reason is None

    project, _ = oss_config.split(_combined(tmp_path))
    no_local_dir = tmp_path / "no-local"
    no_local_dir.mkdir()
    no_local_path = no_local_dir / oss_config.CONFIG_NAME
    no_local_path.write_text(json.dumps(project), encoding="utf-8")

    derived = oss_config.local_key_states(no_local_path)
    for key in oss_config.LOCAL_KEYS:
        state, value, reason = derived[key]
        assert state == oss_config.LOCAL_STATE_DERIVED, key
        assert value is not None
        assert reason is None
    assert derived["clone"][1] == str(no_local_dir.resolve())
    assert derived["worktree_root"][1] == "{}-wt".format(no_local_dir.resolve())


def test_local_key_states_could_not_derive_when_the_local_half_is_unreadable(tmp_path):
    path = _write_split(tmp_path)
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text("{ broken", encoding="utf-8")
    states = oss_config.local_key_states(path)
    for key in oss_config.LOCAL_KEYS:
        state, value, reason = states[key]
        assert state == oss_config.LOCAL_STATE_COULD_NOT_DERIVE, key
        assert value is None
        assert reason is not None


def test_local_key_states_reports_a_mis_scoped_committed_key_as_configured_not_derived(
    tmp_path,
):
    """Self-review round (#608): a machine-scoped key left in the committed
    `.oss.json` -- `_scope_problems` already flags this as a scope violation on its
    own -- is a real value someone chose, not a guess this script made up. With no
    `.oss.local.json` on disk at all, `_local_key_states` used to fall straight to
    `derived, not configured` for it and report a value computed from the repository
    root that DIFFERS from the real one `load()` actually uses (`config = dict
    (project)` keeps the committed value). Paired against the ordinary derived case
    in the same fixture: a sibling key with no committed value at all still derives
    normally, so this is not a blanket "everything is configured now" regression.
    """
    combined = _combined(tmp_path)
    mis_scoped_path = tmp_path / oss_config.CONFIG_NAME
    mis_scoped_path.write_text(json.dumps(combined), encoding="utf-8")  # nothing split out

    config, _problems = oss_config.load(mis_scoped_path)
    states = oss_config.local_key_states(mis_scoped_path)

    for key in oss_config.LOCAL_KEYS:
        state, value, reason = states[key]
        assert state == oss_config.LOCAL_STATE_CONFIGURED, key
        assert value == combined[key], key
        assert value == config[key], key
        assert reason is None

    # Must-fire control: a project half with the machine keys genuinely absent, in
    # a fresh directory of its own, still derives -- this fix must not have made
    # everything "configured" unconditionally.
    project_only, _local = oss_config.split(combined)
    derived_dir = tmp_path / "derived"
    derived_dir.mkdir()
    derived_path = derived_dir / oss_config.CONFIG_NAME
    derived_path.write_text(json.dumps(project_only), encoding="utf-8")
    derived_states = oss_config.local_key_states(derived_path)
    for key in oss_config.LOCAL_KEYS:
        state, _value, reason = derived_states[key]
        assert state == oss_config.LOCAL_STATE_DERIVED, key
        assert reason is None


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


def _project_only(root):
    """The shape #608 and #701 describe: already split, no machine keys anywhere."""
    project, _ = oss_config.split(_combined(root))
    return project


def test_split_cli_derives_when_no_machine_keys_anywhere_but_still_moves_them_when_present(
    tmp_path, capsys
):
    """The negative case needs its positive control in the same fixture (CLAUDE.md's
    rule on negative assertions), or "the project half was untouched" also passes on a
    run that changed nothing at all.
    """
    # Positive control: machine keys ARE present in the committed file, none configured
    # here yet -- the ordinary migration --split has always performed.
    with_keys = tmp_path / "with_keys"
    _git_repo(with_keys)
    combined_path = with_keys / oss_config.CONFIG_NAME
    combined_path.write_text(json.dumps(_combined(with_keys), indent=2), encoding="utf-8")

    assert oss_config._main(["--split", str(combined_path)]) == 0
    moved_project = json.loads(combined_path.read_text(encoding="utf-8"))
    moved_local = json.loads(
        (with_keys / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert not (set(moved_project) & oss_config.LOCAL_KEYS)
    assert set(moved_local) == oss_config.LOCAL_KEYS

    # The case #608 and #701 report: no machine key in the committed file, and no
    # .oss.local.json on this machine either -- the ordinary state of a fresh clone.
    no_keys = tmp_path / "no_keys"
    _git_repo(no_keys)
    project_path = no_keys / oss_config.CONFIG_NAME
    before = json.dumps(_project_only(no_keys), indent=2)
    project_path.write_text(before, encoding="utf-8")
    assert not (no_keys / oss_config.LOCAL_CONFIG_NAME).is_file()

    assert oss_config._main(["--split", str(project_path)]) == 0

    # Byte-identical -- nothing was rewritten, not even reformatted, because there was
    # nothing in it to move.
    assert project_path.read_text(encoding="utf-8") == before

    local = json.loads(
        (no_keys / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert set(local) == oss_config.LOCAL_KEYS
    resolved = str(no_keys.resolve())
    assert local["clone"] == resolved
    assert local["worktree_root"] == "{}-wt".format(resolved)
    assert local["state_file"] == ".max/name-watch.json"

    out = capsys.readouterr().out
    assert "derived, not configured" in out

    # Idempotent, same as the ordinary migration: re-running must not rewrite either
    # file once the machine half has been derived once.
    local_first = local
    assert oss_config._main(["--split", str(project_path)]) == 0
    assert project_path.read_text(encoding="utf-8") == before
    assert (
        json.loads((no_keys / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8"))
        == local_first
    )
    assert "already split; no key moved" in capsys.readouterr().out


def test_split_cli_derives_a_fallback_state_file_when_repo_is_not_a_string(tmp_path, capsys):
    """`_derive_local_config` copies `build()`'s ``(document.get("repo") or "/").split("/")``
    pattern, but `build()` only ever runs on a probe `probe_problems` has already confirmed
    carries a string `repo` -- `split_config_file` has no such gate, so a hand-edited or
    corrupted `.oss.json` with `repo` present and not a string used to raise a bare
    `AttributeError` out of `_main` instead of returning cleanly, unlike every other
    malformed-input path in this function (found in review, #701).
    """
    _git_repo(tmp_path)
    path = tmp_path / oss_config.CONFIG_NAME
    combined = _project_only(tmp_path)
    combined["repo"] = 123
    path.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0

    local = json.loads((tmp_path / oss_config.LOCAL_CONFIG_NAME).read_text(encoding="utf-8"))
    assert local["state_file"] == ".max/oss-watch.json"


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


# ------------------------------------------------------- the rule --split cannot repoint
#
# `.git/info/exclude` is not the only thing that ignores a file, and it is the only one
# this script may touch: a `.gitignore` belongs to the maintainer. So the project half can
# be correct, un-excluded, and still invisible to `git add` -- which is exactly the state
# this repository was in after #39, its own `.gitignore` still carrying `.oss.json`.
#
# `now safe to track` was printed unconditionally, so the receipt described the action
# taken rather than the state produced. Three states now: clear, ignored (naming the rule),
# and could-not-ask.


def _real_git_repo(tmp_path):
    """A repo `git check-ignore` will actually answer about, or the test skips.

    A fake `.git/info/` is enough for the exclude rewrite and not enough for git itself,
    and a skip that says so beats a green that measured nothing.
    """
    done = subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {}".format(done.stderr.strip() or done.returncode))
    (tmp_path / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git" / "info" / "exclude").write_text(
        "# git ls-files --others\n.oss.json\n", encoding="utf-8"
    )
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path), indent=2), encoding="utf-8")
    return path


def test_split_names_the_gitignore_rule_that_still_hides_the_project_half(tmp_path, capsys):
    path = _real_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n.oss.json\n", encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0
    out = capsys.readouterr().out

    assert ".gitignore:2" in out, out
    assert "now safe to track" not in out, (
        "the project half is still ignored, so claiming it is trackable reports the "
        "action taken instead of the state produced"
    )


def test_split_says_the_project_half_is_trackable_when_nothing_ignores_it(tmp_path, capsys):
    # The positive control for the assertion above: with no rule in the way the
    # trackable line must still appear, or that assertion also passes on a --split
    # that says nothing about tracking at all.
    path = _real_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0
    out = capsys.readouterr().out

    assert "now safe to track" in out, out
    assert ".gitignore:" not in out, out


def test_split_says_it_could_not_ask_rather_than_claiming_the_file_is_trackable(tmp_path, capsys):
    # No git repository at all, so check-ignore cannot answer. `unknown` is not `clear`:
    # a file nobody could check is not a file nobody ignores.
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(_combined(tmp_path), indent=2), encoding="utf-8")

    assert oss_config._main(["--split", str(path)]) == 0
    out = capsys.readouterr().out

    assert "could not" in out, out
    assert "now safe to track" not in out, out


# ------------------------------------- the probe's own output is filenames (#112)
#
# `_ignore_rule` decoded git's output with `universal_newlines=True`, i.e. the locale
# encoding, under `except OSError`. `UnicodeDecodeError` is a `ValueError`, so a byte the
# locale cannot decode skipped all three states and raised out of the function.
#
# What flows through this call is **pathnames**, which is the one place an undecodable
# byte is ordinary rather than exotic. And the answer never depended on the text: the
# exit code carries ignored/clear/unknown on its own, and the `-v` detail this function
# returns is the *source rule* -- everything before the tab -- while the undecodable
# pathname is everything after it. So the bytes could not reach the returned value even
# in principle. Reporting `unknown` here would have been this repo's own defect class: a
# tool limitation rendered as a fact about the repository.

_UNDECODABLE_NAME = "a\udc80b"
"""A lone 0x80 written deliberately, never left to a locale to produce.

surrogateescape is how Python already carries an undecodable filesystem byte, and it
re-encodes to exactly that byte on the way into argv. Nothing is created on disk:
`git check-ignore` answers about a pathname as a string, so there is no filesystem that
can refuse the name and no path-length limit in play on any platform.
"""


def _undecodable_probe_repo(tmp_path):
    """A repo whose `check-ignore` really does emit an undecodable byte, or a skip.

    `core.quotePath` defaults to true, which renders the byte as an ASCII octal escape
    and decodes cleanly -- so on a default repo this bug is unreachable and a test
    asserting it would be asserting nothing. The setting is flipped, and then the raw
    bytes are **measured** rather than assumed: if this platform's git still hands back
    something strictly decodable, there was no signal to classify and the test skips
    saying what went untested. No table of platform behaviours is written down.
    """
    done = subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {!r}".format(done.stderr[-200:]))
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "core.quotePath", "false"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (tmp_path / ".gitignore").write_text("*b\n", encoding="utf-8")

    try:
        probe = subprocess.run(
            ["git", "-C", str(tmp_path), "check-ignore", "-v", "--", _UNDECODABLE_NAME],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        pytest.skip(
            "this platform would not carry the byte into argv ({}: {}); the decode path "
            "in _ignore_rule went untested here".format(type(exc).__name__, exc)
        )
    if probe.returncode != 0:
        pytest.skip(
            "git did not match the pathname here (exit {}, stdout {!r}); the decode path "
            "went untested".format(probe.returncode, probe.stdout)
        )
    try:
        probe.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return
    pytest.skip(
        "git's output here is strictly decodable ({!r}), so nothing reached the decoder "
        "and there is no undecodable case on this platform to classify; the guard in "
        "_ignore_rule went untested".format(probe.stdout)
    )


def test_ignore_rule_answers_about_a_path_git_prints_undecodably(tmp_path):
    _undecodable_probe_repo(tmp_path)

    # The bug: this raised UnicodeDecodeError out of a function whose whole contract is
    # to return one of three states.
    state, detail = oss_config._ignore_rule(tmp_path, _UNDECODABLE_NAME)

    assert state == "ignored", (state, detail)
    assert detail == ".gitignore:1:*b", (
        "the source rule is entirely ASCII and sits before the tab, so the undecodable "
        "pathname after it must not degrade it: got {!r}".format(detail)
    )
    assert "�" not in detail, detail

    # The positive control, in the same fixture and the same repo: a name nothing matches
    # must still come back `clear`. Without it, an assertion that the undecodable name was
    # handled also passes on a probe that answered nothing at all, or on a repo where
    # every question happens to return the same state.
    assert oss_config._ignore_rule(tmp_path, "zzz.txt") == ("clear", "")


def test_ignore_rule_reports_unknown_when_git_cannot_be_run_with_that_name(tmp_path):
    """The remaining `ValueError`: subprocess refuses an argument holding a NUL byte.

    Different answer from `git would not start` -- the binary is there and would have
    run; it is this name that cannot be handed to it -- so it gets its own reason rather
    than being folded into the missing-binary one.
    """
    state, detail = oss_config._ignore_rule(tmp_path, "a\x00b")

    assert state == "unknown", (state, detail)
    assert "would not start" not in detail, detail
    assert "could not be handed to git" in detail, detail

    # Positive control: the same directory answers normally for a name git accepts, so
    # this is a fact about the name and not about a probe that is broken outright.
    assert oss_config._ignore_rule(tmp_path, "zzz.txt")[0] in ("clear", "unknown")


def test_run_returns_undecodable_stdout_instead_of_raising():
    """`_run` had the same spelling and the same guard, and `git ls-files` prints paths.

    Driven with a real subprocess emitting a real 0x80, so no locale and no mock decides
    whether the case occurs.
    """
    emit = r"import sys; sys.stdout.buffer.write(b'ok-\x80\n')"
    ok, stdout, detail = oss_config._run([sys.executable, "-c", emit])

    assert ok is True, detail
    assert stdout.startswith("ok-"), repr(stdout)

    # Positive control: an all-ASCII run through the same helper is byte-exact, so the
    # replacement policy is confined to bytes that had no other rendering.
    ok, clean, detail = oss_config._run([sys.executable, "-c", "print('ok-plain')"])
    assert ok is True, detail
    assert clean.strip() == "ok-plain", repr(clean)


def test_this_repos_own_gitignore_does_not_hide_its_project_half():
    """The stale line that motivated all of the above, pinned so it cannot come back."""
    rules = [
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ]
    assert oss_config.CONFIG_NAME not in rules, (
        "{} is the tracked project half; a .gitignore rule for it makes this repo's own "
        "config uncommittable".format(oss_config.CONFIG_NAME)
    )
    assert oss_config.LOCAL_CONFIG_NAME in rules, (
        "and the machine half must be ignored, or one maintainer's paths get committed"
    )
