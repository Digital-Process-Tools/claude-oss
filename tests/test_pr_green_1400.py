"""#1400: `pr_green.py` exits 0 GREEN while a declared workflow's own run on
this commit has produced no job yet.

`gh-pr:status` (see `claude-supertool`'s `presets/github/pr.py`) draws exactly
the line this module needs: query the Actions runs GitHub has actually
recorded for the head commit (`GET .../actions/runs?head_sha=`), independent
of anything parsed out of a workflow file, and for a run not yet reflected in
the check rollup, ask whether it has produced any job at all
(`GET .../actions/runs/{id}/jobs`). A run that exists with zero jobs is the
exact shape of the race #1400 reports -- a `tests` workflow run existed on
the commit, but none of its legs had reached the rollup yet, and the old
code folded that into "every leg passed" because the rollup was simply short
of rows for it.

The two cases pinned here, side by side, per CLAUDE.md's negative-assertion
rule: a run that exists but has produced no job yet must NOT read green
(must-not-fire), and the identical shape with a job present must still read
green once nothing else is missing (must-fire / positive control).
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


def test_read_pr_not_green_when_a_workflow_run_has_no_job_yet():
    """#1400's own reproduction: three concluded legs in the rollup, and a
    `tests` run recorded on the commit with zero jobs so far."""
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


def test_read_pr_green_when_the_same_run_has_produced_a_job():
    """Positive control, same shape: once the run has at least one job the
    PR still reads green."""
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
            (0, _jobs_json([{"name": "ubuntu (3.11)"}]), ""),
        ]
    )
    entry = pr_green.read_pr(381, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_GREEN
    assert entry["unresolved_runs"] == []


def test_render_pending_names_the_unresolved_run():
    """`_render`'s PENDING line names the run that has no job yet, not just
    `(rollup not yet reported)` -- the line a human actually reads."""
    entry = {
        "pr": 381,
        "state": pr_green.STATE_PENDING,
        "branch": "fix/380",
        "sha": "187135ca",
        "pending_legs": [],
        "unresolved_runs": ["tests"],
    }
    rendered = pr_green._render(entry)
    assert "PENDING" in rendered
    assert "tests (no job yet)" in rendered


def test_read_pr_green_unaffected_when_no_url_is_available():
    """No `url` field (older fixtures, or a shape gh did not return it for):
    owner/repo cannot be derived, so the reconciliation call is skipped
    rather than blocking green forever on an unreadable fact."""
    rows = [_row("tests (3.11)", "tests"), _row("changelog", "changelog")]
    run = _run_sequence(
        [
            (
                0,
                json.dumps(
                    {
                        "number": 101,
                        "headRefName": "fix/101",
                        "headRefOid": "abc123",
                        "state": "OPEN",
                        "statusCheckRollup": rows,
                    }
                ),
                "",
            )
        ]
    )
    entry = pr_green.read_pr(101, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_GREEN
    assert len(run.calls) == 1
