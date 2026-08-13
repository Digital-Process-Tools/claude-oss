"""Files the plugin owns inside someone else's repo.

Three contracts, and the whole point is that they are legible from inside the repo
rather than only in our documentation:

* **theirs** -- never read, never written.
* **defaults** -- created when absent, then theirs forever. Never overwritten.
* **ours** -- replaced on every update, and each one says so in its own first lines.

A copied file with no visible owner is a file somebody edits and loses. The header is
what makes the third contract survive being discovered six months later by a person
who was not in this conversation.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "ci": {"required_checks": 0},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


def test_there_are_owned_files():
    assert scaffold.OWNED, "no owned files -- every check below would vacuously pass"


def test_owned_files_live_in_one_directory():
    """Ownership by location, not by whether someone noticed a comment. One folder,
    one rule, and a reader can see the boundary without opening anything.
    """
    outside = [p for p in scaffold.OWNED if not p.startswith(scaffold.OWNED_DIR + "/")]
    assert outside == [".github/workflows/oss-changelog.yml"], outside


def test_the_owned_directory_explains_itself():
    """The README is the primary signal. A directory of generated files with no note
    is a directory somebody edits.
    """
    assert scaffold.OWNED_DIR + "/README.md" in scaffold.OWNED


def test_the_changelog_gate_and_its_script_are_owned():
    """The gate calls the script, and a runner checking out the managed repo has no
    plugin to reach into. Shipping one without the other is a red build on day one.
    """
    assert ".github/workflows/oss-changelog.yml" in scaffold.OWNED
    assert scaffold.OWNED_DIR + "/assemble_changelog.py" in scaffold.OWNED


def test_owned_files_are_written_on_apply(tmp_path):
    scaffold.apply(tmp_path, _config())
    for path in scaffold.OWNED:
        assert (tmp_path / path).is_file(), path


def test_owned_files_are_replaced_on_the_next_apply(tmp_path):
    """This is the contract that makes updates possible at all."""
    scaffold.apply(tmp_path, _config())
    target = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    target.write_text("edited by a human\n", encoding="utf-8")

    scaffold.apply(tmp_path, _config())
    assert target.read_text(encoding="utf-8") != "edited by a human\n"


def test_a_default_is_never_replaced_even_after_an_update(tmp_path):
    """The other side of it: SECURITY.md is a default, so it becomes theirs the
    moment it exists.
    """
    scaffold.apply(tmp_path, _config())
    theirs = tmp_path / "SECURITY.md"
    theirs.write_text("our own policy\n", encoding="utf-8")

    scaffold.apply(tmp_path, _config())
    assert theirs.read_text(encoding="utf-8") == "our own policy\n"


def test_every_owned_file_declares_that_it_is_overwritten(tmp_path):
    """Said in the file, because that is where someone about to edit it is looking."""
    scaffold.apply(tmp_path, _config())
    for path in scaffold.OWNED:
        head = (tmp_path / path).read_text(encoding="utf-8")[:900].lower()
        assert "oss plugin" in head, path
        assert "overwritten" in head, path
        assert "/oss:scaffold" in head, path


def test_the_header_tells_you_what_to_do_instead(tmp_path):
    """A prohibition with no alternative gets ignored by whoever needs the change."""
    scaffold.apply(tmp_path, _config())
    head = (tmp_path / ".github" / "workflows" / "oss-changelog.yml").read_text(encoding="utf-8")
    assert "copy it" in head.lower()


def test_the_plan_distinguishes_all_three_contracts(tmp_path):
    (tmp_path / "SECURITY.md").write_text("ours\n", encoding="utf-8")
    actions = {entry["path"]: entry["action"] for entry in scaffold.plan(tmp_path, _config())}
    assert actions["SECURITY.md"] == "present"
    assert actions["CLAUDE.md"] == "create"
    assert actions[".github/workflows/oss-changelog.yml"] == "replace"


def test_the_copied_script_is_the_one_the_plugin_ships(tmp_path):
    """Copied at write time from the plugin's own file rather than duplicated into a
    template string: two copies of 1164 lines drift, and only one of them is tested.
    """
    scaffold.apply(tmp_path, _config())
    copied = (tmp_path / scaffold.OWNED_DIR / "assemble_changelog.py").read_text(
        encoding="utf-8"
    )
    source = (REPO_ROOT / "scripts" / "assemble_changelog.py").read_text(encoding="utf-8")
    assert source.splitlines()[-1] in copied
    assert "UNTAGGED_RELEASES = frozenset()" in copied


def test_the_copied_script_still_carries_no_other_repos_releases(tmp_path):
    """The reason this file was edited at all. A regression here would reintroduce
    confident findings about a release history the managed repo has never had.
    """
    scaffold.apply(tmp_path, _config())
    copied = (tmp_path / scaffold.OWNED_DIR / "assemble_changelog.py").read_text(
        encoding="utf-8"
    )
    for version in ("0.19.0", "0.18.0", "0.11.0"):
        assert '"{}"'.format(version) not in copied, version
