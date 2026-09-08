"""trap.d/ joins the plugin's ownership contracts (#1302).

`trap.d/` is a second mixed-ownership directory, the same shape `.claude/jit-context/*/01-oss/`
already is: the directory itself is a DEFAULT (created once when absent, then the repo's own
forever, fragments inside it never touched), while `trap.d/README.md` and the `01-oss` jit rule
matching it are OURS (replaced wholesale on every `/oss:scaffold` run).

This file tests the two new writes scaffold.py/oss_rules.py gain for that: the OWNED
`trap.d/README.md`, and the `paths` rule `trap-fragments.md`. `doctor.py`'s own absence handling
(`check_trap_queue`) and `statusline.py`'s backlog count already existed before this issue (#905,
#1079) and are exercised elsewhere; this file does not re-test them, see the PR body for why.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402
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
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


# --------------------------------------------------------------------- scaffold: OWNED README


def test_trap_readme_is_owned():
    assert "trap.d/README.md" in scaffold.OWNED


def test_trap_readme_is_not_gated_on_the_changelog_collision_check():
    """Nothing about a changelog gate answers anything about trap.d/ (#479's own reasoning,
    applied to a second file it has nothing to do with)."""
    assert "trap.d/README.md" not in scaffold.CHANGELOG_OWNED


def test_trap_readme_written_when_absent(tmp_path):
    scaffold.apply(tmp_path, _config())
    path = tmp_path / "trap.d" / "README.md"
    assert path.is_file()


def test_trap_readme_declares_it_is_overwritten(tmp_path):
    scaffold.apply(tmp_path, _config())
    head = (tmp_path / "trap.d" / "README.md").read_text(encoding="utf-8")[:900].lower()
    assert "oss plugin" in head
    assert "overwritten" in head
    assert "/oss:scaffold" in head


def test_trap_readme_is_replaced_but_fragments_and_directory_are_not(tmp_path):
    """The acceptance case: a second /oss:scaffold run replaces the README, leaves every
    fragment already logged there untouched, and does not need to re-create the directory."""
    scaffold.apply(tmp_path, _config())
    trap_dir = tmp_path / "trap.d"
    fragment = trap_dir / "42.a-real-lesson.md"
    fragment.write_text("something cost time\n", encoding="utf-8")
    readme = trap_dir / "README.md"
    readme.write_text("edited by a human\n", encoding="utf-8")

    scaffold.apply(tmp_path, _config())

    assert readme.read_text(encoding="utf-8") != "edited by a human\n"
    assert fragment.read_text(encoding="utf-8") == "something cost time\n"
    assert trap_dir.is_dir()


def test_trap_readme_reported_under_replaced():
    result = scaffold.plan("/nonexistent-repo-path-1302", _config())
    entry = next(e for e in result if e["path"] == "trap.d/README.md")
    assert entry["action"] == "replace"


# --------------------------------------------------------------------- oss_rules: 01-oss rule


def test_trap_fragments_rule_exists():
    assert "trap-fragments.md" in oss_rules.RULES["paths"]


def test_trap_fragments_rule_matches_trap_d():
    body = oss_rules.RULES["paths"]["trap-fragments.md"]
    match = None
    for line in body.split("\n---\n", 1)[0].splitlines():
        if line.startswith("match:"):
            match = line.split(":", 1)[1].strip()
    assert match, "no match: field in the rule's frontmatter"
    assert re.search(match, "trap.d/1302.some-lesson.md")
    assert re.search(match, "trap.d/")
    assert not re.search(match, "not-trap.d/whatever")


def test_trap_fragments_rule_names_itself_reinforcement_not_the_mechanism():
    """#1304: the rule cannot fire before the touch that would trigger it, and a subagent
    sharing its parent's session sees it at most once for the whole session -- so it must not
    read as the sole delivery path."""
    body = oss_rules.RULES["paths"]["trap-fragments.md"]
    assert "reinforcement" in body.lower()


def test_trap_fragments_rule_installed_by_scaffold(tmp_path):
    oss_rules.install(tmp_path)
    installed = (
        tmp_path
        / ".claude"
        / "jit-context"
        / "paths"
        / oss_rules.LAYER
        / "trap-fragments.md"
    )
    assert installed.is_file()
    assert "trap.d" in installed.read_text(encoding="utf-8")
