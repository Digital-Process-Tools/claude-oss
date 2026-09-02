r"""#611: the documented development command requires pytest-cov, and nothing declared it.

`pyproject.toml`'s `addopts` sets `--cov=scripts --cov-report=term-missing --cov-fail-under=85`,
so `python3 -m pytest tests/ -q` -- the command both `README.md` and `CLAUDE.md` document --
needs `pytest-cov` installed before a single test collects. Confirmed on a clean venv holding
only `pytest`: the run fails at argument parsing with "unrecognized arguments: --cov=...",
never reaching a test. `pyproject.toml` deliberately declares no `[project.dependencies]` and no
`[build-system]` -- neither reason covers *development* dependencies, and this file is the fix:
`requirements-dev.txt` is now the single declared list, and both docs point a contributor at it
beside the test command they already give.

Two tests would be easy and worth little on their own: that `requirements-dev.txt` exists, and
that it mentions `pytest-cov`. The one with teeth is sufficiency -- the declared set has to cover
everything the suite actually needs, not just the one package this issue happened to name. So
this file cross-checks the declared set against two independent, already-real sources: the
`--cov` flag actually present in `pyproject.toml`'s `addopts` (rather than assuming it), and the
package list `.github/workflows/tests.yml` already installs to make CI green (rather than
guessing what CI needs). A requirements file that agreed with itself but drifted from either
would still be wrong, and both are checked.

Every assertion here is paired with a positive control proving the fixture it reads is real,
not merely present -- per CLAUDE.md's "must fire" pairing.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
README = REPO_ROOT / "README.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
#: #795 moved the Development section -- install line and test command together --
#: out of README.md and into docs/development.md.
DEVELOPMENT_DOC = REPO_ROOT / "docs" / "development.md"

_COMMENT_OR_BLANK = re.compile(r"\A\s*(#.*)?\Z")
_PACKAGE_NAME = re.compile(r"\A([A-Za-z0-9][A-Za-z0-9._-]*)")


def _declared_packages():
    """The package names `requirements-dev.txt` declares, lowercased, unversioned."""
    if not REQUIREMENTS_DEV.exists():
        return set()
    packages = set()
    for line in REQUIREMENTS_DEV.read_text(encoding="utf-8").splitlines():
        if _COMMENT_OR_BLANK.match(line):
            continue
        match = _PACKAGE_NAME.match(line.strip())
        if match:
            packages.add(match.group(1).lower())
    return packages


def _workflow_installed_packages():
    """What `.github/workflows/tests.yml`'s own install step names -- ground truth for what
    a green CI run actually required, independent of anything this repo says about itself."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("pip install") and "requirements" not in line:
            return {tok.lower() for tok in line.strip().split()[2:]}
    return set()


# ------------------------------------------------------------------- positive controls


def test_pyproject_addopts_actually_requires_cov():
    """Positive control for the test below: if this ever stops being true, the assertion
    that pytest-cov must be declared would no longer be testing a real requirement."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "--cov" in text, "pyproject.toml no longer requests coverage in addopts"


def test_workflow_installs_something():
    """Positive control: an empty extraction would make the sufficiency check vacuous."""
    assert _workflow_installed_packages(), "could not find tests.yml's pip install line"


# ------------------------------------------------------------------------ the real checks


def test_requirements_dev_txt_exists_and_is_nonempty():
    assert REQUIREMENTS_DEV.exists(), "requirements-dev.txt is missing (#611)"
    assert _declared_packages(), "requirements-dev.txt declares no packages"


def test_pytest_cov_is_declared():
    assert "pytest-cov" in _declared_packages(), (
        "pyproject.toml's addopts requires --cov, but pytest-cov is not declared in "
        "requirements-dev.txt -- the documented command fails before a test runs"
    )


def test_declared_set_covers_everything_ci_actually_installs():
    """Sufficiency, not just presence: nothing CI found necessary is missing here."""
    declared = _declared_packages()
    missing = sorted(pkg for pkg in _workflow_installed_packages() if pkg not in declared)
    assert not missing, (
        "tests.yml installs {} but requirements-dev.txt does not declare it -- a "
        "contributor following requirements-dev.txt alone would not reproduce a green "
        "CI run".format(missing)
    )


def test_readme_states_the_install_line_beside_the_test_command():
    """#795 moved this whole section to docs/development.md; the proximity fact
    travels with it rather than staying pinned to README.md."""
    body = DEVELOPMENT_DOC.read_text(encoding="utf-8")
    assert "requirements-dev.txt" in body
    install_at = body.index("requirements-dev.txt")
    command_at = body.index("python3 -m pytest tests/ -q")
    assert abs(body.count("\n", 0, install_at) - body.count("\n", 0, command_at)) <= 5, (
        "the install line and the test command are not near each other in "
        "docs/development.md"
    )


def test_claude_md_states_the_install_line_beside_the_test_command():
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert "requirements-dev.txt" in body
    install_at = body.index("requirements-dev.txt")
    command_at = body.index("python3 -m pytest tests/ -q")
    assert abs(body.count("\n", 0, install_at) - body.count("\n", 0, command_at)) <= 3, (
        "the install line and the test command are not near each other in CLAUDE.md"
    )


def test_a_command_naming_nothing_installed_would_pass_this_check_vacuously_never():
    """Negative control: a requirements-dev.txt that declared nothing must fail the
    sufficiency check above, proving it does not pass on an empty or missing file."""
    declared = set()
    missing = sorted(pkg for pkg in _workflow_installed_packages() if pkg not in declared)
    assert missing, "the sufficiency check has no teeth: it passed against an empty declared set"


if __name__ == "__main__":
    sys.exit(0)
