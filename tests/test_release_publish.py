"""The GitHub Release object /oss:release never created (#58).

The tag was the end of the road: the releases page showed a tag with no notes,
nothing was marked `Latest`, and nobody watching for releases heard anything. The
skill's own section already argued the tag is not the delivery, then narrated the
shortfall instead of closing it.

Three states here, like everywhere else in this plugin, and the third is the reason
the file is arranged this way:

  create / created            policy asked for it and the command is buildable
  skipped                     policy says this repo does not publish releases
  could-not-run / -create     the notes could not be extracted, `gh` is not on PATH,
                              or the call failed. Never a release, never a skip, and
                              above all never silence on a release path.

`--verify-tag` is asserted by spelling the whole command out. A test that mocks the
call and checks the mock was invoked proves nothing about the flags -- and without
`--verify-tag`, `gh release create` mints the missing tag itself, which turns the
verification step two paragraphs earlier in the skill into decoration.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import release_publish  # noqa: E402


CHANGELOG = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.3.0] - 2026-08-14

### Added

- The thing that was added.

### Fixed

- The thing that was fixed (#58).

## [0.2.0] - 2026-07-01

### Added

- An older thing nobody is releasing today.
"""


def _config(**release):
    block = {"tag_pattern": "v{version}", "commit_subject": None, "merge_method": "squash"}
    block.update(release)
    return {"repo": "owner/name", "release": block}


# --------------------------------------------------------------- notes extraction


def test_the_notes_are_the_section_body_and_stop_at_the_next_heading():
    found = release_publish.notes_section(CHANGELOG, "0.3.0")
    assert found["state"] == "found"
    assert "The thing that was added." in found["body"]
    assert "The thing that was fixed (#58)." in found["body"]
    # The positive control above is only worth having next to this: a body that ran
    # on past the next `## [` would carry the previous release's notes into this
    # release's announcement, and every assertion above would still pass.
    assert "An older thing nobody is releasing today." not in found["body"]
    assert "## [0.2.0]" not in found["body"]
    assert "## [0.3.0]" not in found["body"]


def test_the_last_section_in_the_file_runs_to_the_end_rather_than_off_it():
    found = release_publish.notes_section(CHANGELOG, "0.2.0")
    assert found["state"] == "found"
    assert "An older thing nobody is releasing today." in found["body"]


def test_the_only_section_in_the_file_is_extractable():
    text = "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n### Added\n\n- First release.\n"
    found = release_publish.notes_section(text, "1.0.0")
    assert found["state"] == "found"
    assert found["body"].strip() == "### Added\n\n- First release."


def test_a_heading_with_no_body_is_empty_and_not_found():
    """`## [0.4.0]` immediately followed by the next heading. An empty string here
    would reach `gh` as a release with blank notes, which is the absence the tool
    produced rendered as the notes somebody wrote.
    """
    text = "# Changelog\n\n## [0.4.0]\n\n## [0.3.0]\n\n- Something.\n"
    found = release_publish.notes_section(text, "0.4.0")
    assert found["state"] == "empty"
    assert found["body"] in (None, "")
    # Positive control in the same fixture: the harness can see a body when there
    # is one, so `empty` above is a reading and not a broken extractor.
    assert release_publish.notes_section(text, "0.3.0")["state"] == "found"


def test_a_heading_shaped_line_inside_a_fence_is_not_a_boundary():
    """A changelog entry quoting a changelog is not exotic, and a `## [x]` line at
    column 0 inside a fence read as a real heading truncates the notes there. That is
    worse than either absence this module reports: not a state, but wrong content
    returned as `found`, with nothing downstream able to tell.
    """
    text = (
        "# Changelog\n\n"
        "## [0.3.0] - 2026-08-14\n\n"
        "- Before the fence.\n\n"
        "```markdown\n"
        "## [9.9.9] - not a real release\n"
        "```\n\n"
        "- After the fence.\n\n"
        "## [0.2.0] - 2026-07-01\n\n"
        "- Older.\n"
    )
    found = release_publish.notes_section(text, "0.3.0")
    assert found["state"] == "found"
    assert "- Before the fence." in found["body"]
    # The whole point. Without fence tracking the body stops at the fenced line and
    # this is the assertion that fails.
    assert "- After the fence." in found["body"]
    # Still bounded by the next *real* heading, so the fix did not simply widen it.
    assert "- Older." not in found["body"]
    # And the fenced line never becomes a section of its own.
    assert release_publish.notes_section(text, "9.9.9")["state"] == "missing"


def test_a_tilde_fence_closes_only_on_a_tilde_fence():
    """```` ``` ```` inside a `~~~` block does not close it, and an info string on a
    closing fence does not either. Both are how a hand-maintained CHANGELOG.md ends
    up with an extractor that silently disagrees with the renderer above it.
    """
    text = (
        "## [1.0.0]\n\n"
        "~~~\n"
        "```\n"
        "## [8.8.8]\n"
        "~~~\n\n"
        "- Real content.\n"
    )
    found = release_publish.notes_section(text, "1.0.0")
    assert found["state"] == "found"
    assert "- Real content." in found["body"]
    assert release_publish.notes_section(text, "8.8.8")["state"] == "missing"


def test_a_crlf_changelog_extracts_the_same_notes():
    """Reasoned, not observed: a Windows checkout with `core.autocrlf` writes CRLF,
    and `notes_section` is a pure function that can be handed the bytes directly.
    """
    found = release_publish.notes_section(CHANGELOG.replace("\n", "\r\n"), "0.3.0")
    assert found["state"] == "found"
    assert "The thing that was fixed (#58)." in found["body"].replace("\r\n", "\n")
    assert "An older thing nobody is releasing today." not in found["body"]


def test_a_version_with_no_section_is_missing():
    found = release_publish.notes_section(CHANGELOG, "9.9.9")
    assert found["state"] == "missing"


def test_a_version_is_matched_whole_and_not_by_prefix():
    """`0.3` must not match `## [0.3.0]`, and `0.3.0` must not match `## [0.3.0-rc1]`."""
    assert release_publish.notes_section(CHANGELOG, "0.3")["state"] == "missing"
    text = "## [0.3.0-rc1]\n\n- A candidate.\n"
    assert release_publish.notes_section(text, "0.3.0")["state"] == "missing"
    assert release_publish.notes_section(text, "0.3.0-rc1")["state"] == "found"


# ------------------------------------------------------------------- the command


def test_the_planned_command_carries_verify_tag():
    """The flag this whole issue turns on, asserted by spelling the argv out rather
    than by watching a mock get called.
    """
    plan = release_publish.plan(
        config=_config(create_release=True, draft=False, latest=True),
        tag="v0.3.0",
        notes_path="/tmp/notes.md",
        gh="gh",
    )
    assert plan["state"] == release_publish.STATE_CREATE
    assert plan["command"] == [
        "gh",
        "release",
        "create",
        "v0.3.0",
        "--repo",
        "owner/name",
        "--title",
        "v0.3.0",
        "--notes-file",
        "/tmp/notes.md",
        "--verify-tag",
        "--latest",
    ]


def test_a_draft_is_a_draft_and_a_published_release_is_not():
    drafted = release_publish.plan(
        config=_config(create_release=True, draft=True),
        tag="v0.3.0",
        notes_path="/tmp/notes.md",
        gh="gh",
    )
    published = release_publish.plan(
        config=_config(create_release=True, draft=False, latest=False),
        tag="v0.3.0",
        notes_path="/tmp/notes.md",
        gh="gh",
    )
    assert "--draft" in drafted["command"]
    assert "--draft" not in published["command"]
    # A draft cannot be Latest, so no latest flag is emitted for one at all --
    # asserted rather than assumed, because `--latest=false` on a draft reads as a
    # deliberate "not latest" that gh has no published release to apply it to.
    assert not [arg for arg in drafted["command"] if arg.startswith("--latest")]
    assert "--latest=false" in published["command"]
    # Both plans still verify the tag. Neither branch may lose it.
    assert "--verify-tag" in drafted["command"]
    assert "--verify-tag" in published["command"]


# ------------------------------------------------------------------- the policy


def test_an_unstated_policy_does_not_publish_and_says_which_key_would():
    """The conservative default. Publishing notifies watchers and a published
    release is not undoable the way a draft is, so an absent key is never read as
    consent -- but it is named out loud, because a silent skip is the same defect
    one layer down.
    """
    plan = release_publish.plan(
        config=_config(), tag="v0.3.0", notes_path="/tmp/notes.md", gh="gh"
    )
    assert plan["state"] == release_publish.STATE_SKIPPED
    assert plan["command"] is None
    assert "create_release" in plan["reason"]


def test_a_repo_that_deliberately_tags_without_releasing_is_skipped():
    """Some projects tag without releasing, and that is a policy rather than a
    failure. Paired with its own positive control, because a `plan` that returned
    `skipped` unconditionally would satisfy the first assertion alone.
    """
    off = release_publish.plan(
        config=_config(create_release=False),
        tag="v0.3.0",
        notes_path="/tmp/notes.md",
        gh="gh",
    )
    on = release_publish.plan(
        config=_config(create_release=True),
        tag="v0.3.0",
        notes_path="/tmp/notes.md",
        gh="gh",
    )
    assert off["state"] == release_publish.STATE_SKIPPED
    assert on["state"] == release_publish.STATE_CREATE


def test_a_missing_gh_is_could_not_run_and_never_a_skip():
    plan = release_publish.plan(
        config=_config(create_release=True), tag="v0.3.0", notes_path="/tmp/notes.md", gh=None
    )
    assert plan["state"] == release_publish.STATE_COULD_NOT_RUN
    assert plan["command"] is None
    assert plan["state"] != release_publish.STATE_SKIPPED


def test_no_notes_path_is_could_not_run():
    plan = release_publish.plan(
        config=_config(create_release=True), tag="v0.3.0", notes_path=None, gh="gh"
    )
    assert plan["state"] == release_publish.STATE_COULD_NOT_RUN


# ----------------------------------------------------------- config: the policy keys


def _valid_config():
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
        "release": {"tag_pattern": "v{version}", "merge_method": "squash"},
    }


def test_the_publish_keys_validate():
    config = _valid_config()
    config["release"].update({"create_release": True, "draft": False, "latest": True})
    assert oss_config.validate(config) == []


def test_the_publish_keys_must_be_booleans():
    """`"yes"` is a string and every string is truthy, so a config that reads as a
    deliberate `false` publishes. The `not in problem` half matters: before the keys
    were known, this passed on the unknown-key refusal instead -- a green that said
    nothing about the type check it was written for.
    """
    for key in ("create_release", "draft", "latest"):
        config = _valid_config()
        config["release"][key] = "yes"
        problems = oss_config.validate(config)
        assert any(key in p and "unknown key" not in p for p in problems), (key, problems)


def test_a_draft_marked_latest_is_refused_because_it_cannot_be_both():
    """gh will not mark a draft as Latest. Accepting the pair means the config
    states an outcome the release path can never produce, and the maintainer finds
    out from a failed release rather than from the validator.
    """
    config = _valid_config()
    config["release"].update({"create_release": True, "draft": True, "latest": True})
    problems = oss_config.validate(config)
    assert any("latest" in p and "unknown key" not in p for p in problems), problems
    # Positive control on the same pair of keys: each alone is fine, so the refusal
    # above is about the combination and not about either key existing.
    fine = _valid_config()
    fine["release"].update({"create_release": True, "draft": True, "latest": False})
    assert oss_config.validate(fine) == []


def test_the_publish_policy_defaults_are_the_conservative_ones():
    policy = oss_config.release_publish_policy({"repo": "owner/name"})
    assert policy["create"] is False
    assert policy["draft"] is True
    assert policy["latest"] is False
    assert policy["stated"] is False


def test_a_sibling_key_does_not_state_a_decision_about_publishing():
    """`stated` is about `create_release` alone. A repo that set only `draft` has said
    how it would publish, not whether to -- and a `stated` that unions the three keys
    reported that repo, in words, as having chosen not to publish. A decision it never
    made, rendered exactly like one it did.
    """
    partial = {"repo": "owner/name", "release": {"draft": True}}
    policy = oss_config.release_publish_policy(partial)
    assert policy["create"] is False
    assert policy["stated"] is False
    plan = release_publish.plan(
        config=partial, tag="v0.3.0", notes_path="/tmp/notes.md", gh="gh"
    )
    assert plan["state"] == release_publish.STATE_SKIPPED
    assert "unset" in plan["reason"]
    # Positive control on the same key: an explicit false does say so, so the reason
    # above is a reading of the config and not one sentence for every skip.
    explicit = release_publish.plan(
        config=_config(create_release=False),
        tag="v0.3.0",
        notes_path="/tmp/notes.md",
        gh="gh",
    )
    assert "unset" not in explicit["reason"]
    assert "false" in explicit["reason"]


def test_a_stated_policy_wins_over_the_defaults():
    policy = oss_config.release_publish_policy(
        _config(create_release=True, draft=False, latest=True)
    )
    assert (policy["create"], policy["draft"], policy["latest"]) == (True, False, True)
    assert policy["stated"] is True


def test_this_repo_publishes_and_says_so_in_its_own_config():
    """The owner's decision for this repository, carried explicitly rather than
    inherited: the value a maintainer gets should be one somebody chose. The shipped
    default is the conservative one, which is why this assertion is about *this*
    repo's file and not about the module.
    """
    config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    policy = oss_config.release_publish_policy(config)
    assert policy["stated"] is True
    assert policy["create"] is True
    assert policy["draft"] is False
    assert policy["latest"] is True


# ------------------------------------------------------------------- execution


# The fake-gh fixture is a POSIX shebang script, so the tests that spawn it are
# POSIX-only and say so rather than being quietly absent on the platform they do not
# run on. Windows honours no shebang, and a `.cmd` shim is not obviously spawnable
# through `subprocess` with `shell=False` either -- which is the trap, not the
# inconvenience: an unspawnable fixture raises a spawn error, `execute` reports that
# as `could-not-create`, and the test asserting `could-not-create` on a *failing gh*
# then passes for a reason that has nothing to do with gh's exit code. A green leg
# measuring its own fixture is worse than a named skip.
#
# So the three-state behaviour is measured on every platform by
# `test_execute_tells_the_states_apart_without_any_fake_binary` below, which spawns
# the running interpreter -- the one executable every leg is guaranteed to have.
posix_only = pytest.mark.skipif(
    os.name == "nt",
    reason="the fake gh is a shebang script; Windows covers execute() via sys.executable",
)


def _fake_gh(tmp_path, exit_code=0):
    """A `gh` that records the argv it was handed. The seam is the process boundary,
    so what the test reads back is the command that really ran.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    record = tmp_path / "argv.json"
    impl = tmp_path / "gh_impl.py"
    impl.write_text(
        "import json, sys\n"
        "open({0!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        "sys.stderr.write('release failed: no such tag' + chr(10))\n"
        "sys.exit({1})\n".format(str(record), exit_code),
        encoding="utf-8",
    )
    script = tmp_path / "gh"
    script.write_text(
        "#!{0}\nimport runpy\nrunpy.run_path({1!r}, run_name='__main__')\n".format(
            sys.executable, str(impl)
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script, record


def test_execute_tells_the_states_apart_without_any_fake_binary(tmp_path):
    """Every platform, including the ones the shebang fixture cannot reach. The plan
    is hand-built here -- the one place in this file that does that -- because the
    subject is `execute`'s reading of an exit code and nothing else.
    """
    base = {
        "state": release_publish.STATE_CREATE,
        "tag": "v0.3.0",
        "repo": "owner/name",
        "draft": False,
        "latest": True,
    }
    ok = dict(base, command=[sys.executable, "-c", "import sys; sys.exit(0)"])
    bad = dict(
        base,
        command=[sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"],
    )
    assert release_publish.execute(ok)["state"] == release_publish.STATE_CREATED
    failed = release_publish.execute(bad)
    assert failed["state"] == release_publish.STATE_COULD_NOT_CREATE
    assert "boom" in failed["detail"]
    # A command that cannot be spawned at all is could-not-create too, and never a
    # traceback out of a release path.
    missing = dict(base, command=[str(tmp_path / "no-such-gh"), "release", "create"])
    assert release_publish.execute(missing)["state"] == release_publish.STATE_COULD_NOT_CREATE


@posix_only
def test_executing_runs_the_command_that_was_planned_verify_tag_and_all(tmp_path):
    script, record = _fake_gh(tmp_path, exit_code=0)
    notes = tmp_path / "notes.md"
    notes.write_text("- A thing.\n", encoding="utf-8")
    result = release_publish.execute(
        release_publish.plan(
            config=_config(create_release=True, draft=False, latest=True),
            tag="v0.3.0",
            notes_path=str(notes),
            gh=str(script),
        )
    )
    assert result["state"] == release_publish.STATE_CREATED, result
    argv = json.loads(record.read_text(encoding="utf-8"))
    assert argv[:3] == ["release", "create", "v0.3.0"]
    assert "--verify-tag" in argv
    assert "--latest" in argv


@posix_only
def test_a_failing_call_is_could_not_create_and_never_reads_as_created(tmp_path):
    script, _ = _fake_gh(tmp_path, exit_code=1)
    notes = tmp_path / "notes.md"
    notes.write_text("- A thing.\n", encoding="utf-8")
    result = release_publish.execute(
        release_publish.plan(
            config=_config(create_release=True, draft=False, latest=True),
            tag="v0.3.0",
            notes_path=str(notes),
            gh=str(script),
        )
    )
    assert result["state"] == release_publish.STATE_COULD_NOT_CREATE
    assert result["state"] != release_publish.STATE_CREATED
    assert "no such tag" in result["detail"]


@posix_only
def test_executing_a_skipped_plan_creates_nothing(tmp_path):
    script, record = _fake_gh(tmp_path)
    result = release_publish.execute(
        release_publish.plan(
            config=_config(create_release=False),
            tag="v0.3.0",
            notes_path="/tmp/notes.md",
            gh=str(script),
        )
    )
    assert result["state"] == release_publish.STATE_SKIPPED
    assert not record.exists()


# ------------------------------------------------------------------------- CLI


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "release_publish.py")] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _repo(tmp_path, changelog=CHANGELOG, **release):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    block = {"tag_pattern": "v{version}"}
    block.update(release)
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/name", "release": block}), encoding="utf-8"
    )
    return tmp_path


def test_the_cli_prints_the_command_it_would_run_without_running_it(tmp_path):
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    notes_out = tmp_path / "notes.md"
    done = _run(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--notes-out",
            str(notes_out),
            # Named rather than resolved: whether a runner has gh on PATH is not what
            # this test is about, and a green that depends on it is a green about the
            # runner.
            "--gh",
            "gh",
            "--json",
        ],
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["state"] == release_publish.STATE_CREATE
    assert "--verify-tag" in payload["command"]
    assert "The thing that was fixed (#58)." in notes_out.read_text(encoding="utf-8")


def test_the_cli_exit_code_separates_skipped_from_could_not_run(tmp_path):
    skipped = _run(
        [
            "--repo",
            str(_repo(tmp_path / "a", create_release=False)),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--json",
        ],
        cwd=tmp_path,
    )
    assert skipped.returncode == release_publish.EXIT_SKIPPED
    assert json.loads(skipped.stdout)["state"] == release_publish.STATE_SKIPPED

    absent = _run(
        [
            "--repo",
            str(_repo(tmp_path / "b", create_release=True)),
            "--version",
            "9.9.9",
            "--tag",
            "v9.9.9",
            "--json",
        ],
        cwd=tmp_path,
    )
    assert absent.returncode == release_publish.EXIT_COULD_NOT_RUN
    assert json.loads(absent.stdout)["state"] == release_publish.STATE_COULD_NOT_RUN
    assert skipped.returncode != absent.returncode


def test_a_missing_changelog_is_could_not_run_and_not_a_traceback(tmp_path):
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/name", "release": {"create_release": True}}),
        encoding="utf-8",
    )
    done = _run(
        ["--repo", str(tmp_path), "--version", "0.3.0", "--tag", "v0.3.0", "--json"],
        cwd=tmp_path,
    )
    assert done.returncode == release_publish.EXIT_COULD_NOT_RUN
    assert "Traceback" not in done.stderr
    assert json.loads(done.stdout)["state"] == release_publish.STATE_COULD_NOT_RUN


# ------------------------------------------------- the CLI, end to end, in process
#
# The subprocess tests above prove the entry point runs. These drive `main` directly,
# which is the only way `--execute` gets exercised at all -- and an unexercised
# `--execute` is a release path nothing has ever walked.


@posix_only
def test_execute_end_to_end_creates_the_release_and_ran_verify_tag(tmp_path):
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    script, record = _fake_gh(tmp_path / "bin", exit_code=0)
    code = release_publish.main(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--notes-out",
            str(tmp_path / "notes.md"),
            "--gh",
            str(script),
            "--execute",
        ]
    )
    assert code == 0
    argv = json.loads(record.read_text(encoding="utf-8"))
    assert "--verify-tag" in argv
    assert "--notes-file" in argv
    notes = Path(argv[argv.index("--notes-file") + 1]).read_text(encoding="utf-8")
    assert "The thing that was fixed (#58)." in notes


@posix_only
def test_execute_reports_could_not_create_when_gh_fails(tmp_path, capsys):
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    script, _ = _fake_gh(tmp_path / "bin", exit_code=1)
    code = release_publish.main(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--notes-out",
            str(tmp_path / "notes.md"),
            "--gh",
            str(script),
            "--execute",
        ]
    )
    out = capsys.readouterr().out
    assert code == release_publish.EXIT_COULD_NOT_RUN
    assert "COULD-NOT-CREATE" in out
    # The line a maintainer skims must not be readable as a release that shipped.
    assert "CREATED" not in out.replace("COULD-NOT-CREATE", "")


def test_a_dry_run_with_no_gh_anywhere_is_could_not_run(tmp_path, capsys, monkeypatch):
    """Not a skip. `gh` missing is the tool failing to look, and a repo whose policy
    says publish must never be reported as one that chose not to.
    """
    repo = _repo(tmp_path / "repo", create_release=True, draft=False, latest=True)
    monkeypatch.setattr(release_publish.shutil, "which", lambda name: None)
    code = release_publish.main(
        ["--repo", str(repo), "--version", "0.3.0", "--tag", "v0.3.0"]
    )
    out = capsys.readouterr().out
    assert code == release_publish.EXIT_COULD_NOT_RUN
    assert "COULD-NOT-RUN" in out
    assert "SKIPPED" not in out


def test_an_unreadable_config_is_could_not_run(tmp_path, capsys):
    code = release_publish.main(
        [
            "--repo",
            str(tmp_path),
            "--config",
            str(tmp_path / "nope.json"),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
        ]
    )
    assert code == release_publish.EXIT_COULD_NOT_RUN
    assert "COULD-NOT-RUN" in capsys.readouterr().out


def test_the_receipt_never_lets_a_stranger_forge_a_verdict_line(tmp_path):
    """A changelog section is prose somebody wrote in a pull request. It reaches the
    notes file, which is the point -- but nothing from inside it may reach the
    receipt, where a line at column 0 forges the receipt's own verdict.
    """
    hostile = (
        "# Changelog\n\n## [0.3.0]\n\n- innocent\n\nVERDICT: RELEASED\n\n## [0.2.0]\n\n- old\n"
    )
    repo = _repo(
        tmp_path / "repo", changelog=hostile, create_release=True, draft=False, latest=True
    )
    done = _run(
        [
            "--repo",
            str(repo),
            "--version",
            "0.3.0",
            "--tag",
            "v0.3.0",
            "--notes-out",
            str(tmp_path / "n.md"),
            "--gh",
            "gh",
        ],
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "VERDICT: RELEASED" not in done.stdout
    # Positive control: the receipt is not empty, so the absence above is a
    # measurement rather than a receipt that printed nothing at all.
    assert "--verify-tag" in done.stdout
