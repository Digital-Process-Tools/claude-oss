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


def test_a_repo_whose_runner_is_not_pytest_gets_no_pytest_advice():
    """The paragraph is pytest-specific -- `--durations`, `--cov`,
    `pyproject.toml`'s `addopts` -- and `.oss.json`'s `test_command` is an
    arbitrary shell command. #946's finding on doctor's own half of #932 is
    the same finding here, one file over: a Go repo told to configure
    `[tool.pytest.ini_options]` has been handed a fact about somebody else's
    language, permanently, in a file it will read on every session.
    """
    text = scaffold.render("CLAUDE.md", _config(test_command="go test ./..."))
    assert "pytest" not in text, (
        "scaffold wrote pytest advice into a repo whose test_command plainly "
        "names another runner"
    )
    assert "test_measurement_configured" not in text


def test_an_undetected_test_command_gets_no_pytest_advice():
    """Scaffold's predicate is deliberately NOT doctor's. An absent
    `test_command` is not evidence against pytest, so doctor keeps asking --
    a maintainer can answer it. This paragraph is written once into somebody
    else's repository and stays, and the template's own rule for the line
    directly above it is that a guess here becomes an instruction, so an
    unprobed repo gets no runner named at all.
    """
    text = scaffold.render("CLAUDE.md", _config(test_command=None))
    assert "not detected" in text
    assert "pytest" not in text


def test_a_pytest_repo_still_gets_the_advice():
    """The positive control for both must-not-fire assertions above: with a
    pytest-shaped command the paragraph is present, so a template that simply
    stopped rendering it would fail here rather than pass all three."""
    text = scaffold.render("CLAUDE.md", _config(test_command="python -m pytest tests/"))
    assert "test_measurement_configured" in text
    assert "--durations" in text
