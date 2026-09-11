"""#1458: a CANCELLED check-run superseded by a later run of the same name
must not read RED -- `pr_green.py` disagreed with supertool's own
`gh-pr:N:status` (`_checks.github_superseded`, #1792), which already excludes
a superseded conclusion from its failing tally.

Same rule as #1792, reproduced here rather than imported: a leg is
superseded only when another leg of the *same check name* started strictly
after this leg completed. Two same-named legs whose wall clocks overlap
(GitHub's default code-scanning setup emits two runs of one workflow per
push, #1640) supersede nothing and both still have to pass.

Every "must not fire" case here is paired with a "must fire" case in the
same fixture (CLAUDE.md's own negative-assertion rule): a CANCELLED leg with
no later run of the same name must still read as a real failure.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pr_green  # noqa: E402


def _run_sequence(responses):
    calls = []
    it = iter(responses)

    def run(cmd, **kwargs):
        calls.append(cmd)
        try:
            rc, out, err = next(it)
        except StopIteration:  # pragma: no cover - a fixture bug
            raise AssertionError(
                "more gh calls than the fixture staged: {0}".format(cmd)
            )
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def _rollup_json(number, branch, sha, rows):
    return json.dumps(
        {
            "number": number,
            "headRefName": branch,
            "headRefOid": sha,
            "state": "OPEN",
            "statusCheckRollup": rows,
        }
    )


def _row(
    name,
    workflow,
    status="COMPLETED",
    conclusion="SUCCESS",
    started_at=None,
    completed_at=None,
):
    row = {
        "name": name,
        "workflowName": workflow,
        "status": status,
        "conclusion": conclusion,
    }
    if started_at is not None:
        row["startedAt"] = started_at
    if completed_at is not None:
        row["completedAt"] = completed_at
    return row


def test_a_superseded_cancelled_leg_does_not_read_red():
    """The #1458 repro: `fragment` was CANCELLED at 22:23, then re-run and
    passed eight hours later -- the same shape as #1792's own worked
    example. `gh-pr:N:status` reads this leg as superseded, not failed."""
    rows = [
        _row(
            "fragment",
            "oss changelog",
            conclusion="CANCELLED",
            started_at="2026-09-11T22:00:00Z",
            completed_at="2026-09-11T22:23:00Z",
        ),
        _row(
            "fragment",
            "oss changelog",
            conclusion="SUCCESS",
            started_at="2026-09-12T06:30:00Z",
            completed_at="2026-09-12T06:35:00Z",
        ),
        _row("tests (3.11)", "tests"),
    ]
    run = _run_sequence(
        [(0, _rollup_json(658, "chore/scaffold", "2bcf6c3b", rows), "")]
    )
    entry = pr_green.read_pr(658, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_GREEN, entry
    assert entry["failing"] == [], entry["failing"]
    assert len(entry["superseded"]) == 1
    assert entry["superseded"][0]["name"] == "fragment"
    assert entry["superseded"][0]["conclusion"] == "CANCELLED"
    # A superseded conclusion is not a real failure -- no log-line fetch for it.
    assert run.calls == [run.calls[0]]


def test_a_cancelled_leg_with_no_later_run_of_the_same_name_still_reads_red():
    """Positive control: nothing superseded this one, so it is a real
    failure and must still block green."""
    rows = [
        _row(
            "fragment",
            "oss changelog",
            conclusion="CANCELLED",
            started_at="2026-09-11T22:00:00Z",
            completed_at="2026-09-11T22:23:00Z",
        ),
        _row("tests (3.11)", "tests"),
    ]
    run = _run_sequence(
        [
            (0, _rollup_json(659, "chore/scaffold", "cafef00d", rows), ""),
            (0, "some ok output\n", ""),
        ]
    )
    entry = pr_green.read_pr(659, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_RED, entry
    assert len(entry["failing"]) == 1
    assert entry["failing"][0]["name"] == "fragment"
    assert entry.get("superseded") == []


def test_two_overlapping_same_named_runs_supersede_nothing():
    """#1640 parity: GitHub's default code-scanning setup emits two runs of
    one workflow per push, started in the same second -- neither supersedes
    the other, and a failure among them must still read RED."""
    rows = [
        _row(
            "Analyze (python)",
            "codeql",
            conclusion="FAILURE",
            started_at="2026-09-11T22:00:00Z",
            completed_at="2026-09-11T22:05:00Z",
        ),
        _row(
            "Analyze (python)",
            "codeql",
            conclusion="SUCCESS",
            started_at="2026-09-11T22:00:01Z",
            completed_at="2026-09-11T22:06:00Z",
        ),
    ]
    run = _run_sequence(
        [
            (0, _rollup_json(660, "chore/scaffold", "0ff1ce", rows), ""),
            (0, "", ""),
        ]
    )
    entry = pr_green.read_pr(660, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_RED, entry
    assert len(entry["failing"]) == 1
    assert entry.get("superseded") == []


def test_render_names_a_superseded_leg_on_an_otherwise_green_pr():
    rows = [
        _row(
            "fragment",
            "oss changelog",
            conclusion="CANCELLED",
            started_at="2026-09-11T22:00:00Z",
            completed_at="2026-09-11T22:23:00Z",
        ),
        _row(
            "fragment",
            "oss changelog",
            conclusion="SUCCESS",
            started_at="2026-09-12T06:30:00Z",
            completed_at="2026-09-12T06:35:00Z",
        ),
    ]
    run = _run_sequence([(0, _rollup_json(661, "chore/scaffold", "abc123", rows), "")])
    entry = pr_green.read_pr(661, "gh", run, workflows_dir=None)
    line = pr_green._render(entry)
    assert "GREEN" in line
    assert "superseded" in line.lower()
    assert "fragment" in line
