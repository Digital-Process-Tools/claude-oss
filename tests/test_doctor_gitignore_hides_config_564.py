"""#564: `check_gitignore_hides_config` -- the diagnostic half.

`.gitignore` is a DEFAULTS file: scaffolded once, then the managed repo's forever.
A stale rule in it -- the pre-#34 template naming `.oss.json` instead of
`.oss.local.json` -- can never be corrected by a later `/oss:scaffold` run. This is
the only place that defect can ever become visible again, so it gets its own test
file rather than living only inside `test_scaffold.py`'s template assertions.

Three states, never two: `clear` (OK), `ignored` (FAIL, naming the rule), and
`unknown` -- git could not be asked -- which must render as a WARN naming why,
never as a silent OK. The `unknown` case is the positive control here: without it,
a broken git invocation and a genuinely clean `.gitignore` would both print nothing.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _real_git_repo(tmp_path):
    done = subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {}".format(done.stderr.strip() or done.returncode))


def _states():
    return [state for state, _ in doctor.FINDINGS]


def _messages():
    return [message for _, message in doctor.FINDINGS]


def test_a_gitignore_hiding_oss_json_is_a_failure_naming_the_rule(tmp_path):
    _real_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n.oss.json\n", encoding="utf-8")

    doctor.check_gitignore_hides_config(tmp_path)

    assert "FAIL" in _states(), _messages()
    assert any(".gitignore:2" in m for m in _messages()), _messages()


def test_a_gitignore_that_leaves_oss_json_trackable_is_clean(tmp_path):
    # Positive control for the assertion above, same fixture shape: with nothing
    # ignoring .oss.json the check must say so and must not fail.
    _real_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n.oss.local.json\n", encoding="utf-8")

    doctor.check_gitignore_hides_config(tmp_path)

    assert "FAIL" not in _states(), _messages()
    assert any("not ignored" in m for m in _messages()), _messages()


def test_no_gitignore_at_all_is_also_clean(tmp_path):
    _real_git_repo(tmp_path)

    doctor.check_gitignore_hides_config(tmp_path)

    assert "FAIL" not in _states(), _messages()


def test_a_path_git_cannot_be_asked_about_is_unknown_not_silently_clean(tmp_path, monkeypatch):
    """The third state: could-not-ask must render as a WARN, never as OK.

    Not a git repository at all, so `git check-ignore` exits neither 0 nor 1 --
    it errors, which is exactly the shape `oss_config._ignore_rule` reports as
    ``unknown``.
    """
    (tmp_path / ".gitignore").write_text(".oss.json\n", encoding="utf-8")

    doctor.check_gitignore_hides_config(tmp_path)

    assert "FAIL" not in _states(), _messages()
    assert "WARN" in _states(), _messages()
    assert any("could not ask" in m for m in _messages()), _messages()


def test_oss_config_import_failure_is_reported_not_silently_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "oss_config", None)

    doctor.check_gitignore_hides_config(tmp_path)

    assert _states() == ["WARN"], _messages()
    assert "could not be imported" in _messages()[0]
