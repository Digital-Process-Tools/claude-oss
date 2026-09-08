"""#1229: `doctor.py` reports `scripts/lane_pattern_coverage.py`'s own three
states -- `ok` / `finding` / `not-configured` -- through `report()`, choosing
the doctor state each one earns per `.claude/jit-context/paths/00-manual/
doctor-check-contract.md`: `not-configured` is structurally unable to ever
answer for a repo that never declared `lane_patterns`, so it is `NOTICE`, not
`WARN` -- there is nothing to clear. `finding` (a dead pattern, a refused
pattern, or two lanes overlapping) is `WARN`, and every remedy names an edit
to `.oss.json` a session can make directly -- runnable, not only clickable,
per that same contract.

Every "must not fire" case (config is None; a clean, disjoint set of
patterns) is paired with a "must fire" case in the same fixture.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_lane_patterns as dclp  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _touch(repo, *rels):
    for rel in rels:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def _states():
    return [state for state, _ in doctor.FINDINGS]


def test_config_none_is_unmeasured(tmp_path):
    dclp.check_lane_patterns(tmp_path, None)
    assert _states() == ["WARN"]
    assert "lane patterns" in doctor.FINDINGS[0][1]


def test_not_declared_is_notice_not_warn_the_must_not_fire_control(tmp_path):
    config = {"labels": {}}
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["NOTICE"]


def test_disjoint_clean_lanes_are_ok(tmp_path):
    _touch(tmp_path, "a/one.py", "b/two.py")
    config = {
        "labels": {"lane_patterns": {"lane-a": ["a/one.py"], "lane-b": ["b/two.py"]}}
    }
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["OK"]


def test_overlap_is_warn_the_must_fire_case(tmp_path):
    _touch(tmp_path, "shared.py")
    config = {
        "labels": {"lane_patterns": {"lane-a": ["shared.py"], "lane-b": ["shared.py"]}}
    }
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["WARN"]
    message = doctor.FINDINGS[0][1]
    assert "shared.py" in message
    assert ".oss.json" in message


def test_dead_pattern_is_warn(tmp_path):
    config = {"labels": {"lane_patterns": {"lane-a": ["scripts/gone_*.py"]}}}
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["WARN"]
    assert "scripts/gone_*.py" in doctor.FINDINGS[0][1]


def test_uncovered_count_is_surfaced_not_computed_and_discarded(tmp_path):
    """A reviewer finding on #1229's own self-review: `lane_pattern_report`
    computes `uncovered_count` with a real filesystem walk, and the first
    version of this module read every OTHER field off the result but never
    this one -- a full-tree walk performed on every doctor invocation purely
    to compute a number nothing ever printed."""
    _touch(tmp_path, "scripts/covered.py", "scripts/leftover.py")
    config = {"labels": {"lane_patterns": {"lane-a": ["scripts/covered.py"]}}}
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["OK"]
    assert "1" in doctor.FINDINGS[0][1]


def test_uncovered_count_problem_reports_could_not_count_not_flat_ok(
    tmp_path, monkeypatch
):
    """#1252: a failed walk inside `lane_pattern_coverage._uncovered_count`
    used to be discarded and rendered identically to a clean read with
    nothing uncovered -- the flat "every declared pattern resolves..." OK
    line, no coverage clause at all. The must-fire case: a failed walk must
    produce a distinguishable "could not count" clause instead."""
    _touch(tmp_path, "scripts/covered.py")
    config = {"labels": {"lane_patterns": {"lane-a": ["scripts/covered.py"]}}}

    import lane_pattern_coverage

    def _boom(repo):
        return [], "PermissionError: [Errno 13] boom"

    monkeypatch.setattr(lane_pattern_coverage, "_walk_all_files", _boom)
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["OK"]
    message = doctor.FINDINGS[0][1]
    assert "could not" in message.lower()
    assert "boom" in message


def test_non_dict_lane_patterns_is_warn_not_a_crash(tmp_path):
    config = {"labels": {"lane_patterns": ["not", "a", "dict"]}}
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["WARN"]


def test_non_list_per_lane_value_is_warn_not_a_crash(tmp_path):
    config = {"labels": {"lane_patterns": {"lane-a": "abc"}}}
    dclp.check_lane_patterns(tmp_path, config)
    assert _states() == ["WARN"]
    assert "lane-a" in doctor.FINDINGS[0][1]
