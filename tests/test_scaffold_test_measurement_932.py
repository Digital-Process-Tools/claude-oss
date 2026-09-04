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


def test_a_repo_whose_runner_is_not_pytest_still_gets_the_neutral_advice():
    """#955: the paragraph used to be pytest-specific -- `--durations`, `--cov`,
    `pyproject.toml`'s `addopts` -- and `.oss.json`'s `test_command` is an
    arbitrary shell command, so it was gated on a substring match that is
    wrong in both directions. The fix makes the paragraph itself
    runner-neutral (it names the property, not one runner's flags), so a Go
    repo gets the same generic recommendation as everyone else rather than
    nothing at all.
    """
    text = scaffold.render("CLAUDE.md", _config(test_command="go test ./..."))
    assert "pytest" not in text, (
        "scaffold wrote pytest-specific wording into a repo whose test_command "
        "plainly names another runner"
    )
    assert "test_measurement_configured" in text, (
        "a set test_command withheld the (now runner-neutral) measurement "
        "advice on the strength of a guess about which runner it is"
    )


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
    stopped rendering it would fail here rather than pass all three. The
    advice is runner-neutral now (#955), so this checks the property named --
    duration and coverage -- rather than pytest's own flag spelling."""
    text = scaffold.render("CLAUDE.md", _config(test_command="python -m pytest tests/"))
    assert "test_measurement_configured" in text
    assert "how long each" in text
    assert "how much" in text


def test_a_command_naming_pytest_only_incidentally_gets_no_pytest_flags():
    """#955: `names_pytest` is a substring match. `'npm test --grep pytest'`
    contains the word `pytest` and used to trip the pytest-specific advice
    into a JavaScript repo's CLAUDE.md -- a fact about somebody else's
    language, written permanently into the file every session there reads
    first. The command itself is still echoed verbatim in its own code
    fence -- that is not the defect -- so this checks the ADVICE paragraph
    specifically: it must never name pytest's own flags on the strength of a
    substring match.
    """
    text = scaffold.render(
        "CLAUDE.md", _config(test_command="npm test --grep pytest")
    )
    assert "--durations" not in text and "--cov" not in text, (
        "a substring match on the word 'pytest' inside an npm invocation wrote "
        "pytest-specific flag advice into a non-Python repo's CLAUDE.md"
    )
    assert "pyproject.toml" not in text


def test_a_wrapped_pytest_invocation_still_gets_the_measurement_advice():
    """#955's mirror: `'make test'` that actually runs pytest underneath used
    to get NOTHING, because `names_pytest` cannot see through a wrapper --
    `doctor` reporting `OK: not applicable` for a check that never looked.
    The fix is runner-neutral, so a wrapped command is not a reason to
    withhold it either.
    """
    text = scaffold.render("CLAUDE.md", _config(test_command="make test"))
    assert "test_measurement_configured" in text, (
        "a set test_command with no pytest-specific wording got no measurement "
        "advice at all -- exactly the withheld half of #955"
    )
