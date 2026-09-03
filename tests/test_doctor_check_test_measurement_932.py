"""#932: doctor and scaffold should recommend test-duration + coverage measurement
be configured.

`test_measurement_configured` is a maintainer ATTESTATION in `.oss.json` -- a
boolean nobody derives from the config's own content, following #932's own
citation of this repository's three-state rule. Three states this check
answers, none of them content-checked:

  true, and a pytest-config-shaped file is readable here   -> OK
  absent or false                                          -> WARN (finding)
  true, but no pytest-config-shaped file is readable here  -> WARN (unknown --
                                                               never silently OK)
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import doctor  # noqa: E402
import doctor_check_test_measurement as check  # noqa: E402


def _capture(monkeypatch):
    seen = []
    monkeypatch.setattr(doctor, "report", lambda state, message: seen.append((state, message)))
    return seen


def test_absent_key_is_a_finding(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {})
    assert seen[0][0] == "WARN", seen
    assert "test_measurement_configured" in seen[0][1]
    assert "absent" in seen[0][1]


def test_false_is_a_finding(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_measurement_configured": False})
    assert seen[0][0] == "WARN", seen
    assert "false" in seen[0][1]


def test_true_with_readable_pytest_config_is_ok(tmp_path, monkeypatch):
    lines = [
        "[tool.pytest.ini_options]",
        "addopts = \"--durations=25 --cov\"",
        "",
    ]
    (tmp_path / "pyproject.toml").write_text("\n".join(lines), encoding="utf-8")
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_measurement_configured": True})
    assert seen[0][0] == "OK", seen
    assert "pyproject.toml" in seen[0][1]


def test_true_with_no_readable_pytest_config_is_unknown_not_silently_ok(tmp_path, monkeypatch):
    """The must-fire half: nothing in `tmp_path` looks like a pytest config at
    all, so an attestation of `true` cannot be corroborated even minimally and
    must render as a distinct third state rather than a blind OK."""
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_measurement_configured": True})
    assert seen[0][0] == "WARN", seen
    assert "test_measurement_configured" in seen[0][1]
    assert seen[0][0] != "OK"


def test_config_none_is_unmeasured(monkeypatch):
    seen = []
    monkeypatch.setattr(doctor, "unmeasured", lambda label, reason=doctor.NO_CONFIG: seen.append((label, reason)))
    check.check_test_measurement("/nonexistent", None)
    assert seen, "a None config must report the third state, never silently pass"


def test_doctor_reexports_the_check():
    assert doctor.check_test_measurement is check.check_test_measurement


def test_non_pytest_test_command_is_not_applicable_npm(tmp_path, monkeypatch):
    """#946-adjacent finding from review: a non-Python repo's `test_command` (e.g.
    `npm test`) must never trigger pytest-specific advice -- that bakes in "every
    diagnosed repo uses pytest", the same class of error CLAUDE.md's governing rule
    exists to prevent, one language down."""
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_command": "npm test"})
    assert seen[0][0] == "OK", seen
    assert "pytest" not in seen[0][1].split("not applicable")[-1].lower() or "pytest-shaped" in seen[0][1]
    assert "not applicable" in seen[0][1], seen


def test_non_pytest_test_command_is_not_applicable_go(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_command": "go test ./..."})
    assert seen[0][0] == "OK", seen
    assert "not applicable" in seen[0][1], seen


def test_non_pytest_test_command_is_not_applicable_cargo(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_command": "cargo test"})
    assert seen[0][0] == "OK", seen
    assert "not applicable" in seen[0][1], seen


def test_pytest_test_command_still_fires_finding(tmp_path, monkeypatch):
    """A pytest-shaped `test_command` keeps the existing finding/OK behavior."""
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {"test_command": "python3 -m pytest tests/ -q"})
    assert seen[0][0] == "WARN", seen
    assert "not applicable" not in seen[0][1], seen


def test_unset_test_command_keeps_prior_pytest_assumption(tmp_path, monkeypatch):
    """No `test_command` at all is ambiguous, not evidence against pytest -- keep
    firing the existing pytest-shaped behavior rather than silently skipping."""
    seen = _capture(monkeypatch)
    check.check_test_measurement(str(tmp_path), {})
    assert seen[0][0] == "WARN", seen
    assert "not applicable" not in seen[0][1], seen
