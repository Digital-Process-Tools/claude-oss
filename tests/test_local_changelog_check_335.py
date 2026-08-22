"""#335: a lane is required to write a changelog fragment and given no way to
check one, because the checker is a CI leg (`assemble_changelog.py --check`)
that `test_command` (`pytest`) never runs. An agent that ran the full suite
green three times had checked everything it was told to check and had not
checked the fragment at all -- and the failure that surfaced it, measured on
this repository, was a fragment that names its issue only in its filename:
the fold consumes the filename, so nothing carries the number into
`CHANGELOG.md`.

`agents/developer.md` now names the exact local invocation. This file checks
two things: that the brief actually names it (so the fix is not only in this
test's docstring), and that the named invocation genuinely catches the #274
shape -- refuses a fragment naming its issue only in the filename, paired
with a control that accepts the same fragment once the body names it too, so
a checker that refused everything could not pass this file.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"

OK, SKIPPED, REFUSED = 0, 1, 2


def _vendor(tmp_path, script_rel_dir="scripts"):
    """Copy the real script to a synthetic repo root with its own `.git`
    marker and a `changelog.d/`, mirroring tests/test_changelog_root_default.py
    so `--check` resolves against *this* fixture, not the real repo."""
    root = tmp_path / "vendor"
    script_dir = root / script_rel_dir
    script_dir.mkdir(parents=True)
    script_path = script_dir / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    (root / ".git").mkdir()
    (root / "changelog.d").mkdir()
    return root, script_path


def _check(script_path, cwd):
    return subprocess.run(
        [sys.executable, str(script_path), "--check"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_developer_md_names_the_local_check():
    """The brief has to name the exact command the CI leg runs, or an agent
    reading it still has no way to check a fragment before pushing."""
    text = DEVELOPER_MD.read_text(encoding="utf-8")
    assert "assemble_changelog.py" in text, (
        "agents/developer.md never names the changelog checker -- the fragment "
        "requirement has no locally-runnable command"
    )
    assert "--check" in text, (
        "agents/developer.md names the assembler but not the read-only --check "
        "mode -- pointing at the script alone risks the fold, which writes"
    )


def test_local_check_refuses_a_fragment_naming_its_issue_only_in_the_filename(tmp_path):
    """The #274 shape, reproduced directly against the command the brief now
    names: a fragment whose filename carries the issue number and whose body
    never mentions it. The fold would consume the filename and ship nothing."""
    root, script_path = _vendor(tmp_path)
    (root / "changelog.d" / "274.fixed.md").write_text(
        "- Fixed a thing that was broken.\n", encoding="utf-8"
    )
    result = _check(script_path, root)
    assert result.returncode == REFUSED, (result.stdout, result.stderr)
    assert "#274" in result.stdout, result.stdout


def test_local_check_passes_the_same_fragment_once_the_body_names_the_issue(tmp_path):
    """Control for the assertion above: the identical fragment, differing only
    in that the body now names its own issue, must pass -- otherwise a
    checker that refuses everything would satisfy the refusal test too."""
    root, script_path = _vendor(tmp_path)
    (root / "changelog.d" / "274.fixed.md").write_text(
        "- Fixed a thing that was broken (#274).\n", encoding="utf-8"
    )
    result = _check(script_path, root)
    assert result.returncode == OK, (result.stdout, result.stderr)
