"""#1244: `doctor.py` reports `scripts/lane_coupling.py`'s own three states
(`ok` / `finding` / `not-configured`) through `report()`, choosing the
doctor state each one earns per `.claude/jit-context/paths/00-manual/
doctor-check-contract.md` -- the same wrapping shape #1229's own
`doctor_check_lane_patterns.py` already uses for the closely related check,
one level up.

`not-configured` (this repo has never declared `labels.lane_patterns`) is
`NOTICE`: structurally unable to ever answer, nothing to clear. `finding`
(an UNACKNOWLEDGED span, a malformed lane, or an unreadable test file) is
`WARN`, naming the test files a maintainer can either fix or add to
`.oss.json`'s `labels.lane_coupling_allowlist`. `ok` is `OK`, with the
acknowledged count folded into the message informationally -- the same
`uncovered_count` shape `doctor_check_lane_patterns.py` already uses,
never one line per acknowledged file.

Every "must not fire" case is paired with a "must fire" case in the same
fixture.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_lane_coupling as dclc  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _states():
    return [state for state, _ in doctor.FINDINGS]


def _scaffold_two_lane_repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "beta.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()


def test_config_none_is_unmeasured(tmp_path):
    dclc.check_lane_coupling(tmp_path, None)
    assert _states() == ["WARN"]
    assert "lane coupling" in doctor.FINDINGS[0][1]


def test_lane_patterns_not_declared_is_notice_the_must_not_fire_control(tmp_path):
    config = {"labels": {}}
    dclc.check_lane_coupling(tmp_path, config)
    assert _states() == ["NOTICE"]


def test_single_lane_test_is_ok(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_ok.py").write_text(
        'REF = "scripts/alpha.py"\n', encoding="utf-8"
    )
    config = {
        "labels": {
            "lane_patterns": {
                "lane-a": ["scripts/alpha*.py"],
                "lane-b": ["scripts/beta*.py"],
            }
        }
    }
    dclc.check_lane_coupling(tmp_path, config)
    assert _states() == ["OK"]


def test_unacknowledged_span_is_warn_the_must_fire_case(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_spans.py").write_text(
        'A = "scripts/alpha.py"\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    config = {
        "labels": {
            "lane_patterns": {
                "lane-a": ["scripts/alpha*.py"],
                "lane-b": ["scripts/beta*.py"],
            }
        }
    }
    dclc.check_lane_coupling(tmp_path, config)
    assert _states() == ["WARN"]
    message = doctor.FINDINGS[0][1]
    assert "test_spans.py" in message


def test_allowlisted_span_is_ok_not_warn(tmp_path):
    """The allowlist mechanism itself, exercised through the doctor wrapper:
    an acknowledged span must not gate the verdict."""
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_spans.py").write_text(
        'A = "scripts/alpha.py"\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    config = {
        "labels": {
            "lane_patterns": {
                "lane-a": ["scripts/alpha*.py"],
                "lane-b": ["scripts/beta*.py"],
            },
            "lane_coupling_allowlist": ["tests/test_spans.py"],
        }
    }
    dclc.check_lane_coupling(tmp_path, config)
    assert _states() == ["OK"]
    assert "1" in doctor.FINDINGS[0][1]


def test_real_repo_is_quiet_the_issues_own_verification(
    monkeypatch, lane_coupling_real_repo_report
):
    """The issue's own verification instruction: running doctor should not
    produce ~48 warnings on this repo's own tree.

    Routed through the shared `lane_coupling_real_repo_report` fixture
    (#1318, `tests/conftest.py`): `test_lane_coupling_allowlist_1244.
    py::test_real_repo_is_quiet_once_wired_with_its_own_declared_allowlist`
    walks this same real tree with the identical arguments (this repo's
    own root, `labels.lane_patterns`, `labels.lane_coupling_allowlist`).
    `dclc.lane_coupling.lane_coupling_report` is intercepted here so a
    call carrying those exact arguments answers from the shared cache
    instead of re-walking the tree -- any OTHER call still reaches the
    real, un-memoized function, so `check_lane_coupling`'s own
    state-translation logic below is still exercised against a real,
    freshly-derived-or-cached answer either way, never a stubbed one."""
    import json

    config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    real_report = dclc.lane_coupling.lane_coupling_report

    def _cached_for_the_real_repo(project_dir, lane_patterns, allowlist=None):
        if project_dir == REPO_ROOT:
            return lane_coupling_real_repo_report(
                project_dir, lane_patterns, allowlist=allowlist
            )
        return real_report(project_dir, lane_patterns, allowlist=allowlist)

    monkeypatch.setattr(
        dclc.lane_coupling, "lane_coupling_report", _cached_for_the_real_repo
    )
    dclc.check_lane_coupling(REPO_ROOT, config)
    assert _states() == ["OK"], doctor.FINDINGS
