"""#1086: one call, several pull requests, states as exit codes -- not prose an
`until ... grep` loop has to match.

`trap.d/1066.grep-negation-contains-its-own-positive.md`: a wait loop matched
`⚠ NOT ALL GREEN` against the substring `ALL GREEN` and exited green with 12
checks still pending. This module removes the substring-collision class
rather than guarding against it: the caller reads an exit code, not prose.

Per the maintainer's own comments on #1086 (which supersede the issue body's
original aggregate-precedence shaping): scan N named pull requests (or
--all-open) in order, and stop at the **first** one that is not pending --
there is no aggregate and no wait-for-all. `could-not-read` must never fold
into `pending` (a spinning wait loop) or into `green` (a blind merge) -- every
"must not fold" case here is paired with a "must fire" case in the same
fixture, per CLAUDE.md's own negative-assertion rule.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pr_green  # noqa: E402


def _run_sequence(responses):
    """``responses``: one ``(returncode, stdout, stderr)`` per expected `gh`
    call, in call order. Recording argv lets a test assert which calls were
    (or were not) made -- e.g. that a log fetch never happens for a green PR.
    """
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


def _row(name, workflow, status="COMPLETED", conclusion="SUCCESS", details_url=None):
    row = {
        "name": name,
        "workflowName": workflow,
        "status": status,
        "conclusion": conclusion,
    }
    if details_url is not None:
        row["detailsUrl"] = details_url
    return row


def _workflows_dir(tmp_path, names=("tests", "changelog")):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    for name in names:
        (wf_dir / "{0}.yml".format(name)).write_text(
            "name: {0}\n\non:\n  pull_request:\n".format(name), encoding="utf-8"
        )
    return wf_dir


# --------------------------------------------------------------- read_pr: green


def test_read_pr_green_when_every_leg_passed(tmp_path):
    rows = [_row("tests (3.11)", "tests"), _row("changelog", "changelog")]
    run = _run_sequence([(0, _rollup_json(101, "fix/101", "abc123", rows), "")])
    wf_dir = _workflows_dir(tmp_path)
    entry = pr_green.read_pr(101, "gh", run, workflows_dir=wf_dir)
    assert entry["state"] == pr_green.STATE_GREEN
    assert entry["branch"] == "fix/101"
    assert entry["sha"] == "abc123"
    assert entry["missing_workflows"] == []


def test_read_pr_green_names_a_declared_workflow_that_produced_no_run():
    """A declared pull_request-triggered workflow with no row in the rollup is
    named separately -- never silently folded into "every leg passed"."""
    rows = [_row("tests (3.11)", "tests")]
    run = _run_sequence([(0, _rollup_json(101, "fix/101", "abc123", rows), "")])
    entry = pr_green.read_pr(
        101, "gh", run, workflows_dir=None, declared_workflows={"tests", "changelog"}
    )
    assert entry["state"] == pr_green.STATE_GREEN
    assert entry["missing_workflows"] == ["changelog"]


# --------------------------------------------------------------- read_pr: red


def test_read_pr_red_names_branch_sha_and_failing_legs():
    rows = [
        _row(
            "tests (3.11)",
            "tests",
            conclusion="FAILURE",
            details_url="https://github.com/o/r/actions/runs/555/job/999",
        ),
        _row("changelog", "changelog"),
    ]
    run = _run_sequence(
        [
            (0, _rollup_json(202, "fix/202", "deadbee", rows), ""),
            (0, "some ok output\nError: assertion failed on line 4\n", ""),
        ]
    )
    entry = pr_green.read_pr(202, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_RED
    assert entry["branch"] == "fix/202"
    assert entry["sha"] == "deadbee"
    assert len(entry["failing"]) == 1
    leg = entry["failing"][0]
    assert leg["name"] == "tests (3.11)"
    assert leg["workflow"] == "tests"
    # the shortest decisive line, fetched via the run/job id parsed out of detailsUrl
    assert leg["log_line"] == "Error: assertion failed on line 4"
    run_call = run.calls[1]
    assert "555" in run_call and "999" in run_call


def test_read_pr_red_even_with_other_legs_still_pending():
    """A red leg is actionable immediately -- it does not wait for its
    neighbours to finish, per the maintainer's third comment on #1086."""
    rows = [
        _row("tests (3.11)", "tests", conclusion="FAILURE"),
        _row("tests (3.12)", "tests", status="IN_PROGRESS", conclusion=None),
    ]
    run = _run_sequence([(0, _rollup_json(303, "fix/303", "cafefee", rows), "")])
    entry = pr_green.read_pr(303, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_RED


def test_read_pr_red_on_an_unrecognised_completed_conclusion():
    """A completed check with a conclusion this module has never seen must
    never render as green -- an unrecognised state is a finding, not a pass."""
    rows = [_row("weird-check", "tests", conclusion="STALE")]
    run = _run_sequence([(0, _rollup_json(404, "fix/404", "f00d", rows), "")])
    entry = pr_green.read_pr(404, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_RED


# --------------------------------------------------------------- read_pr: pending


def test_read_pr_pending_when_a_leg_is_still_running():
    rows = [
        _row("tests (3.11)", "tests"),
        _row("tests (3.12)", "tests", status="IN_PROGRESS", conclusion=None),
    ]
    run = _run_sequence([(0, _rollup_json(505, "fix/505", "beef00", rows), "")])
    entry = pr_green.read_pr(505, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_PENDING


def test_read_pr_pending_with_an_empty_rollup():
    """No checks reported yet -- not a read failure, not green."""
    run = _run_sequence([(0, _rollup_json(606, "fix/606", "0000", []), "")])
    entry = pr_green.read_pr(606, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_PENDING


# --------------------------------------------------------------- read_pr: could-not-read


def test_read_pr_could_not_read_on_a_nonzero_gh_exit():
    run = _run_sequence([(1, "", "gh: pull request not found")])
    entry = pr_green.read_pr(9999, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_COULD_NOT_READ
    assert "not found" in entry["detail"]


def test_read_pr_could_not_read_on_unparseable_json():
    run = _run_sequence([(0, "not json{{{", "")])
    entry = pr_green.read_pr(1, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_COULD_NOT_READ


def test_read_pr_could_not_read_when_gh_process_fails_to_start():
    def run(cmd, **kwargs):
        raise FileNotFoundError("no such file: gh")

    entry = pr_green.read_pr(1, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_COULD_NOT_READ


# --------------- could-not-read must never fold into pending or green ---------------


def test_could_not_read_is_not_pending_and_is_not_green():
    """Paired with the positive controls above (a real pending PR reads
    `pending`, a real clean PR reads `green`) -- the negative-assertion rule."""
    run = _run_sequence([(1, "", "network error")])
    entry = pr_green.read_pr(1, "gh", run, workflows_dir=None)
    assert entry["state"] not in (pr_green.STATE_PENDING, pr_green.STATE_GREEN)
    assert entry["state"] == pr_green.STATE_COULD_NOT_READ


def test_exit_codes_are_distinct_and_could_not_read_outranks_nothing_implicitly():
    codes = pr_green.EXIT_CODES
    assert len(set(codes.values())) == 4
    assert codes[pr_green.STATE_GREEN] == 0
    assert codes[pr_green.STATE_COULD_NOT_READ] != codes[pr_green.STATE_PENDING]
    assert codes[pr_green.STATE_COULD_NOT_READ] != codes[pr_green.STATE_GREEN]


# --------------------------------------------------------------- scan(): first non-pending


def test_scan_stops_at_the_first_non_pending_pr_in_order():
    """Two PRs: the first is pending, the second is green. `scan` must return
    the second and must not have needed a third call for a PR after it."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(2, "fix/2", "b", green_rows), ""),
        ]
    )
    entry = pr_green.scan([1, 2, 3], "gh", run, workflows_dir=None)
    assert entry is not None
    assert entry["pr"] == 2
    assert entry["state"] == pr_green.STATE_GREEN
    assert len(run.calls) == 2  # PR 3 was never read


def test_scan_returns_none_when_every_named_pr_is_pending():
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(2, "fix/2", "b", pending_rows), ""),
        ]
    )
    entry = pr_green.scan([1, 2], "gh", run, workflows_dir=None)
    assert entry is None


def test_scan_stops_at_a_red_pr_without_reading_the_rest():
    red_rows = [_row("tests", "tests", conclusion="FAILURE")]
    run = _run_sequence([(0, _rollup_json(1, "fix/1", "a", red_rows), "")])
    entry = pr_green.scan([1, 2, 3], "gh", run, workflows_dir=None)
    assert entry["pr"] == 1
    assert entry["state"] == pr_green.STATE_RED
    assert len(run.calls) == 1


def test_scan_stops_at_a_could_not_read_pr_without_reading_the_rest():
    run = _run_sequence([(1, "", "boom")])
    entry = pr_green.scan([1, 2, 3], "gh", run, workflows_dir=None)
    assert entry["pr"] == 1
    assert entry["state"] == pr_green.STATE_COULD_NOT_READ
    assert len(run.calls) == 1


# --------------------------------------------------------------- wait_for_first_actionable


def test_wait_polls_while_all_pending_then_returns_the_first_actionable():
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", green_rows), ""),
        ]
    )
    sleeps = []
    entry = pr_green.wait_for_first_actionable(
        [1], "gh", run, workflows_dir=None, interval=45, sleep=sleeps.append
    )
    assert entry["state"] == pr_green.STATE_GREEN
    assert len(run.calls) == 3
    assert sleeps == [45, 45]


def test_wait_times_out_returning_none_while_everything_is_still_pending():
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
        ]
    )
    clock = iter([0.0, 10.0, 999.0])
    entry = pr_green.wait_for_first_actionable(
        [1],
        "gh",
        run,
        workflows_dir=None,
        interval=45,
        timeout=20,
        sleep=lambda _s: None,
        clock=lambda: next(clock),
    )
    assert entry is None


# --------------------------------------------------------------- list_open_pr_numbers


def test_list_open_pr_numbers_sorted():
    run = _run_sequence(
        [(0, json.dumps([{"number": 30}, {"number": 5}, {"number": 17}]), "")]
    )
    numbers, err = pr_green.list_open_pr_numbers("gh", run)
    assert err is None
    assert numbers == [5, 17, 30]


def test_list_open_pr_numbers_could_not_read_on_gh_failure():
    run = _run_sequence([(1, "", "gh: not authenticated")])
    numbers, err = pr_green.list_open_pr_numbers("gh", run)
    assert numbers is None
    assert "not authenticated" in err


# --------------------------------------------------------------- CLI: main()


def _cli_run_factory(responses):
    return _run_sequence(responses)


def test_cli_exits_0_on_green(monkeypatch, capsys):
    rows = [_row("tests", "tests")]
    run = _run_sequence([(0, _rollup_json(11, "fix/11", "aaa", rows), "")])
    monkeypatch.setattr(pr_green.shutil, "which", lambda name: "/usr/bin/gh")
    rc = pr_green.main(["11"], run=run)
    out = capsys.readouterr().out
    assert rc == 0
    assert "GREEN" in out
    assert "#11" in out


def test_cli_exits_1_on_red_and_prints_branch_and_leg(monkeypatch, capsys):
    rows = [_row("tests (3.11)", "tests", conclusion="FAILURE")]
    run = _run_sequence(
        [
            (0, _rollup_json(22, "fix/22", "bbb", rows), ""),
            (0, "some log\nlast line here\n", ""),
        ]
    )
    monkeypatch.setattr(pr_green.shutil, "which", lambda name: "/usr/bin/gh")
    rc = pr_green.main(["22"], run=run)
    out = capsys.readouterr().out
    assert rc == 1
    assert "RED" in out
    assert "fix/22" in out
    assert "tests (3.11)" in out


def test_cli_exits_3_on_could_not_read_never_2_never_0(monkeypatch, capsys):
    run = _run_sequence([(1, "", "gh: rate limited")])
    monkeypatch.setattr(pr_green.shutil, "which", lambda name: "/usr/bin/gh")
    rc = pr_green.main(["33"], run=run)
    out = capsys.readouterr().out
    assert rc == 3
    assert rc not in (0, 2)
    assert "COULD-NOT-READ" in out


def test_cli_exits_2_when_all_named_prs_are_pending_and_no_wait_given(
    monkeypatch, capsys
):
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    run = _run_sequence([(0, _rollup_json(44, "fix/44", "ccc", pending_rows), "")])
    monkeypatch.setattr(pr_green.shutil, "which", lambda name: "/usr/bin/gh")
    rc = pr_green.main(["44"], run=run)
    out = capsys.readouterr().out
    assert rc == 2
    assert "PENDING" in out


def test_cli_requires_pr_numbers_or_all_open(monkeypatch, capsys):
    monkeypatch.setattr(pr_green.shutil, "which", lambda name: "/usr/bin/gh")
    with pytest.raises(SystemExit):
        pr_green.main([], run=_run_sequence([]))


# ------------------------------------------ self-review fixes (#1086) ------------------------------------------
# Two real defects found by the review spawns and fixed in the same commit:
# (1) a legacy StatusContext rollup row (no `status`/`conclusion` keys, only
#     `state`) was misread as a failing CheckRun and turned a green PR red;
# (2) an unreadable workflows directory rendered identically to one that
#     genuinely declares zero pull_request-triggered workflows -- this
#     repository's own named defect class, an absence the tool produced
#     read as an absence in the world.


def _status_context_row(context, state="SUCCESS", target_url=None):
    row = {"context": context, "state": state}
    if target_url is not None:
        row["targetUrl"] = target_url
    return row


def test_read_pr_green_with_a_passing_legacy_status_context_row():
    """A StatusContext row (e.g. Codecov, a preview-deploy bot) has no
    `status`/`conclusion` keys at all -- reading them as `None` must not
    turn a passing legacy check into a failure."""
    rows = [_row("tests", "tests"), _status_context_row("codecov/project")]
    run = _run_sequence([(0, _rollup_json(707, "fix/707", "aa11", rows), "")])
    entry = pr_green.read_pr(707, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_GREEN


def test_read_pr_red_with_a_failing_legacy_status_context_row():
    rows = [_status_context_row("codecov/project", state="FAILURE")]
    run = _run_sequence([(0, _rollup_json(708, "fix/708", "bb22", rows), "")])
    entry = pr_green.read_pr(708, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_RED
    assert entry["failing"][0]["name"] == "codecov/project"


def test_read_pr_pending_with_a_pending_legacy_status_context_row():
    rows = [_status_context_row("codecov/project", state="PENDING")]
    run = _run_sequence([(0, _rollup_json(709, "fix/709", "cc33", rows), "")])
    entry = pr_green.read_pr(709, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_PENDING


def test_declared_pr_workflow_names_reports_ok_true_on_a_readable_directory(tmp_path):
    wf_dir = _workflows_dir(tmp_path, names=("tests",))
    names, ok = pr_green._declared_pr_workflow_names(wf_dir)
    assert ok is True
    assert names == {"tests"}


def test_declared_pr_workflow_names_reports_ok_false_on_an_unreadable_directory(
    tmp_path,
):
    """Paired with the positive control above: a genuinely empty, readable
    directory must render differently from one that could not be listed at
    all -- an unreadable directory must never render as 'declares nothing'."""
    missing = tmp_path / "does-not-exist"
    names, ok = pr_green._declared_pr_workflow_names(missing)
    assert ok is False
    assert names == set()


def test_read_pr_green_missing_workflows_is_none_when_the_directory_is_unreadable(
    tmp_path,
):
    """The end-to-end version of the same case: `missing_workflows` must be
    `None` (could not determine), never `[]` (checked, none missing) --
    those are two different facts and must not render identically."""
    rows = [_row("tests", "tests")]
    run = _run_sequence([(0, _rollup_json(710, "fix/710", "dd44", rows), "")])
    entry = pr_green.read_pr(710, "gh", run, workflows_dir=tmp_path / "does-not-exist")
    assert entry["state"] == pr_green.STATE_GREEN
    assert entry["missing_workflows"] is None


def test_read_pr_green_missing_workflows_is_the_real_empty_list_when_checked_clean(
    tmp_path,
):
    """The positive control for the case above: a readable directory that
    genuinely declares every workflow already seen renders `[]`, not
    `None`."""
    wf_dir = _workflows_dir(tmp_path, names=("tests",))
    rows = [_row("tests", "tests")]
    run = _run_sequence([(0, _rollup_json(711, "fix/711", "ee55", rows), "")])
    entry = pr_green.read_pr(711, "gh", run, workflows_dir=wf_dir)
    assert entry["state"] == pr_green.STATE_GREEN
    assert entry["missing_workflows"] == []


def test_cli_notes_could_not_determine_missing_workflows_on_an_unreadable_directory(
    monkeypatch, capsys, tmp_path
):
    rows = [_row("tests", "tests")]
    run = _run_sequence([(0, _rollup_json(712, "fix/712", "ff66", rows), "")])
    monkeypatch.setattr(pr_green.shutil, "which", lambda name: "/usr/bin/gh")
    rc = pr_green.main(
        ["712", "--project-dir", str(tmp_path / "does-not-exist")],
        run=run,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "could not determine" in out
