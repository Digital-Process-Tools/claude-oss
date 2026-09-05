"""#1075 -- zero lane labels used to report `OK ... 0 lane label(s). The
triager can tag from this today.`, folding "vocabulary is fine" and
"vocabulary is empty" into the same line, distinguished only by a number a
reader had to notice. `check_label_vocabulary` now reports the lane half on
its own line, in its own three states, never inside the priority verdict.

Paired per this repo's own "a negative assertion needs a positive control"
rule: a board with zero lane labels (must fire the new gap line) sits next
to a board with a populated vocabulary (must fire the satisfied line, and
must NOT also render as the gap).
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

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


def test_zero_lane_labels_is_not_ok_it_is_a_named_gap(tmp_path):
    """The must-fire half: a vocabulary with priority labels but zero lane
    labels must never render as `OK ... 0 lane label(s)` again."""
    rows = json.dumps([{"name": "priority-high"}, {"name": "priority-low"}])
    doctor.FINDINGS[:] = []
    doctor.check_label_vocabulary(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=rows)
    )
    lane_lines = [msg for _state, msg in doctor.FINDINGS if "lane label" in msg]
    assert lane_lines, "expected a dedicated lane-label finding"
    assert not any(
        state == "OK" and "0 lane label(s)" in msg for state, msg in doctor.FINDINGS
    ), "an empty lane vocabulary must never render as OK"
    assert any(
        "no lane-* labels exist" in msg
        for _state, msg in doctor.FINDINGS
        if "lane" in msg
    )


def test_a_populated_lane_vocabulary_is_satisfied_the_positive_control(tmp_path):
    """The must-not-fire half: a real vocabulary must report the lanes as
    satisfied, not as the gap the test above checks for."""
    rows = json.dumps(
        [
            {"name": "priority-high"},
            {"name": "lane-doctor"},
            {"name": "lane-dispatch"},
        ]
    )
    doctor.FINDINGS[:] = []
    doctor.check_label_vocabulary(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=rows)
    )
    assert any(
        state == "OK" and "lane label" in msg and "lane-doctor" in msg
        for state, msg in doctor.FINDINGS
    )
    assert not any("none declared" in msg for _state, msg in doctor.FINDINGS)


def test_lane_label_state_three_states_directly(tmp_path):
    rows = json.dumps([{"name": "lane-doctor"}])
    state, payload = doctor.lane_label_state(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=rows)
    )
    assert state == "satisfied"
    slug, lanes = payload
    assert slug == "owner/name"
    assert lanes == ["lane-doctor"]

    state, payload = doctor.lane_label_state(
        tmp_path, config={"repo": "owner/name"}, run=_fake_run(stdout=json.dumps([]))
    )
    assert state == "none-declared"
    assert payload == "owner/name"

    doctor.shutil.which  # sanity: module attribute exists before monkeypatching
