"""#932: scaffold's default CLAUDE.md recommends -- never forces -- setting
`test_measurement_configured`.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import scaffold  # noqa: E402


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [],
        "changelog_dir": None,
        "docs_targets": [],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/x.json",
    }
    config.update(overrides)
    return config


def test_claude_md_recommends_setting_the_key():
    text = scaffold.render("CLAUDE.md", _config())
    assert "test_measurement_configured" in text, (
        "the default CLAUDE.md must recommend the attestation, not just doctor's "
        "own finding text -- or scaffold ships no signal at all for a repo that "
        "never runs `doctor` before its first change"
    )


def test_it_is_a_recommendation_not_an_instruction_to_set_it_to_a_fixed_value():
    """The must-not-fire half: nothing in the template writes the key INTO
    .oss.json -- it only recommends the maintainer set it once they have
    confirmed their own suite. `render("CLAUDE.md", ...)` must not itself
    mutate `config`."""
    config = _config()
    before = dict(config)
    scaffold.render("CLAUDE.md", config)
    assert config == before, "rendering a template must not mutate the config passed in"
    assert "test_measurement_configured" not in config, (
        "scaffold recommends the key in prose; it must never invent the value "
        "in .oss.json itself -- that is a maintainer attestation (#932)"
    )
