"""#1266: nothing waited on the release commit's own CI before the tag was
pushed. `v0.27.0` tagged and published at `fb73907` before that commit's own
`tests` run had even started -- it concluded RED four minutes later, on
every non-CodeQL leg on all three operating systems.

Gates 1-6 (`skills/manager/phases/release.md`, `commands/release.md`) verify
the default branch is green *before* the release commit is written. That is
the right check for the delta being released; it says nothing about the
release commit itself, which is new content (folded `CHANGELOG.md`,
rewritten version sites, the `CLAUDE.md` marker paragraph). This module is
the missing check: wait for *that* commit's own CI to conclude before a tag
is created and pushed.

Same shape as `pr_green.py` (#1086) on purpose, not a fresh design: a commit
pushed straight to the default branch has no check rollup to poll, but
`gh run list --commit SHA` gives the same kind of list, one row per workflow
*run* rather than per PR check -- and the same `_gh`-through-subprocess
approach, so `--wait` can actually poll from inside one call, the same
reason `pr_green.py` does not shell out through the Bash tool the
raw-command guard hooks.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_ci_wait as rcw  # noqa: E402

SHA = "a" * 40


def _run_sequence(responses):
    """Same fixture shape as `test_pr_green_1086.py`'s own: one
    ``(returncode, stdout, stderr)`` per expected `gh` call, in order."""
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


def _runs_json(rows):
    return json.dumps(rows)


def _row(name="tests", status="completed", conclusion="success", url=None, event=None):
    row = {
        "workflowName": name,
        "status": status,
        "conclusion": conclusion,
        "headSha": SHA,
    }
    if url is not None:
        row["url"] = url
    if event is not None:
        row["event"] = event
    return row


def _workflows_dir(tmp_path, names=("tests", "changelog")):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    for name in names:
        (wf_dir / "{0}.yml".format(name)).write_text(
            "name: {0}\n\non:\n  push:\n    branches: [main]\n".format(name),
            encoding="utf-8",
        )
    return wf_dir


# --------------------------------------------------------------- read_commit: green


def test_read_commit_green_when_every_run_passed():
    rows = [
        _row("tests", conclusion="success"),
        _row("changelog", conclusion="success"),
    ]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_GREEN
    assert entry["sha"] == SHA


def test_read_commit_neutral_and_skipped_conclusions_count_as_passing():
    rows = [
        _row("tests", conclusion="neutral"),
        _row("changelog", conclusion="skipped"),
    ]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_GREEN


# --------------------------------------------------------------- read_commit: red


def test_read_commit_red_when_a_run_failed():
    rows = [_row("tests", conclusion="failure")]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_RED
    assert entry["failing"][0]["workflow"] == "tests"


def test_read_commit_red_on_an_unrecognised_completed_conclusion():
    """An unrecognised conclusion is a finding, not a silent pass -- the same
    discipline `pr_green.py`'s own sibling test pins."""
    rows = [_row("tests", conclusion="some_future_conclusion_this_never_saw")]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_RED


def test_read_commit_red_reported_even_with_a_pending_sibling():
    """A red run does not wait for a still-running sibling (#1086's own third
    comment, carried over)."""
    rows = [
        _row("tests", conclusion="failure"),
        _row("changelog", status="in_progress", conclusion=None),
    ]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_RED


# --------------------------------------------------------------- read_commit: pending


def test_read_commit_pending_when_a_run_is_still_running():
    rows = [_row("tests", status="in_progress", conclusion=None)]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_PENDING


def test_read_commit_pending_when_no_run_has_shown_up_yet():
    """A workflow run is not created the instant a commit is pushed -- an
    empty list must read as `pending` (nothing to fail, nothing that passed
    either), never as `green` and never as `red`. This is #1266's own
    described failure mode with the check inverted: `v0.27.0` was tagged
    before a single leg had even started, i.e. while the rollup was still
    exactly this shape."""
    run = _run_sequence([(0, _runs_json([]), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_PENDING


def test_read_commit_pending_treats_cancelled_as_not_yet_safe():
    """A concurrency-cancelled run is not a green run (#1266's own second
    named requirement) -- `cancelled` must not be read as a passing
    conclusion."""
    rows = [_row("tests", conclusion="cancelled")]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_RED


# --------------------------------------------------------------- read_commit: could-not-read


def test_read_commit_could_not_read_on_gh_failure():
    run = _run_sequence([(1, "", "some gh error")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_COULD_NOT_READ


def test_read_commit_could_not_read_on_unparseable_json():
    run = _run_sequence([(0, "not json", "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_COULD_NOT_READ


def test_could_not_read_never_folds_into_pending_or_green():
    """Negative-assertion pairing (CLAUDE.md's own rule): `could-not-read`
    must render as neither of the other two -- proven against both in the
    same fixture family as the two tests directly above and below."""
    run = _run_sequence([(1, "", "boom")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] != rcw.STATE_PENDING
    assert entry["state"] != rcw.STATE_GREEN
    # Positive control: a genuinely empty, well-formed rollup is `pending`,
    # not `could-not-read` -- proves the assertion above is not vacuously
    # true because nothing can ever be pending.
    run2 = _run_sequence([(0, _runs_json([]), "")])
    entry2 = rcw.read_commit(SHA, "gh", run2)
    assert entry2["state"] == rcw.STATE_PENDING


# --------------------------------------------------------------- read_commit: --require-event (#1324)


def test_require_event_does_not_report_green_from_a_push_triggered_run_alone():
    """#1324: this repo reserves its full 3-OS x Python-3.9-3.12 matrix for a
    `workflow_dispatch` carrying `full_matrix: true` (#1246); the ordinary
    push-triggered run of the same workflow is only the reduced 5-leg set.
    A caller waiting specifically for the dispatched full-matrix run must
    never read a green push-triggered run alone as satisfying that wait --
    zero runs matching the required event is its own state, never GREEN."""
    rows = [_row("tests", conclusion="success", event="push")]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run, expect_event="workflow_dispatch")
    assert entry["state"] != rcw.STATE_GREEN
    assert entry["state"] == rcw.STATE_PENDING


def test_require_event_reports_green_once_the_matching_run_is_green():
    """Positive control for the test above: once a run with the required
    event actually exists and is green, the wait is satisfied -- proves the
    assertion above is not vacuously true because nothing matching the event
    can ever be green."""
    rows = [
        _row("tests", conclusion="success", event="push"),
        _row("tests", conclusion="success", event="workflow_dispatch"),
    ]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run, expect_event="workflow_dispatch")
    assert entry["state"] == rcw.STATE_GREEN


def test_require_event_reports_red_from_the_matching_run_even_if_others_passed():
    """A green push-triggered run must not mask a failing dispatched run
    either -- the filter applies to RED the same way it applies to GREEN."""
    rows = [
        _row("tests", conclusion="success", event="push"),
        _row("tests", conclusion="failure", event="workflow_dispatch"),
    ]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run, expect_event="workflow_dispatch")
    assert entry["state"] == rcw.STATE_RED


def test_require_event_none_preserves_old_behaviour():
    """Regression control: omitting `expect_event` (the CLI default) must
    keep classifying by conclusion alone, exactly as before #1324."""
    rows = [_row("tests", conclusion="success", event="push")]
    run = _run_sequence([(0, _runs_json(rows), "")])
    entry = rcw.read_commit(SHA, "gh", run)
    assert entry["state"] == rcw.STATE_GREEN


def test_main_wires_require_event_through_to_a_pending_verdict(capsys):
    """The CLI flag actually reaches `read_commit`, not just the library
    function directly."""
    rows = [_row("tests", conclusion="success", event="push")]
    run = _run_sequence([(0, _runs_json(rows), "")])
    code = rcw.main(["--commit", SHA, "--require-event", "workflow_dispatch"], run=run)
    assert code == rcw.EXIT_CODES[rcw.STATE_PENDING]
    out = capsys.readouterr().out
    assert "PENDING" in out
    assert "workflow_dispatch" in out


# --------------------------------------------------------------- --wait / timeout


def test_wait_for_conclusion_polls_until_not_pending():
    responses = [
        (0, _runs_json([_row("tests", status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row("tests", status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row("tests", conclusion="success")]), ""),
    ]
    run = _run_sequence(responses)
    sleeps = []
    entry = rcw.wait_for_conclusion(
        SHA,
        "gh",
        run,
        interval=1,
        timeout=None,
        sleep=sleeps.append,
        clock=iter([0, 1, 2, 3]).__next__,
    )
    assert entry["state"] == rcw.STATE_GREEN
    assert len(sleeps) == 2


def test_wait_for_conclusion_returns_none_on_timeout_while_still_pending():
    """A tag is not revocable, so a timeout with no answer must be
    distinguishable from a real conclusion -- the caller's cue to stop
    rather than tag on a guess."""
    run = _run_sequence(
        [(0, _runs_json([_row("tests", status="in_progress", conclusion=None)]), "")]
        * 3
    )
    entry = rcw.wait_for_conclusion(
        SHA,
        "gh",
        run,
        interval=1,
        timeout=2,
        sleep=lambda s: None,
        clock=iter([0, 1, 3]).__next__,
    )
    assert entry is None


# --------------------------------------------------------------- main() / exit codes


def test_main_exit_codes_green_red_could_not_read_pending():
    assert rcw.EXIT_CODES[rcw.STATE_GREEN] == 0
    assert rcw.EXIT_CODES[rcw.STATE_RED] == 1
    assert rcw.EXIT_CODES[rcw.STATE_COULD_NOT_READ] == 3
    assert rcw.EXIT_CODES[rcw.STATE_PENDING] == 4


def test_exit_codes_never_collide_with_argparse_usage_error():
    """Self-review (#1266): argparse.ArgumentParser.error() always exits 2 --
    verified directly by the auditor spawn (`python3 scripts/release_ci_wait.py`
    with no `--commit` exits 2). None of this module's own states may sit on
    that number, the same discipline `cohort_citation_order.py`'s own
    `EXIT_DECLINED` fix (#1267) applies in this same commit -- a caller
    branching on exit code alone must be able to tell 'still pending' from
    'you invoked this wrong'."""
    values = list(rcw.EXIT_CODES.values())
    assert len(values) == len(set(values)), "exit codes must be pairwise distinct"
    assert 2 not in values, "exit 2 is reserved for argparse usage errors"


def test_missing_commit_flag_exits_with_the_argparse_usage_code():
    with pytest.raises(SystemExit) as excinfo:
        rcw.main([], run=_run_sequence([]))
    assert excinfo.value.code == 2


def test_an_abbreviated_sha_is_refused_with_the_argparse_usage_code():
    """#1266's own module docstring: a short sha silently returns no runs from
    `gh run list --commit` rather than failing -- refused before any `gh`
    call is made, rather than read as `pending`."""
    with pytest.raises(SystemExit) as excinfo:
        rcw.main(["--commit", "abc123"], run=_run_sequence([]))
    assert excinfo.value.code == 2
