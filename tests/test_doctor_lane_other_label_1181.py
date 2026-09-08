"""#1181: `labels.lane_other` gets the same three-state check `labels.filed_by_loop`
already has (#990) -- declared/not-declared/could-not-tell -- plus the fourth state
`filed_by_loop` does not need: whether the declared spelling actually exists as a
label on the forge. Nothing checked that before; a declared spelling with no matching
forge label made `select_issues.py` find zero `lane-other` candidates forever, which
reads exactly like a lane that fills correctly and simply has none today.

`declared-and-absent` and `could-not-tell` must never render alike -- an unreadable
forge is not evidence the label is missing, the same defect class `label_vocabulary_
state`'s own docstring exists to avoid.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _fake_run(stdout="", returncode=0):
    class _Result:
        pass

    def run(cmd, **kwargs):
        result = _Result()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = ""
        return result

    return run


def _config(labels):
    config = {"repo": "owner/name"}
    if labels is not None:
        config["labels"] = labels
    return config


def test_not_declared_warns_with_an_executable_remedy():
    """#1310: `not-declared` used to be reported as a legitimate `OK`, the same
    posture as `filed_by_loop`'s own optional key -- but a repo can never reach
    `0nl` without a fallback lane, so leaving it unset forever is not neutral.
    The remedy has to be runnable, not only clickable (doctor-check-contract).
    """
    doctor.FINDINGS.clear()
    doctor.check_lane_other_label(
        "/tmp", _config({"lanes": ["lane-a"]}), run=_fake_run()
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not-declared" in message
    assert "gh label create" in message
    assert "lane_other" in message
    doctor.FINDINGS.clear()


def test_null_value_is_also_not_declared_and_also_warns():
    doctor.FINDINGS.clear()
    doctor.check_lane_other_label(
        "/tmp", _config({"lanes": ["lane-a"], "lane_other": None}), run=_fake_run()
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not-declared" in message
    assert "gh label create" in message
    doctor.FINDINGS.clear()


def test_declared_and_present_on_the_forge_the_must_fire_case():
    doctor.FINDINGS.clear()
    rows = '[{"name": "lane-other"}, {"name": "lane-a"}]'
    doctor.check_lane_other_label(
        "/tmp",
        _config({"lanes": ["lane-a"], "lane_other": "lane-other"}),
        run=_fake_run(stdout=rows),
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "lane-other" in message and "exists" in message
    doctor.FINDINGS.clear()


def test_declared_and_absent_the_must_fire_case():
    doctor.FINDINGS.clear()
    rows = '[{"name": "lane-a"}]'
    doctor.check_lane_other_label(
        "/tmp",
        _config({"lanes": ["lane-a"], "lane_other": "lane-other"}),
        run=_fake_run(stdout=rows),
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "declared but no such label exists" in message
    doctor.FINDINGS.clear()


def test_could_not_tell_never_reads_the_same_as_declared_and_absent():
    """The positive control for the pair above: a forge that could not be
    read must never render the same message as a confirmed absence."""
    doctor.FINDINGS.clear()
    doctor.check_lane_other_label(
        "/tmp",
        _config({"lanes": ["lane-a"], "lane_other": "lane-other"}),
        run=_fake_run(returncode=1),
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could not tell" in message
    assert "declared but no such label exists" not in message
    doctor.FINDINGS.clear()


def test_malformed_value_is_could_not_tell():
    doctor.FINDINGS.clear()
    doctor.check_lane_other_label(
        "/tmp", _config({"lanes": ["lane-a"], "lane_other": True}), run=_fake_run()
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could not tell" in message
    doctor.FINDINGS.clear()


def test_lane_other_label_state_four_states_directly():
    assert doctor.lane_other_label_state(
        "/tmp", config=_config({"lanes": []}), run=_fake_run()
    ) == ("not-declared", None)  # the STATE itself is unchanged by #1310 -- only
    # `check_lane_other_label`'s rendering of it moved from OK to WARN

    rows = '[{"name": "lane-other"}]'
    state, payload = doctor.lane_other_label_state(
        "/tmp",
        config=_config({"lanes": [], "lane_other": "lane-other"}),
        run=_fake_run(stdout=rows),
    )
    assert state == "declared-and-present"
    assert payload == ("owner/name", "lane-other")

    state, payload = doctor.lane_other_label_state(
        "/tmp",
        config=_config({"lanes": [], "lane_other": "lane-other"}),
        run=_fake_run(stdout="[]"),
    )
    assert state == "declared-and-absent"
    assert payload == ("owner/name", "lane-other")

    state, payload = doctor.lane_other_label_state(
        "/tmp",
        config=_config({"lanes": [], "lane_other": "lane-other"}),
        run=_fake_run(returncode=1),
    )
    assert state == "could-not-tell"
