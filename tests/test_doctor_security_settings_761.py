"""#761: the four cheap, non-language-dependent settings checks --
secret scanning, secret-scanning push protection, the "Dependabot alerts"
(vulnerability-alerts) toggle, and automated security fixes.

Every "must not fire" case (a 403 must never render as `disabled`; an absent
`security_and_analysis` object must never be read as `disabled` either) is
paired with a "must fire" case in the same fixture, per CLAUDE.md's rule that
a negative assertion needs a positive control.
"""

import json
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


def _config(repo="owner/name", **overrides):
    config = {"repo": repo}
    config.update(overrides)
    return config


def _run_once(rc, out, err):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


# --------------------------------------------------------------- gating


def test_secret_scanning_could_not_tell_when_gh_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, detail = doctor.secret_scanning_state(tmp_path, config=_config())
    assert state == "could-not-tell"
    assert "gh is not on PATH" in detail


def test_vulnerability_alerts_could_not_tell_when_origin_cannot_be_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_origin_slug", lambda project_dir, run=None: (None, "no readable origin remote here"))
    state, detail = doctor.vulnerability_alerts_state(tmp_path, config=None)
    assert state == "could-not-tell"
    assert "origin" in detail


# ------------------------------------------- secret_scanning / push protection


def _sec_analysis_body(secret_scanning=None, push_protection=None):
    body = {}
    if secret_scanning is not None:
        body["secret_scanning"] = {"status": secret_scanning}
    if push_protection is not None:
        body["secret_scanning_push_protection"] = {"status": push_protection}
    return json.dumps({"security_and_analysis": body})


def test_secret_scanning_enabled(tmp_path):
    run = _run_once(0, _sec_analysis_body(secret_scanning="enabled"), "")
    state, detail = doctor.secret_scanning_state(tmp_path, config=_config(), run=run)
    assert state == "enabled"
    assert "secret_scanning" in detail


def test_secret_scanning_disabled(tmp_path):
    """Must-fire pair for the enabled case above."""
    run = _run_once(0, _sec_analysis_body(secret_scanning="disabled"), "")
    state, _detail = doctor.secret_scanning_state(tmp_path, config=_config(), run=run)
    assert state == "disabled"


def test_push_protection_enabled_independent_of_secret_scanning_field(tmp_path):
    run = _run_once(0, _sec_analysis_body(secret_scanning="disabled", push_protection="enabled"), "")
    state, _detail = doctor.secret_scanning_push_protection_state(tmp_path, config=_config(), run=run)
    assert state == "enabled"


def test_missing_security_and_analysis_object_is_could_not_tell_not_disabled(tmp_path):
    """Negative control: GitHub omits the whole object for a non-admin token.
    That must never render as `disabled` -- the two are indistinguishable in
    the JSON, and only `could-not-tell` is the claim this check can make."""
    run = _run_once(0, json.dumps({"name": "repo", "private": False}), "")
    state, detail = doctor.secret_scanning_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "admin" in detail


def test_secret_scanning_403_is_could_not_tell_never_disabled(tmp_path):
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    state, detail = doctor.secret_scanning_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert state != "disabled"
    assert "403" in detail


# --------------------------------------------------------- automated fixes


def test_automated_security_fixes_enabled(tmp_path):
    run = _run_once(0, json.dumps({"enabled": True, "paused": False}), "")
    state, detail = doctor.automated_security_fixes_state(tmp_path, config=_config(), run=run)
    assert state == "enabled"
    assert "enabled" in detail


def test_automated_security_fixes_disabled_via_body(tmp_path):
    """Must-fire pair: a clean 200 body carrying enabled=False is `disabled`,
    not a parse failure."""
    run = _run_once(0, json.dumps({"enabled": False, "paused": False}), "")
    state, _detail = doctor.automated_security_fixes_state(tmp_path, config=_config(), run=run)
    assert state == "disabled"


def test_automated_security_fixes_404_is_disabled(tmp_path):
    run = _run_once(1, "", "gh: Not Found (HTTP 404)")
    state, _detail = doctor.automated_security_fixes_state(tmp_path, config=_config(), run=run)
    assert state == "disabled"


def test_automated_security_fixes_403_is_could_not_tell(tmp_path):
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    state, detail = doctor.automated_security_fixes_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert "403" in detail


# ------------------------------------------------------- vulnerability alerts


def test_vulnerability_alerts_enabled_on_204(tmp_path):
    """The vulnerability-alerts endpoint returns no body at all on success --
    a 204 renders here as `rc == 0` with empty stdout, same as `gh api`
    reports any other 2xx-with-no-body call."""
    run = _run_once(0, "", "")
    state, _detail = doctor.vulnerability_alerts_state(tmp_path, config=_config(), run=run)
    assert state == "enabled"


def test_vulnerability_alerts_disabled_on_404(tmp_path):
    """Must-fire pair for the enabled case above: the same endpoint's 404
    (no message body to sniff at all) is `disabled`."""
    run = _run_once(1, "", "gh: Not Found (HTTP 404)")
    state, _detail = doctor.vulnerability_alerts_state(tmp_path, config=_config(), run=run)
    assert state == "disabled"


def test_vulnerability_alerts_403_is_could_not_tell_never_disabled(tmp_path):
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    state, detail = doctor.vulnerability_alerts_state(tmp_path, config=_config(), run=run)
    assert state == "could-not-tell"
    assert state != "disabled"
    assert "403" in detail


# --------------------------------------------------------------- report lines


def test_check_secret_scanning_reports_ok_when_enabled(tmp_path, capsys):
    run = _run_once(0, _sec_analysis_body(secret_scanning="enabled"), "")
    doctor.check_secret_scanning(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_automated_security_fixes_reports_warn_with_remedy_when_disabled(tmp_path, capsys):
    run = _run_once(1, "", "gh: Not Found (HTTP 404)")
    doctor.check_automated_security_fixes(tmp_path, config=_config(repo="owner/name"), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "github.com/owner/name/settings/security_analysis" in out


def test_check_vulnerability_alerts_reports_could_not_tell_distinctly(tmp_path, capsys):
    """Negative control: an ambiguous 403 must never render with the OK-shaped
    wording and must never claim a count."""
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    doctor.check_vulnerability_alerts(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not tell" in out
    assert not out.startswith("OK ")
