"""#1480 (finding 1): `pr_green.py`'s `_unresolved_runs` could hold `--wait`
at PENDING forever for a workflow run that is `completed` but produced zero
jobs -- observed as a real, reproducible GitHub Actions state rather than
only reasoned from the code (Digital-Process-Tools/claude-oss run 34676522288,
`status=completed`, `conclusion=cancelled`, `.../jobs?filter=all` returning
`{"jobs": []}` -- a run cancelled while still queued never produces a job and
the jobs endpoint reports zero for it permanently, not merely for the ~18s
window `_run_has_jobs`'s own docstring already documents for a partial
re-run).

Before this fix, nothing distinguished that permanent, zero-job `completed`
run from #1400's own reproduction (a `tests` run genuinely still in flight,
with no job reported *yet*) -- both produced `has_jobs is False` and both
were folded into `unresolved_runs`, so a caller reading `--wait` never saw
PENDING resolve.

`status` on the run object is now considered: a `completed` run is settled
regardless of its own job count, so it must never render as unresolved.
This is the must-fire case; #1400's own reproduction (`test_pr_green_1400.
py::test_read_pr_not_green_when_a_workflow_run_has_no_job_yet`, no `status`
key on the run object at all, meaning "not confirmed completed") is the
paired must-not-break control, re-run here unmodified to prove the fix does
not swallow the real race it was built for.
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


def _rollup_json(number, branch, sha, rows, url):
    return json.dumps(
        {
            "number": number,
            "headRefName": branch,
            "headRefOid": sha,
            "state": "OPEN",
            "url": url,
            "statusCheckRollup": rows,
        }
    )


def _row(name, workflow, status="COMPLETED", conclusion="SUCCESS"):
    return {
        "name": name,
        "workflowName": workflow,
        "status": status,
        "conclusion": conclusion,
    }


def _runs_json(runs):
    return json.dumps({"workflow_runs": runs})


def _jobs_json(jobs):
    return json.dumps({"jobs": jobs})


def test_a_completed_run_with_zero_jobs_reads_green_not_pending_forever():
    """Must fire: a `completed`/`cancelled` run that produced zero jobs must
    never count as unresolved -- it is settled, not a race in flight. Before
    the fix, this rendered PENDING with `unresolved_runs == ["tests"]`
    exactly like #1400's own genuine race, and `--wait` would hold there
    forever since a `completed` run's job count can never change."""
    rows = [
        _row("CodeQL", "CodeQL"),
        _row("fragment", "changelog"),
        _row("analyze", "CodeQL"),
    ]
    run = _run_sequence(
        [
            (
                0,
                _rollup_json(
                    381,
                    "fix/380",
                    "187135ca",
                    rows,
                    "https://github.com/o/r/pull/381",
                ),
                "",
            ),
            (
                0,
                _runs_json([{"id": 555, "name": "tests", "status": "completed"}]),
                "",
            ),
            (0, _jobs_json([]), ""),
        ]
    )
    entry = pr_green.read_pr(381, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_GREEN, entry
    assert entry["unresolved_runs"] == []


def test_an_in_flight_run_with_zero_jobs_still_reads_pending():
    """Must-not-break control, #1400's own reproduction unmodified: a run
    genuinely still in flight (no `status` on the run object at all, the
    same shape the real `head_sha` runs listing produced before this fix)
    with zero jobs so far is still reported unresolved."""
    rows = [
        _row("CodeQL", "CodeQL"),
        _row("fragment", "changelog"),
        _row("analyze", "CodeQL"),
    ]
    run = _run_sequence(
        [
            (
                0,
                _rollup_json(
                    381,
                    "fix/380",
                    "187135ca",
                    rows,
                    "https://github.com/o/r/pull/381",
                ),
                "",
            ),
            (0, _runs_json([{"id": 555, "name": "tests"}]), ""),
            (0, _jobs_json([]), ""),
        ]
    )
    entry = pr_green.read_pr(381, "gh", run, workflows_dir=None)
    assert entry["state"] != pr_green.STATE_GREEN
    assert entry["unresolved_runs"] == ["tests"]
