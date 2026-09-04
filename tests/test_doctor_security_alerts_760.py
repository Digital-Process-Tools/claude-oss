"""#760: the loop reads issues and pull requests and never the security tab, so
an open High finding is invisible to every tick. This is the first, narrower
half of the two the issue asks not to be bundled: a doctor line per scanner
(code scanning, Dependabot alerts, secret scanning) reporting CONFIGURATION
state only -- never a count, never findings text. The board-read half (adding
a security-tab read to /oss:tick step 2, or redefining "nothing left") is
explicitly out of scope for this change.

Four states per scanner, per the issue's own measured table:

* `[]` (HTTP 200) -- the scanner ran. A pass, regardless of what it found --
  this check never reports counts or findings text, so a 200 with open
  findings and a 200 with none render identically here, by design.
* HTTP 404 "no analysis found" -- nothing has ever scanned this repo. Renders
  as an empty security tab, which reads exactly like a clean one; this is the
  plugin's own defect class verbatim.
* HTTP 404 "... is disabled ..." -- a setting, possibly deliberate. Not a
  finding, and not a pass either.
* HTTP 403 -- the token cannot see. Never folded into a count or into
  never-scanned/disabled.

Every "must not fire" case here is paired with a "must fire" case in the same
fixture, per CLAUDE.md's rule that a negative assertion needs a positive
control: a 403 must never render as `never-scanned` or `disabled`, and a 200
must never be shadowed by the disabled-body sniff that only applies to a 404.
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


def test_could_not_tell_when_gh_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, detail = doctor.security_alert_state(tmp_path, "code-scanning", config=_config())
    assert state == "could-not-tell"
    assert "gh is not on PATH" in detail


def test_could_not_tell_when_origin_cannot_be_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_origin_slug", lambda project_dir, run=None: (None, "no readable origin remote here"))
    state, detail = doctor.security_alert_state(tmp_path, "code-scanning", config=None)
    assert state == "could-not-tell"
    assert "origin" in detail


def test_unknown_scanner_name_raises():
    with pytest.raises(ValueError):
        doctor.security_alert_state(Path("."), "not-a-real-scanner", config=_config())


# --------------------------------------------------------------- configured (pass)


@pytest.mark.parametrize("scanner", ["code-scanning", "dependabot", "secret-scanning"])
def test_200_is_configured_for_every_scanner(tmp_path, scanner):
    """Positive control for the never-scanned/disabled negative below: a clean
    200 -- with or without findings inside it -- is `configured`, and this
    check never reads the body for counts."""
    run = _run_once(0, "[]", "")
    state, detail = doctor.security_alert_state(tmp_path, scanner, config=_config(), run=run)
    assert state == "configured"
    assert scanner in detail


def test_200_with_actual_findings_in_the_body_is_still_just_configured(tmp_path):
    """Must-fire pair for the no-counts rule: a non-empty findings array must
    not change the state or leak a count into the detail string."""
    run = _run_once(0, '[{"number": 1, "rule": {"severity": "error"}}]', "")
    state, detail = doctor.security_alert_state(tmp_path, "code-scanning", config=_config(), run=run)
    assert state == "configured"
    assert "1" not in detail.replace("code-scanning", "").replace("owner/name", "")


# --------------------------------------------------------------- never-scanned


def test_404_no_analysis_found_is_never_scanned(tmp_path):
    run = _run_once(1, '{"message": "no analysis found"}', "gh: no analysis found (HTTP 404)")
    state, detail = doctor.security_alert_state(tmp_path, "code-scanning", config=_config(), run=run)
    assert state == "never-scanned"
    assert "404" in detail


# --------------------------------------------------------------- disabled


def test_404_secret_scanning_disabled_body_is_disabled_not_never_scanned(tmp_path):
    """Must-fire pair for the test above: the same HTTP status, a different body
    message, must land on the other side of the never-scanned/disabled split --
    this is the distinction the issue itself calls out as the one most likely to
    get flattened."""
    run = _run_once(
        1,
        '{"message": "Secret scanning is disabled on this repository."}',
        "gh: Secret scanning is disabled on this repository. (HTTP 404)",
    )
    state, detail = doctor.security_alert_state(tmp_path, "secret-scanning", config=_config(), run=run)
    assert state == "disabled"


def test_404_dependabot_disabled_body_is_disabled(tmp_path):
    run = _run_once(
        1,
        '{"message": "Dependabot alerts are disabled for this repository."}',
        "gh: Dependabot alerts are disabled for this repository. (HTTP 404)",
    )
    state, detail = doctor.security_alert_state(tmp_path, "dependabot", config=_config(), run=run)
    assert state == "disabled"


def test_404_body_that_is_not_json_falls_back_to_never_scanned(tmp_path):
    """A 404 whose body cannot be read for a message must not silently become
    `disabled` -- that would over-claim a deliberate setting from nothing."""
    run = _run_once(1, "not json at all", "gh: something went wrong (HTTP 404)")
    state, _detail = doctor.security_alert_state(tmp_path, "code-scanning", config=_config(), run=run)
    assert state == "never-scanned"


# --------------------------------------------------------------- could not tell


def test_403_is_could_not_tell_never_never_scanned_or_disabled(tmp_path):
    """The state most likely to be got wrong, per the issue's own words: a 403
    must never render as a count (0 findings) and must never be folded into
    never-scanned or disabled -- the token cannot see, full stop."""
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    state, detail = doctor.security_alert_state(tmp_path, "dependabot", config=_config(), run=run)
    assert state == "could-not-tell"
    assert "403" in detail
    assert state != "never-scanned"
    assert state != "disabled"


def test_unclassified_response_is_could_not_tell(tmp_path):
    run = _run_once(1, "", "gh: unexpected error talking to api.github.com")
    state, _detail = doctor.security_alert_state(tmp_path, "secret-scanning", config=_config(), run=run)
    assert state == "could-not-tell"


def test_gh_api_call_that_does_not_run_at_all_is_could_not_tell(tmp_path):
    def run(cmd, **kwargs):
        raise OSError("gh binary vanished mid-run")

    state, detail = doctor.security_alert_state(tmp_path, "code-scanning", config=_config(), run=run)
    assert state == "could-not-tell"
    assert "did not run" in detail


# ----------------------------------------------------- undecodable stdout (#1019)


def _run_once_bytes(rc, out, err):
    """`_run_once` above hands `_gh_api` a `str`. A real `subprocess.run` call
    without `universal_newlines=True`/`text=True` (what `_gh_api` now uses)
    hands back `bytes` instead -- this is what makes the fixture below
    exercise the real decode path rather than one `_run_once`'s string
    shortcut skips entirely."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def test_stdout_that_cannot_be_decoded_does_not_abort_the_check(tmp_path):
    """#1019: `_gh_api` used to call `run(...)` with `universal_newlines=True`
    and no `errors=`, which decodes under `errors="strict"` with the
    runner's own locale codec -- a byte that codec cannot represent raises
    `UnicodeDecodeError` (a `ValueError`, not an `OSError` or a
    `subprocess.SubprocessError`), escaping the surrounding `except` and
    aborting the whole `doctor.py` run before its `print("VERDICT: ...")`
    line, breaking the "exit 0 always" contract every check here states.
    `\xff\xfe` is not valid UTF-8 and not valid in most other locale
    codecs either -- the check must still return a state, never raise."""
    run = _run_once_bytes(1, b"gh: something \xff\xfe went wrong (HTTP 404)", b"")
    state, detail = doctor.security_alert_state(
        tmp_path, "code-scanning", config=_config(), run=run
    )
    assert isinstance(state, str)
    assert isinstance(detail, str)


def test_ordinary_bytes_stdout_still_decodes_and_classifies_correctly(tmp_path):
    """Positive control for the case above: a real, cleanly-decodable byte
    response (what `subprocess.run` actually hands back without
    `text=True`) is still read correctly and classified as `configured` --
    the fix is a decode that tolerates a bad byte, not one that swallows
    every response into `could-not-tell`."""
    run = _run_once_bytes(0, b"[]", b"")
    state, _detail = doctor.security_alert_state(
        tmp_path, "code-scanning", config=_config(), run=run
    )
    assert state == "configured"


# --------------------------------------------------------------- report lines


def test_check_code_scanning_alerts_reports_ok_when_configured(tmp_path, capsys):
    run = _run_once(0, "[]", "")
    doctor.check_code_scanning_alerts(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_dependabot_alerts_reports_warn_with_remedy_when_never_scanned(tmp_path, capsys):
    run = _run_once(1, '{"message": "no analysis found"}', "gh: no analysis found (HTTP 404)")
    doctor.check_dependabot_alerts(tmp_path, config=_config(repo="owner/name"), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "github.com/owner/name/settings/security_analysis" in out


def test_check_secret_scanning_alerts_reports_warn_when_disabled(tmp_path, capsys):
    run = _run_once(
        1,
        '{"message": "Secret scanning is disabled on this repository."}',
        "gh: Secret scanning is disabled on this repository. (HTTP 404)",
    )
    doctor.check_secret_scanning_alerts(tmp_path, config=_config(repo="owner/name"), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"


def test_remedy_link_uses_the_origin_fallback_slug_not_only_config(tmp_path, monkeypatch, capsys):
    """Review finding: `_report_security_alert_check` used to re-derive the slug
    from `config` alone when building the remedy URL, so a slug resolved via
    the `origin` fallback (config carries no `repo` key) silently dropped the
    settings-page link even though `security_alert_state` itself had already
    resolved the correct slug and named it in `detail`."""
    monkeypatch.setattr(
        doctor, "_origin_slug", lambda project_dir, run=None: ("owner/from-origin", None)
    )
    run = _run_once(1, '{"message": "no analysis found"}', "gh: no analysis found (HTTP 404)")
    doctor.check_code_scanning_alerts(tmp_path, config=None, run=run)
    out = capsys.readouterr().out
    assert "owner/from-origin" in out
    assert "github.com/owner/from-origin/settings/security_analysis" in out


def test_check_reports_could_not_tell_distinctly_never_as_ok_or_a_count(tmp_path, capsys):
    """Negative control paired with the OK test above: an ambiguous 403 must
    never render with the OK-shaped wording, and must never claim a count."""
    run = _run_once(1, "", "gh: Resource not accessible by integration (HTTP 403)")
    doctor.check_code_scanning_alerts(tmp_path, config=_config(), run=run)
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not tell" in out
    assert not out.startswith("OK ")
