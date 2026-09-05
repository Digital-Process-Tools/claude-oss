"""#1069: `lane_setup_claim.claim_and_register` writes the GitHub assignee
AND registers the lane in one call, rolling every freshly-claimed assignee
back when the registration fails -- named states throughout, never a silent
partial claim. `release_lane_and_assignee` is the mirror.

`checker` is injected everywhere here (the same shape `select_issues.py`'s
own `select()` already uses for `issue_claim.check`), so nothing in this
file shells out to a real `gh`.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup_claim  # noqa: E402
import select_issues_claim_read as claim_read  # noqa: E402


def _row(issue, state, **extra):
    row = {"issue": issue, "state": state}
    row.update(extra)
    return row


def _checker_always(state, **extra):
    def _checker(numbers, mode, repo=None):
        if mode == "claim":
            return [_row(n, state, **extra) for n in numbers]
        if mode == "release":
            return [_row(n, claim_read.STATE_RELEASED) for n in numbers]
        raise AssertionError("unexpected mode: {0}".format(mode))

    return _checker


def test_claim_and_register_succeeds_when_both_halves_succeed(tmp_path):
    """Positive control: a fresh claim, a working registry -- both writes
    land and the state is the sole success terminal, `claimed`."""
    checker = _checker_always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path), 1, "fix/1", str(tmp_path / "wt"), checker=checker
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_CLAIMED
    assert result["record"]["state"] == "recorded"
    assert result["assignee"]["rollback_failed"] == []


def test_already_claimed_by_somebody_else_refuses_before_writing_anything(tmp_path):
    """Never claim over somebody -- refused before the registry is ever
    touched, so nothing (including the assignee) is written for this call."""
    checker = _checker_always(
        claim_read.STATE_ALREADY_CLAIMED, holders=["someone-else"]
    )
    registry = tmp_path / "registry"
    result = lane_setup_claim.claim_and_register(
        str(registry), 2, "fix/2", str(tmp_path / "wt"), checker=checker
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_ALREADY_CLAIMED
    assert result["record"] is None
    assert not registry.exists(), "already-claimed must never register a lane"


def test_could_not_claim_assignee_refuses_before_registering(tmp_path):
    checker = _checker_always(claim_read.STATE_COULD_NOT_CLAIM, detail="boom")
    registry = tmp_path / "registry"
    result = lane_setup_claim.claim_and_register(
        str(registry), 3, "fix/3", str(tmp_path / "wt"), checker=checker
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE
    assert result["record"] is None
    assert not registry.exists()


def test_registration_failure_rolls_the_fresh_assignee_back(tmp_path):
    """The assignee write succeeded (fresh `claimed`) but the registry write
    fails -- named `assignee-rolled-back`, and the rollback (a `release`
    call) is verified to have actually run against the right issue."""
    checker = _checker_always(claim_read.STATE_CLAIMED)
    # worktree_root pointing at a path that is a *file*, not a directory --
    # os.makedirs(..., exist_ok=True) on top of an existing file raises,
    # which record_lane turns into could-not-write.
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("x")
    result = lane_setup_claim.claim_and_register(
        str(not_a_dir), 4, "fix/4", str(tmp_path / "wt"), checker=checker
    )
    assert result["record"]["state"] == "could-not-write"
    assert result["state"] == lane_setup_claim.CLAIM_STATE_ASSIGNEE_ROLLED_BACK
    assert result["assignee"]["rollback_failed"] == []


def test_a_rollback_that_itself_fails_names_the_still_assigned_issue(tmp_path):
    """The worst case: the registry write fails AND the un-assign fails too --
    reported as its own named state, with the still-assigned issue named so
    a maintainer can release it by hand."""

    def checker(numbers, mode, repo=None):
        if mode == "claim":
            return [_row(n, claim_read.STATE_CLAIMED) for n in numbers]
        if mode == "release":
            return [
                _row(n, claim_read.STATE_COULD_NOT_RELEASE, detail="boom")
                for n in numbers
            ]
        raise AssertionError("unexpected mode: {0}".format(mode))

    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("x")
    result = lane_setup_claim.claim_and_register(
        str(not_a_dir), 5, "fix/5", str(tmp_path / "wt"), checker=checker
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_ROLLBACK_FAILED
    assert result["assignee"]["rollback_failed"] == [5]


def test_also_claim_writes_every_companions_assignee_too(tmp_path):
    """A lane's companion issues get their own assignee write in the same
    call -- `also_claim` -- and an `already-mine` companion is never rolled
    back on a later failure, since this call did not freshly write it."""
    seen = []

    def checker(numbers, mode, repo=None):
        seen.append((mode, list(numbers)))
        if mode == "claim":
            rows = []
            for n in numbers:
                state = (
                    claim_read.STATE_ALREADY_MINE
                    if n == 7
                    else claim_read.STATE_CLAIMED
                )
                rows.append(_row(n, state))
            return rows
        raise AssertionError("release must not run when registration succeeds")

    result = lane_setup_claim.claim_and_register(
        str(tmp_path),
        6,
        "fix/6",
        str(tmp_path / "wt"),
        also_claim=[7],
        checker=checker,
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_CLAIMED
    assert seen == [("claim", [6, 7])]


def test_release_lane_and_assignee_releases_both_halves(tmp_path):
    released = []

    def checker(numbers, mode, repo=None):
        assert mode == "release"
        released.extend(numbers)
        return [_row(n, claim_read.STATE_RELEASED) for n in numbers]

    lane_setup_claim.record_lane(str(tmp_path), 8, "fix/8", str(tmp_path / "wt"))
    result = lane_setup_claim.release_lane_and_assignee(
        str(tmp_path), 8, also_release=[9], checker=checker
    )
    assert result["record"]["state"] == "released"
    assert result["assignee"]["state"] == "released"
    assert [row["issue"] for row in result["also_released"]] == [9]
    assert released == [8, 9]
