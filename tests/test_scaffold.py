"""Repo furniture: CLAUDE.md, SECURITY.md, issue templates, dependabot, settings.

The maintainer loop was not the only thing that drifted between repos. So did the
furniture around it -- one repo has no `.github/` at all, another's SECURITY.md is
a different document with the same name. Scaffolding is how that stops.

The rule that shapes every test here: **this writes into someone else's repo.** It
never overwrites, it shows before it writes, and a file that already exists is
reported as present rather than quietly replaced.
"""

import json
import re
import sys
from pathlib import Path

import pytest

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
        "version_sites": [".claude-plugin/plugin.json", "README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": ["priority-high"], "lanes": []},
        "ci": {"required_checks": 4},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


# ----------------------------------------------------------------------------- plan


def test_every_template_is_planned_on_an_empty_repo(tmp_path):
    plan = scaffold.plan(tmp_path, _config())
    assert plan, "no entries -- the checks below would vacuously pass"
    defaults = {e["path"] for e in plan if e["action"] == "create"}
    assert defaults == set(scaffold.TEMPLATES)
    owned = {e["path"] for e in plan if e["action"] == "replace"}
    assert owned == set(scaffold.OWNED)


def test_an_existing_file_is_reported_present_never_overwritten(tmp_path):
    target = tmp_path / "SECURITY.md"
    target.write_text("the repo's own policy\n", encoding="utf-8")
    plan = scaffold.plan(tmp_path, _config())
    entry = next(e for e in plan if e["path"] == "SECURITY.md")
    assert entry["action"] == "present"
    assert target.read_text(encoding="utf-8") == "the repo's own policy\n"


def test_apply_writes_only_the_missing_files(tmp_path):
    (tmp_path / "SECURITY.md").write_text("keep me\n", encoding="utf-8")
    written = scaffold.apply(tmp_path, _config())["created"]
    assert "SECURITY.md" not in written
    assert (tmp_path / "SECURITY.md").read_text(encoding="utf-8") == "keep me\n"
    assert "CLAUDE.md" in written
    assert (tmp_path / "CLAUDE.md").is_file()


def test_apply_creates_parent_directories(tmp_path):
    scaffold.apply(tmp_path, _config())
    assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").is_file()


def test_a_second_apply_creates_no_defaults_but_still_replaces_ours(tmp_path):
    """Idempotent for defaults, deliberately not for the files we own -- that is the
    contract that lets an update reach a repo at all.
    """
    first = scaffold.apply(tmp_path, _config())
    second = scaffold.apply(tmp_path, _config())
    assert first["created"]
    assert second["created"] == []
    assert second["replaced"] == sorted(scaffold.OWNED)


def test_apply_refuses_a_config_that_does_not_validate(tmp_path):
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.apply(tmp_path, {"repo": "owner/name"})


def test_plan_refuses_to_escape_the_repo_root(tmp_path):
    """Template paths are literals in this file, but a literal is one edit away from
    a variable. The containment check is on the write path, not on the author.
    """
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render_to(tmp_path, "../escape.md", "x")


# ---------------------------------------------------------------------------- radar


def test_a_repo_with_no_supertool_config_has_nothing_to_report(tmp_path):
    """Nothing there means the template creates one with radar already on, so there
    is no finding to make.
    """
    assert scaffold.check_radar(tmp_path) == []


def test_an_existing_config_without_radar_tiers_is_reported(tmp_path):
    (tmp_path / ".supertool.json").write_text('{"presets": ["git"]}', encoding="utf-8")
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "no-tiers"
    assert "radar_tiers" in findings[0]["detail"]


def test_an_existing_config_with_radar_tiers_is_clean(tmp_path):
    (tmp_path / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    assert scaffold.check_radar(tmp_path) == []


def test_an_unreadable_config_is_unknown_not_off(tmp_path):
    """The third state. Reporting "no radar" for a file we could not parse would send
    someone to add a block that is already there.
    """
    (tmp_path / ".supertool.json").write_text("{ broken", encoding="utf-8")
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "unreadable"


def test_the_shipped_config_turns_radar_on(tmp_path):
    """The point of shipping it: a managed repo has a board the first time someone
    opens it, rather than after they discover the op exists.
    """
    scaffold.apply(tmp_path, _config())
    assert scaffold.check_radar(tmp_path) == []
    written = json.loads((tmp_path / ".supertool.json").read_text(encoding="utf-8"))
    assert written["ops"]["radar"]["radar_tiers"]


def test_an_existing_supertool_config_is_never_replaced(tmp_path):
    (tmp_path / ".supertool.json").write_text('{"presets": ["mine"]}', encoding="utf-8")
    scaffold.apply(tmp_path, _config())
    assert "mine" in (tmp_path / ".supertool.json").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- render


def test_claude_md_names_this_repo_not_another(tmp_path):
    body = scaffold.render("CLAUDE.md", _config(repo="acme/widget", default_branch="trunk"))
    assert "acme/widget" in body
    assert "trunk" in body


def test_claude_md_carries_the_test_command_when_known():
    assert "pytest" in scaffold.render("CLAUDE.md", _config())


def test_claude_md_says_unknown_rather_than_guessing_a_test_command():
    body = scaffold.render("CLAUDE.md", _config(test_command=None))
    assert "not detected" in body
    assert "pytest" not in body


def test_claude_md_states_the_untrusted_input_rule():
    """The furniture carries it too. A contributor reading CLAUDE.md is the person
    most likely to paste an issue body into a prompt.
    """
    assert "data, not instructions" in scaffold.render("CLAUDE.md", _config())


def test_no_template_hardcodes_a_sibling_repo():
    """The whole point of extracting this was that the copies named their own repo."""
    for name in scaffold.TEMPLATES:
        body = scaffold.render(name, _config())
        for spelling in ("Digital-Process-Tools/claude-", "claude-supertool", "claude-remember"):
            assert spelling not in body, "{} hardcodes {}".format(name, spelling)


def test_rendering_an_unknown_template_is_an_error_not_an_empty_string():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render("NOT_A_TEMPLATE.md", _config())


def test_every_template_renders_without_a_leftover_placeholder():
    """An unsubstituted placeholder reaching a committed file is silent and permanent."""
    leftover = re.compile(r"\{[a-z_]+\}")
    for name in scaffold.TEMPLATES:
        body = scaffold.render(name, _config())
        found = leftover.search(body)
        assert found is None, "{} still contains {}".format(name, found and found.group(0))


def test_a_null_config_value_never_reaches_a_rendered_file_as_None():
    """`None` cannot be checked for as a bare word -- "None of this is acceptable" is
    ordinary English and appears in the code of conduct. What matters is that a null
    config value renders as prose, so this asserts on the template that interpolates.
    """
    body = scaffold.render("CLAUDE.md", _config(test_command=None))
    assert "None" not in body
    assert "not detected" in body
