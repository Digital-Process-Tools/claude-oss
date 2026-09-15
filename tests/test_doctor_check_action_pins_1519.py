"""``check_action_pins`` -- doctor compares the two GitHub Action SHAs pinned
inside `scaffold.CHANGELOG_WORKFLOW` against the live tip of their major tag
(#1519).

The pin lives inside a Python string, not a real workflow file, so
`.github/dependabot.yml`'s `github-actions` watch never sees it drift --
confirmed by reading `.github/dependabot.yml` directly (`directory: /`, real
YAML files only). This is the comparison nothing else in the repo makes.

Positive control included: a fixture where nothing runs (`gh` absent) must
not read the same as a fixture where everything agrees -- both would
otherwise print nothing distinguishable, which is exactly the "absence
produced by the tool" defect class this repository is named after.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import doctor  # noqa: E402
import doctor_check_action_pins  # noqa: E402


WORKFLOW = """
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
"""

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"


def _reset():
    doctor.FINDINGS.clear()


def _finding():
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    return doctor.FINDINGS[0]


class _FakeScaffold:
    CHANGELOG_WORKFLOW = WORKFLOW


@pytest.fixture(autouse=True)
def _restore_scaffold(monkeypatch):
    monkeypatch.setattr(doctor, "scaffold", _FakeScaffold)
    yield


# --------------------------------------------------------------- parsing


def test_pinned_shas_reads_action_and_tag_comment():
    pinned = doctor_check_action_pins._pinned_shas(WORKFLOW)
    assert pinned["actions/checkout"] == (CHECKOUT_SHA, "v7.0.1")
    assert pinned["actions/setup-python"] == (SETUP_PYTHON_SHA, "v7.0.0")


def test_missing_uses_line_is_warn_not_ok():
    _reset()
    monkeypatch_workflow = "no uses lines here at all"

    class _Empty:
        CHANGELOG_WORKFLOW = monkeypatch_workflow

    import doctor as doctor_module

    doctor_module.scaffold = _Empty
    doctor_check_action_pins.check_action_pins()
    state, message = _finding()
    assert state == "WARN"
    assert "could not find" in message


# --------------------------------------------------------------- not-checked


def test_no_scaffold_is_not_checked(monkeypatch):
    _reset()
    monkeypatch.setattr(doctor, "scaffold", None)
    doctor_check_action_pins.check_action_pins()
    state, message = _finding()
    assert state == "WARN"
    assert "scaffold.py" in message


def test_no_gh_binary_is_not_checked(monkeypatch):
    _reset()
    monkeypatch.setattr(
        doctor_check_action_pins.gh_which, "safe_which", lambda name: None
    )
    doctor_check_action_pins.check_action_pins()
    state, message = _finding()
    assert state == "WARN"
    assert "not checked" in message
    assert "gh is not on PATH" in message


def test_live_read_never_answering_is_not_checked_never_ok(monkeypatch):
    _reset()
    monkeypatch.setattr(
        doctor_check_action_pins.gh_which, "safe_which", lambda name: "/usr/bin/gh"
    )
    monkeypatch.setattr(
        doctor_check_action_pins, "_live_commit_sha", lambda gh_bin, action, ref: None
    )
    doctor_check_action_pins.check_action_pins()
    state, message = _finding()
    assert state == "WARN"
    assert "not checked for" in message
    assert "actions/checkout" in message
    assert "actions/setup-python" in message


# --------------------------------------------------------------- the positive control


def test_everything_agreeing_is_ok(monkeypatch):
    """The must-fire half of the pair above: when gh IS on PATH and the live
    read DOES answer and agrees, the check reports OK -- proving the
    not-checked states above are not simply "this check never reports
    anything"."""
    _reset()
    monkeypatch.setattr(
        doctor_check_action_pins.gh_which, "safe_which", lambda name: "/usr/bin/gh"
    )

    def _live(gh_bin, action, ref):
        return {
            "actions/checkout": CHECKOUT_SHA,
            "actions/setup-python": SETUP_PYTHON_SHA,
        }[action]

    monkeypatch.setattr(doctor_check_action_pins, "_live_commit_sha", _live)
    doctor_check_action_pins.check_action_pins()
    state, message = _finding()
    assert state == "OK"
    assert "match the live tip" in message


# --------------------------------------------------------------- drift


def test_one_action_drifted_is_warn_and_names_it(monkeypatch):
    _reset()
    monkeypatch.setattr(
        doctor_check_action_pins.gh_which, "safe_which", lambda name: "/usr/bin/gh"
    )

    def _live(gh_bin, action, ref):
        if action == "actions/checkout":
            return "f" * 40  # drifted
        return SETUP_PYTHON_SHA

    monkeypatch.setattr(doctor_check_action_pins, "_live_commit_sha", _live)
    doctor_check_action_pins.check_action_pins()
    state, message = _finding()
    assert state == "WARN"
    assert "actions/checkout" in message
    assert "drifted" in message
    assert "Dependabot cannot see this" in message
    # The action that agreed is not named as drifted.
    assert "actions/setup-python is pinned" not in message


# --------------------------------------------------------------- gh subprocess


def test_live_commit_sha_returns_none_on_nonzero_exit(monkeypatch):
    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="")

    monkeypatch.setattr(doctor_check_action_pins.subprocess, "run", _fake_run)
    assert (
        doctor_check_action_pins._live_commit_sha(
            "/usr/bin/gh", "actions/checkout", "v7"
        )
        is None
    )


def test_live_commit_sha_returns_none_on_malformed_output(monkeypatch):
    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=0, stdout="not-a-sha\n")

    monkeypatch.setattr(doctor_check_action_pins.subprocess, "run", _fake_run)
    assert (
        doctor_check_action_pins._live_commit_sha(
            "/usr/bin/gh", "actions/checkout", "v7"
        )
        is None
    )


def test_live_commit_sha_returns_sha_on_success(monkeypatch):
    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, returncode=0, stdout=CHECKOUT_SHA + "\n"
        )

    monkeypatch.setattr(doctor_check_action_pins.subprocess, "run", _fake_run)
    assert (
        doctor_check_action_pins._live_commit_sha(
            "/usr/bin/gh", "actions/checkout", "v7"
        )
        == CHECKOUT_SHA
    )


def test_live_commit_sha_never_raises_on_spawn_error(monkeypatch):
    def _fake_run(*args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(doctor_check_action_pins.subprocess, "run", _fake_run)
    assert (
        doctor_check_action_pins._live_commit_sha(
            "/usr/bin/gh", "actions/checkout", "v7"
        )
        is None
    )


# ----------------------------------------------------- wired into doctor.py


def test_doctor_reexports_the_check():
    assert doctor.check_action_pins is doctor_check_action_pins.check_action_pins
