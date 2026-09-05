"""#1064 -- the receipt behind bin/oss-workspace's #764 doctor-route: should the
launcher route this session into /oss:doctor again, or has it already shown this
exact state?

Library half only. `doctor_route_check` decides ARMED/not-armed from this launch's
own verdict + plugin identity against the most recently recorded receipt;
`_last_doctor_route` finds that receipt in the state file's own entry history --
same shape as `_last_plugin_identity` / `_last_wait`, and for the same reason: a
receipt written several launches ago must still be found behind whatever landed
after it.

Three states, not two, mirroring `plugin_identity_check`'s own reasoning: a route
with no receipt at all must not render like a route that compared and found no
change (both would otherwise look "not armed... nothing to report"), so
`no-receipt` and `unchanged` are kept apart even though a caller only cares about
the derived `armed` boolean in practice.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


def test_doctor_route_check_needs_a_current_verdict():
    with pytest.raises(oss_state.StateError):
        oss_state.doctor_route_check("", "0.24.0, content abc", None, None)
    with pytest.raises(oss_state.StateError):
        oss_state.doctor_route_check(None, "0.24.0, content abc", None, None)


def test_doctor_route_check_needs_a_current_plugin_identity():
    with pytest.raises(oss_state.StateError):
        oss_state.doctor_route_check("usable with gaps -- 1 warning(s)", "", None, None)
    with pytest.raises(oss_state.StateError):
        oss_state.doctor_route_check(
            "usable with gaps -- 1 warning(s)", None, None, None
        )


def test_doctor_route_check_arms_with_no_prior_receipt():
    """MUST FIRE: the first launch ever reaching this state has nothing to
    compare against, and that must arm the route rather than read as a
    settled 'unchanged'."""
    record = oss_state.doctor_route_check(
        "usable with gaps -- 1 warning(s)", "0.24.0, content abc", None, None
    )
    assert record["armed"] is True
    assert record["state"] == oss_state.DOCTOR_ROUTE_NO_RECEIPT


def test_doctor_route_check_does_not_arm_when_both_fields_are_unchanged():
    """MUST NOT FIRE: the positive control for the case above -- an identical
    verdict on an identical plugin genuinely must not re-arm."""
    record = oss_state.doctor_route_check(
        "usable with gaps -- 1 warning(s)",
        "0.24.0, content abc",
        "usable with gaps -- 1 warning(s)",
        "0.24.0, content abc",
    )
    assert record["armed"] is False
    assert record["state"] == oss_state.DOCTOR_ROUTE_UNCHANGED


def test_doctor_route_check_arms_when_only_the_verdict_moved():
    record = oss_state.doctor_route_check(
        "not usable -- 1 failure(s)",
        "0.24.0, content abc",
        "usable with gaps -- 1 warning(s)",
        "0.24.0, content abc",
    )
    assert record["armed"] is True
    assert record["state"] == oss_state.DOCTOR_ROUTE_CHANGED


def test_doctor_route_check_arms_when_only_the_plugin_moved():
    """The issue's own reasoning: a plugin update landing on an unchanged
    verdict is exactly as worth a fresh look as a verdict changing on an
    unchanged plugin -- the receipt is a pair, not two independent latches."""
    record = oss_state.doctor_route_check(
        "usable with gaps -- 1 warning(s)",
        "0.25.0, content def",
        "usable with gaps -- 1 warning(s)",
        "0.24.0, content abc",
    )
    assert record["armed"] is True
    assert record["state"] == oss_state.DOCTOR_ROUTE_CHANGED


def test_last_doctor_route_finds_nothing_on_an_empty_history(tmp_path):
    path = tmp_path / "state.json"
    entry, verdict, identity = oss_state._last_doctor_route(path)
    assert entry is None
    assert verdict is None
    assert identity is None


def test_last_doctor_route_reads_the_most_recent_receipt_behind_other_entries(tmp_path):
    """Same shape as `_last_plugin_identity`'s own test: a receipt recorded two
    entries ago must still be found behind an intake entry and a plain
    decision that landed after it."""
    path = tmp_path / "state.json"
    oss_state.append(
        path,
        "2026-01-01T00:00:00Z",
        "doctor-route: usable with gaps",
        detail={
            "doctor_route_verdict": "usable with gaps -- 1 warning(s)",
            "doctor_route_plugin_identity": "0.24.0, content abc",
        },
    )
    oss_state.append(path, "2026-01-02T00:00:00Z", "an unrelated tick decision")
    oss_state.append(
        path,
        "2026-01-03T00:00:00Z",
        "intake",
        detail={"intake": {"filed": 1, "merged": 2}},
    )
    entry, verdict, identity = oss_state._last_doctor_route(path)
    assert entry is not None
    assert verdict == "usable with gaps -- 1 warning(s)"
    assert identity == "0.24.0, content abc"


def test_last_doctor_route_finds_the_newest_of_two_receipts():
    """A second receipt landing later must win over the first, the same way a
    later plugin-identity entry wins over an earlier one."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.json"
        oss_state.append(
            path,
            "2026-01-01T00:00:00Z",
            "doctor-route: first",
            detail={
                "doctor_route_verdict": "usable with gaps -- 1 warning(s)",
                "doctor_route_plugin_identity": "0.24.0, content abc",
            },
        )
        oss_state.append(
            path,
            "2026-01-02T00:00:00Z",
            "doctor-route: second",
            detail={
                "doctor_route_verdict": "not usable -- 1 failure(s)",
                "doctor_route_plugin_identity": "0.25.0, content def",
            },
        )
        entry, verdict, identity = oss_state._last_doctor_route(path)
        assert verdict == "not usable -- 1 failure(s)"
        assert identity == "0.25.0, content def"
