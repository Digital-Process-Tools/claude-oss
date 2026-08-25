"""#478: `/oss:doctor` reports which release-authority mode a repo is in, before a
release rather than at the tag step -- the same reason #421 put the merge-call check
there. All three states (`loop`, `maintainer`, `not-declared`) are legitimate and none is
a WARN; what must never happen is `not-declared` reading as anything other than a stop.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _config(release_block):
    config = {"repo": "o/r"}
    if release_block is not None:
        config["release"] = release_block
    return config


def test_loop_reports_ok_and_names_the_grant():
    doctor.FINDINGS.clear()
    doctor.check_release_authority("/tmp", _config({"authority": "loop"}))
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "loop" in message
    doctor.FINDINGS.clear()


def test_maintainer_reports_ok_and_stops():
    doctor.FINDINGS.clear()
    doctor.check_release_authority("/tmp", _config({"authority": "maintainer"}))
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "maintainer" in message
    assert "stop" in message
    doctor.FINDINGS.clear()


def test_not_declared_reports_ok_and_stops_same_as_maintainer():
    doctor.FINDINGS.clear()
    doctor.check_release_authority("/tmp", _config(None))
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "not-declared" in message
    assert "stop" in message
    doctor.FINDINGS.clear()


def test_missing_config_is_reported_not_silently_skipped():
    doctor.FINDINGS.clear()
    doctor.check_release_authority("/tmp", None)
    state, message = doctor.FINDINGS[-1]
    assert state in ("OK", "WARN")
    assert "release authority" in message
    doctor.FINDINGS.clear()
