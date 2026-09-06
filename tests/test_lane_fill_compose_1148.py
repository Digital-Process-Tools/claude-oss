"""#1148: --claim emits step 5's ready --lane-fill PRIMARY:COUNT[:REASON]
token alongside the Agent(...) line it already renders, so nothing is
retyped by hand at oss_state.py --decision time.

The hidden judgment call this issue names: a short lane whose group
established no reason must still produce a token that oss_state.py
--decision refuses (#852) -- never one that quietly invents a reason.
That refusal is asserted directly here, not just the token's own text, per
the issue's own instruction.

Every must-not is paired with a must, per this repository's own rule for a
negative assertion (CLAUDE.md).
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402
import lane_setup_claim  # noqa: E402
import oss_state  # noqa: E402
import select_issues_claim_read as claim_read  # noqa: E402


def _row(issue, state, **extra):
    row = {"issue": issue, "state": state}
    row.update(extra)
    return row


def _mixed_checker(fail_issue, fail_state=claim_read.STATE_COULD_NOT_CLAIM):
    def _checker(numbers, mode, repo=None):
        if mode == "claim":
            return [
                _row(n, fail_state, detail="boom")
                if n == fail_issue
                else _row(n, claim_read.STATE_CLAIMED)
                for n in numbers
            ]
        if mode == "release":
            return [_row(n, claim_read.STATE_RELEASED) for n in numbers]
        raise AssertionError("unexpected mode: {0}".format(mode))

    return _checker


def _always(state):
    def _checker(numbers, mode, repo=None):
        if mode == "claim":
            return [_row(n, state) for n in numbers]
        if mode == "release":
            return [_row(n, claim_read.STATE_RELEASED) for n in numbers]
        raise AssertionError(mode)

    return _checker


def _payload(issue, claim_result):
    return {"issue": issue, "claim_result": claim_result}


# --------------------------------------------------------------- compose_lane_fill


def test_compose_lane_fill_renders_the_full_lane_token_with_no_reason(tmp_path):
    """Positive control: a full lane (3 held) needs no reason and gets none."""
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(_payload(1, result))
    assert fill["state"] == "rendered"
    assert fill["text"] == "1:3"


def test_compose_lane_fill_carries_the_reason_through_for_a_short_lane(tmp_path):
    """A short lane (2 held, the third failed) whose caller passed the
    group's own established short_reason gets a complete token."""
    checker = _mixed_checker(fail_issue=3)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(
        _payload(1, result), short_reason="board-exhausted"
    )
    assert fill["state"] == "rendered"
    assert fill["text"] == "1:2:board-exhausted"


def test_compose_lane_fill_never_invents_a_reason_for_a_short_lane(tmp_path):
    """The hidden judgment call: a short lane whose group carried no reason
    gets a token with no third field at all, never a fabricated one."""
    checker = _mixed_checker(fail_issue=3)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(_payload(1, result))
    assert fill["state"] == "rendered"
    assert fill["text"] == "1:2"


def test_the_unreasoned_short_token_still_gets_refused_by_oss_state(tmp_path):
    """The test that matters most (#1148's own words): assert the REFUSAL,
    not just the token's text. Feed the unreasoned token straight into
    oss_state.py's own lane_fill() -- the exact function `--decision`
    calls -- and confirm #852's guard still fires on it."""
    checker = _mixed_checker(fail_issue=3)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(_payload(1, result))
    entry = oss_state._lane_fill_argument(fill["text"])
    try:
        oss_state.lane_fill([entry], window="test tick")
    except oss_state.StateError as exc:
        assert "needs one of" in str(exc)
    else:
        raise AssertionError(
            "a short lane with no reason must be refused by oss_state.py "
            "(#852), not silently recorded"
        )


def test_the_reasoned_short_token_is_accepted_by_oss_state(tmp_path):
    """Positive control paired with the test above: the SAME short lane,
    given a real reason, is accepted rather than refused for some other,
    unrelated cause."""
    checker = _mixed_checker(fail_issue=3)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(
        _payload(1, result), short_reason="board-exhausted"
    )
    entry = oss_state._lane_fill_argument(fill["text"])
    recorded = oss_state.lane_fill([entry], window="test tick")
    assert recorded["state"] == oss_state.LANE_FILL_RECORDED
    assert recorded["lanes"][0]["reason"] == "board-exhausted"


def test_compose_lane_fill_drops_a_reason_given_for_a_full_lane(tmp_path):
    """A full lane makes no short-lane claim -- a reason passed in anyway
    (a caller's own mistake) must not land on the token, since oss_state.py's
    own lane_fill() refuses an entry pairing a reason with a full lane for a
    different, unrelated cause than #852's, and that refusal would obscure
    the one #1148 exists to keep firing."""
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(
        _payload(1, result), short_reason="board-exhausted"
    )
    assert fill["text"] == "1:3"


def test_compose_lane_fill_refuses_when_nothing_was_actually_held():
    fill = lane_setup.compose_lane_fill(_payload(1, None))
    assert fill["state"] == "no-claimed-issues"
    assert fill["text"] is None


def test_compose_lane_fill_refuses_when_the_primary_issue_is_not_held(tmp_path):
    checker = _mixed_checker(fail_issue=1)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        1,
        "fix/1",
        str(tmp_path / "wt"),
        also_claim=[2, 3],
        checker=checker,
    )
    fill = lane_setup.compose_lane_fill(_payload(1, result))
    assert fill["state"] == "primary-not-held"
    assert fill["text"] is None


# --------------------------------------------------------------- CLI: --claim renders the token too


def test_cli_claim_renders_the_lane_fill_token_alongside_agent_call(tmp_path):
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "x"], check=True
    )
    config = {
        "repo": "example/example",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "true",
        "docs_targets": [],
        "changelog_dir": "changelog.d",
    }
    (repo / lane_setup.CONFIG_NAME).write_text(json.dumps(config))
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "999",
            "--repo",
            str(repo),
            "--claim",
            "--lane",
            "a.py",
            "--phrase",
            "x",
            "--short-reason",
            "no-adjacent",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    # The claim itself needs a real GitHub call to fully succeed; what this
    # asserts is only that a --short-reason flag exists and is accepted by
    # argparse (never refused as an unknown option).
    assert "unrecognized arguments" not in result.stdout
    assert "--short-reason requires --claim" not in result.stdout


def test_cli_short_reason_without_claim_is_refused():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "999",
            "--lane",
            "a.py",
            "--short-reason",
            "no-adjacent",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 2
    assert "--short-reason requires --claim (#1148)" in result.stdout


def test_cli_short_reason_rejects_an_unknown_word():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "999",
            "--claim",
            "--lane",
            "a.py",
            "--phrase",
            "x",
            "--short-reason",
            "not-a-real-reason",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stdout
