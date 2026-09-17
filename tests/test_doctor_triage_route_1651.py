"""#1651: nothing reported that a label-coverage triage backlog was waiting with
no triage_route_threshold configured -- an unlabelled issue could pile up
indefinitely with no doctor line naming it. Mirrors
tests/test_doctor_trap_queue_1359.py for the curate route, one population over.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_triage_route as mod  # noqa: E402
import statusline  # noqa: E402


def _write_cache(monkeypatch, tmp_path, document):
    """Point statusline.cache_path at a scratch file and write ``document`` there
    (or write nothing at all when ``document`` is None), so the check reads a
    cache this test controls rather than this machine's real one."""
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(statusline, "cache_path", lambda repo: cache_file)
    if document is not None:
        import json

        cache_file.write_text(json.dumps(document), encoding="utf-8")


def test_a_waiting_backlog_with_no_triage_route_warns(monkeypatch, tmp_path):
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, {"issues_no_priority": 2, "issues_no_lane": 1})
    mod.check_triage_route(str(tmp_path), config={"repo": "example/example"})
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", (state, message)
    assert "triage_route_threshold" in message, message
    assert "2 issue(s) with no priority-* label" in message, message
    assert "1 issue(s) with no lane-* label" in message, message


def test_a_waiting_backlog_with_triage_route_configured_notices_not_warns(
    monkeypatch, tmp_path
):
    """Positive control for the assertion above: the identical fixture, plus a
    configured triage_route_threshold -- must NOTICE, never the WARN a genuinely
    unconfigured reading gets."""
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, {"issues_no_priority": 2, "issues_no_lane": 1})
    mod.check_triage_route(
        str(tmp_path),
        config={"repo": "example/example", "triage_route_threshold": 5},
    )
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "NOTICE", (state, message)
    assert "triage_route_threshold" not in message, message


def test_no_unlabelled_issues_reports_ok(monkeypatch, tmp_path):
    """Positive control: a board with both counts at a real, measured zero must
    report OK, never a phantom WARN/NOTICE for nothing waiting."""
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, {"issues_no_priority": 0, "issues_no_lane": 0})
    mod.check_triage_route(str(tmp_path), config={"repo": "example/example"})
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "OK", (state, message)
    assert "none waiting" in message, message


def test_no_cache_at_all_is_could_not_read_not_zero(monkeypatch, tmp_path):
    """A repo whose board was never refreshed must not render as a repo with no
    unlabelled issues -- the third-state rule this module exists to keep."""
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, None)
    mod.check_triage_route(str(tmp_path), config={"repo": "example/example"})
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", (state, message)
    assert "could not be read" in message, message
    assert "UNKNOWN, not zero" in message, message


def test_no_repo_configured_is_could_not_read(monkeypatch, tmp_path):
    doctor.FINDINGS.clear()
    mod.check_triage_route(str(tmp_path), config={})
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", (state, message)
    assert "could not be read" in message, message


def test_config_none_does_not_crash_and_is_not_read_as_configured(
    monkeypatch, tmp_path
):
    """config=None must neither crash on .get nor be read as "configured".
    Unlike check_trap_queue, this check needs config["repo"] to even locate a
    cache, so config=None also means no repo -- the honest answer is
    "could not be read", never a silent "nothing waiting"."""
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, {"issues_no_priority": 2, "issues_no_lane": 1})
    mod.check_triage_route(str(tmp_path))
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", (state, message)
    assert "could not be read" in message, message


def test_config_missing_threshold_but_repo_present_warns_naming_the_key(
    monkeypatch, tmp_path
):
    """Positive control for the assertion above, and the same shape
    check_trap_queue's own config=None test exercises: a real repo, a real
    waiting backlog, and no triage_route_threshold -- must WARN, naming the
    missing key, never silently pass as configured."""
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, {"issues_no_priority": 2, "issues_no_lane": 1})
    mod.check_triage_route(str(tmp_path), config={"repo": "example/example"})
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", (state, message)
    assert "triage_route_threshold" in message, message


def test_both_axes_unmeasured_in_an_otherwise_readable_cache_is_could_not_read(
    monkeypatch, tmp_path
):
    """A cache file that exists and reads cleanly, but never populated either
    count (an old cache from before this field existed, or a repo declaring no
    priority-*/lane-* spellings at all) is UNKNOWN, not a real zero."""
    doctor.FINDINGS.clear()
    _write_cache(monkeypatch, tmp_path, {"prs": 3})
    mod.check_triage_route(str(tmp_path), config={"repo": "example/example"})
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", (state, message)
    assert "could not be read" in message, message
