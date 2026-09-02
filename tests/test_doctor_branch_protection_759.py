"""#759: is the default branch actually protected, or is "merge on green" advisory?

Three states, `protected` / `not-protected` / `could-not-tell`, gated on the same
local facts `check_label_vocabulary` already gates on (`gh` on PATH, `origin`/config
naming the repo). The state most likely to be got wrong, per the issue's own
comment: a 404 from `branches/<b>/protection` and a 403 both mean "this call did
not tell you the branch is protected", and only the first is safe to read as
"not protected" -- the second must render as `could-not-tell`, never folded into
`not-protected`, because a permission-limited token cannot be told apart from a
genuinely bare repo by that response alone.

Every "must not fire" case here (a 403 must never render as not-protected; a
protection-endpoint 200 must never be shadowed by an unread rulesets call) is
paired with a "must fire" case in the same fixture, per CLAUDE.md's rule that a
negative assertion needs a positive control.
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


def _config(repo="owner/name", default_branch="main", **overrides):
    config = {"repo": repo, "default_branch": default_branch}
    config.update(overrides)
    return config


def _run_sequence(responses):
    """``responses``: one ``(returncode, stdout, stderr)`` per expected `gh api` call,
    in call order. Recording the actual argv lets a test assert which endpoint was
    (or was not) reached -- e.g. that rulesets is never called when the protection
    endpoint alone already answers ``protected``.
    """
    calls = []
    it = iter(responses)

    def run(cmd, **kwargs):
        calls.append(cmd)
        try:
            rc, out, err = next(it)
        except StopIteration:  # pragma: no cover - a fixture bug, not a product path
            raise AssertionError("more gh calls than the fixture staged: {}".format(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


# --------------------------------------------------------------- gating


def test_could_not_tell_when_gh_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, detail = doctor.branch_protection_state(tmp_path, config=_config())
    assert state == "could-not-tell"
    assert "gh is not on PATH" in detail


def test_could_not_tell_when_default_branch_is_not_configured(tmp_path):
    state, _detail = doctor.branch_protection_state(tmp_path, config=_config(default_branch=None))
    assert state == "could-not-tell"


def test_could_not_tell_when_origin_cannot_be_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_origin_slug", lambda project_dir, run=None: (None, "no readable origin remote here"))
    state, detail = doctor.branch_protection_state(tmp_path, config=None)
    assert state == "could-not-tell"
    assert "origin" in detail


# --------------------------------------------------------------- protected


def test_classic_protection_is_protected_and_never_reads_rulesets(tmp_path):
    """Positive control: a 200 from the protection endpoint settles it. Asserting
    on `run.calls` is the "must not fire" half -- the rulesets endpoint (a second
    network call) must never be reached once the first already answered."""
    run = _run_sequence([(0, '{"required_status_checks": {}}', "")])
    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "protected"
    assert "main" in detail
    assert len(run.calls) == 1


def test_ruleset_covers_it_when_classic_protection_404s(tmp_path):
    """A repo can be covered by a ruleset while the classic endpoint 404s -- the
    issue's own scenario for why both endpoints must be read before concluding
    `not-protected`."""
    run = _run_sequence([
        (1, "", "gh: Branch not protected (HTTP 404)"),
        (0, '[{"id": 1, "name": "main-guard"}]', ""),
    ])
    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "protected"
    assert "ruleset" in detail
    assert len(run.calls) == 2


# --------------------------------------------------------------- not protected


def test_404_on_protection_and_empty_rulesets_is_not_protected(tmp_path):
    run = _run_sequence([
        (1, "", "gh: Branch not protected (HTTP 404)"),
        (0, "[]", ""),
    ])
    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "not-protected"
    assert "main" in detail


# --------------------------------------------------------------- could not tell


def test_403_on_protection_is_could_not_tell_never_not_protected(tmp_path):
    """The state most likely to be got wrong (issue's own words): a 403 must not
    collapse into `not-protected`, because it renders identically to "you lack
    permission" and a repo that IS protected can answer this way too."""
    run = _run_sequence([
        (1, "", "gh: Resource not accessible by integration (HTTP 403)"),
    ])
    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "403" in detail
    # Must-fire pair for the "not protected" positive control above: reaching
    # rulesets after an ambiguous 403 would not rescue the answer, so it is
    # never called.
    assert len(run.calls) == 1


def test_403_on_rulesets_after_a_clean_404_is_still_could_not_tell(tmp_path):
    run = _run_sequence([
        (1, "", "gh: Branch not protected (HTTP 404)"),
        (1, "", "gh: Resource not accessible by integration (HTTP 403)"),
    ])
    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "403" in detail


def test_unclassified_protection_response_is_could_not_tell(tmp_path):
    run = _run_sequence([(1, "", "gh: unexpected error talking to api.github.com")])
    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"


def test_gh_api_call_that_does_not_run_at_all_is_could_not_tell(tmp_path):
    def run(cmd, **kwargs):
        raise OSError("gh binary vanished mid-run")

    state, detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "did not run" in detail


def test_rulesets_response_that_is_not_a_json_list_is_could_not_tell(tmp_path):
    run = _run_sequence([
        (1, "", "gh: Branch not protected (HTTP 404)"),
        (0, '{"unexpected": "shape"}', ""),
    ])
    state, _detail = doctor.branch_protection_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"


# --------------------------------------------------------------- report line


def test_check_branch_protection_reports_protected(tmp_path, capsys):
    run = _run_sequence([(0, "{}", "")])
    doctor.check_branch_protection(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_branch_protection_reports_not_protected_with_a_remedy(tmp_path, capsys):
    run = _run_sequence([
        (1, "", "gh: Branch not protected (HTTP 404)"),
        (0, "[]", ""),
    ])
    doctor.check_branch_protection(tmp_path, config=_config(repo="owner/name"), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "github.com/owner/name/settings/branches" in out


def test_check_branch_protection_reports_could_not_tell_distinctly(tmp_path, capsys):
    """Negative control paired with the two tests above: neither OK nor the
    not-protected WARN wording appears when the answer is ambiguous."""
    run = _run_sequence([(1, "", "gh: Resource not accessible by integration (HTTP 403)")])
    doctor.check_branch_protection(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not" in out
    assert "not protected" not in out
