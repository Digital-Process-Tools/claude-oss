"""#1673: split one already-concluded CI job's own wall clock into
pre-step, step and post-step seconds, from GitHub's own per-step
timestamps -- the "what would actually settle it" ask from that issue's
own body.

Four occurrences of the same shape (#1658, #1660, #1671, #1673) all read
the cancellation's reported elapsed time as *the suite's own runtime*, and
built diagnostics that assume the process is genuinely blocked
(`tests/posthang_diagnostics_1660.py`'s stack dumps; the hand-maintained
margin in `tests/test_pytest_leg_timeout_1658.py`). Neither watchdog ever
fired across four occurrences -- because nothing inside the pytest
process is actually stuck. This module answers the prior, narrower
question those diagnostics cannot: given one job id, where does its own
wall clock actually go -- before the test step starts (checkout, tool
setup, install), inside the test step itself, or after the test step ends
(teardown, log upload, the runner's own post-job housekeeping)?

Manually walked once against two real jobs before this module existed
(#1673's own recon), from `gh api repos/OWNER/NAME/actions/jobs/ID`:

  job 105522023801 (`pytest (windows-latest, 3.12)`, PR #1654, cancelled)
    pre-step 28s / `Run tests` 1777s / post-step 5s -- job total 1810s.
  job 105519970619 (same leg, same day, a green `main` push)
    pre-step ~31s / `Run tests` 343s / post-step ~5s.

Both jobs' own `test-durations:` summary line in the log (out of scope
for this module -- a log search, not a step-timing read; see `gh-job:
N:grep` for that) reported almost IDENTICAL summed per-test call time
(1120.68s vs 1168.75s "total") despite the `Run tests` step itself being
roughly 5x longer on the cancelled job. That pairing is what distinguishes
"the suite is doing more work" (it is not -- the sums nearly match) from
"something during the run consumes wall clock without doing measured test
work" (worker starvation, IPC stalls, runner/fleet contention) or "a
leaked handle holds the step open after pytest's own summary line" (the
post-step gap here is 5s, not large) -- this module states the three-way
split so a future recurrence can be classified the same way without
hand-computing timestamps from a raw `gh api` read every time. It does
NOT itself decide which theory is right, and does not read the log's own
`test-durations:` line -- a caller wanting that cross-check still reads
the log separately (`gh-job:N:grep:test-durations`) and compares by hand.

Same `_gh`-through-injectable-``run`` shape as `release_ci_wait.py` and
`pr_green.py`: a standalone script called via `subprocess`, not through
the Bash tool the raw-command guard hooks, so it can be run from inside
one call. Python 3.9 compatible: no match statements, no ``X | Y``
annotations.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys

import gh_which

STATE_OK = "ok"
STATE_NO_MATCHING_STEP = "no-matching-step"
STATE_AMBIGUOUS_STEP = "ambiguous-step"
STATE_COULD_NOT_READ = "could-not-read"

# Not 2 -- argparse.ArgumentParser.error() always exits 2 for a usage
# error (a missing required flag, an unrecognised one), and a caller
# branching on exit code alone must be able to tell "you invoked this
# wrong" from a real classification of the job. Mirrors the discipline
# `release_ci_wait.py`'s own `EXIT_CODES` states explicitly for the
# identical reason (#1266/#1267 self-review).
EXIT_CODES = {
    STATE_OK: 0,
    STATE_NO_MATCHING_STEP: 1,
    STATE_AMBIGUOUS_STEP: 4,
    STATE_COULD_NOT_READ: 3,
}

DEFAULT_TEST_STEP_NAME = "Run tests"


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _flatten(text):
    """#1113's own discipline, carried over: text this module did not
    generate itself (`gh` stderr, a step's own name) collapsed onto one
    line before it lands in a line-structured receipt."""
    return " ".join(str(text).split())


def _gh(gh, args, run, timeout=30):
    """Run ``[gh] + args``, returning ``(stdout, detail)`` -- the same
    two-outcome shape `release_ci_wait.py`'s own `_gh` uses."""
    try:
        done = run(
            [gh] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    stdout = _decode(done.stdout)
    stderr = _decode(done.stderr)
    if done.returncode != 0:
        return None, (stderr.strip() or "gh exit {0}".format(done.returncode))
    return stdout, None


def _parse_ts(value):
    """Parse one GitHub Actions API timestamp (``2026-09-18T07:41:03Z``,
    always UTC per GitHub's own docs) into a naive UTC `datetime`, or
    `None` when it is missing or not that shape -- never raises, since a
    caller here always has a `could-not-read` state ready for it."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def read_job_timing(
    job_id, gh, run, repo, test_step_name=DEFAULT_TEST_STEP_NAME, timeout=30
):
    """Read one job's own step timestamps and split its wall clock into
    pre-step / step / post-step seconds.

    ``repo`` is required (``OWNER/NAME``) -- unlike `release_ci_wait.py`'s
    optional ``--repo`` (which falls back to `gh`'s own repo inference
    from the working directory), the jobs endpoint has no such fallback:
    ``gh api repos/{repo}/actions/jobs/{id}`` needs the owner/name in the
    path itself.

    Four states:

      ok                the named step was found, uniquely, and has a
                         `started_at`; `step_seconds_approximate` is
                         `True` when the step carried no `completed_at`
                         of its own (still running, or the runner never
                         recorded one before the job as a whole
                         concluded) -- approximated using the JOB's own
                         `completed_at` instead, so a step that never got
                         to report its own end is never silently read as
                         a step_seconds of zero.
      no-matching-step  the job was read successfully but has no step
                         named `test_step_name` -- a workflow rename or a
                         wrong argument, not a read failure. Carries
                         `step_names` (every step name this job actually
                         has) so a caller can see what to ask for instead.
      ambiguous-step    the job has MORE than one step named
                         `test_step_name` -- taking the first would
                         silently misattribute a later matching step's
                         own time as pre-step or post-step, which is
                         exactly the mistake this module exists to avoid
                         making elsewhere (#1673 self-review). Carries
                         `step_count`. Never folded into `ok`.
      could-not-read    the `gh` call failed, the output was not JSON, the
                         JSON was not an object, or the job's own
                         `started_at`/`completed_at` were missing or
                         unparseable. Never folded into any state above
                         -- this repository's own defect class
                         (CLAUDE.md), applied to one job read.
    """
    args = ["api", "repos/{0}/actions/jobs/{1}".format(repo, job_id)]
    out, detail = _gh(gh, args, run, timeout=timeout)
    if out is None:
        return {"job_id": job_id, "state": STATE_COULD_NOT_READ, "detail": detail}

    try:
        payload = json.loads(out)
    except ValueError as exc:
        return {
            "job_id": job_id,
            "state": STATE_COULD_NOT_READ,
            "detail": "could not parse `gh api` output: {0}".format(exc),
        }
    if not isinstance(payload, dict):
        return {
            "job_id": job_id,
            "state": STATE_COULD_NOT_READ,
            "detail": "unexpected `gh api` shape (not an object)",
        }

    job_start = _parse_ts(payload.get("started_at"))
    job_end = _parse_ts(payload.get("completed_at"))
    if job_start is None or job_end is None:
        return {
            "job_id": job_id,
            "state": STATE_COULD_NOT_READ,
            "detail": "job started_at/completed_at missing or unparseable",
        }

    total_seconds = (job_end - job_start).total_seconds()

    steps = payload.get("steps")
    steps = (
        [step for step in steps if isinstance(step, dict)]
        if isinstance(steps, list)
        else []
    )

    matches = [step for step in steps if step.get("name") == test_step_name]

    if not matches:
        return {
            "job_id": job_id,
            "state": STATE_NO_MATCHING_STEP,
            "detail": "no step named {0!r} in this job's own step list".format(
                test_step_name
            ),
            "total_seconds": total_seconds,
            "step_names": [step.get("name") for step in steps],
        }

    if len(matches) > 1:
        # Silently taking the first match here would misattribute the
        # LATER matching step's own duration as "post-step" (teardown) --
        # exactly the shape this module exists to tell apart from a real
        # teardown gap. A repeated step name is a real GitHub Actions
        # shape (a composite action reused twice, a workflow that reruns
        # a step under the same name), so this is refused as its own
        # state rather than guessed at (#1673 self-review).
        return {
            "job_id": job_id,
            "state": STATE_AMBIGUOUS_STEP,
            "detail": (
                "{0} steps are named {1!r} in this job's own step list -- "
                "picking one would silently misattribute another "
                "matching step's own time as pre-step or post-step"
            ).format(len(matches), test_step_name),
            "total_seconds": total_seconds,
            "step_count": len(matches),
        }

    target = matches[0]

    step_start = _parse_ts(target.get("started_at"))
    if step_start is None:
        return {
            "job_id": job_id,
            "state": STATE_COULD_NOT_READ,
            "detail": "matched step {0!r} has no started_at".format(test_step_name),
        }

    step_end = _parse_ts(target.get("completed_at"))
    pre_step_seconds = (step_start - job_start).total_seconds()
    if step_end is not None:
        step_seconds = (step_end - step_start).total_seconds()
        post_step_seconds = (job_end - step_end).total_seconds()
        step_seconds_approximate = False
    else:
        # The step never recorded its own completion -- approximate using
        # the job's own end rather than reporting step_seconds=0, which
        # would read as "the step finished instantly" (this repository's
        # own absence-as-signal defect class, applied to a duration).
        step_seconds = (job_end - step_start).total_seconds()
        post_step_seconds = 0.0
        step_seconds_approximate = True

    return {
        "job_id": job_id,
        "state": STATE_OK,
        "test_step_name": test_step_name,
        "step_conclusion": target.get("conclusion"),
        "total_seconds": total_seconds,
        "pre_step_seconds": pre_step_seconds,
        "step_seconds": step_seconds,
        "step_seconds_approximate": step_seconds_approximate,
        "post_step_seconds": post_step_seconds,
    }


def _render(entry):
    if entry["state"] == STATE_COULD_NOT_READ:
        return "COULD-NOT-READ | job: {0} | {1}".format(
            entry["job_id"], _flatten(entry.get("detail", "unknown"))
        )
    if entry["state"] == STATE_NO_MATCHING_STEP:
        return "NO-MATCHING-STEP | job: {0} | {1} | steps present: {2}".format(
            entry["job_id"],
            _flatten(entry.get("detail", "unknown")),
            ", ".join(_flatten(name) for name in entry.get("step_names", []))
            or "(none)",
        )
    if entry["state"] == STATE_AMBIGUOUS_STEP:
        return "AMBIGUOUS-STEP | job: {0} | {1}".format(
            entry["job_id"], _flatten(entry.get("detail", "unknown"))
        )
    approx = (
        " (approximate -- step never recorded its own completed_at)"
        if entry["step_seconds_approximate"]
        else ""
    )
    return (
        "OK | job: {0} | total: {1:.1f}s | pre-step: {2:.1f}s | "
        "step ({3}): {4:.1f}s{5} | post-step: {6:.1f}s | conclusion: {7}"
    ).format(
        entry["job_id"],
        entry["total_seconds"],
        entry["pre_step_seconds"],
        entry["test_step_name"],
        entry["step_seconds"],
        approx,
        entry["post_step_seconds"],
        entry.get("step_conclusion"),
    )


def main(argv=None, run=None):
    run = subprocess.run if run is None else run
    parser = argparse.ArgumentParser(
        description=(
            "Split one CI job's own wall clock into pre-step / step / "
            "post-step seconds, from GitHub's own per-step timestamps. "
            "ok=0 no-matching-step=1 could-not-read=3 ambiguous-step=4 "
            "(2 is reserved for a usage error). With --baseline-job, the "
            "exit code is the WORSE of the job's own and the baseline's "
            "own state, so a caller checking only the exit code still "
            "sees a failed baseline read."
        )
    )
    parser.add_argument("--job", required=True, help="the job id")
    parser.add_argument("--repo", required=True, help="OWNER/NAME")
    parser.add_argument(
        "--baseline-job",
        default=None,
        help="a second job id (e.g. a known-green run of the same leg) to compare against",
    )
    parser.add_argument(
        "--test-step-name",
        default=DEFAULT_TEST_STEP_NAME,
        help='the step name to split on (default: "{0}")'.format(
            DEFAULT_TEST_STEP_NAME
        ),
    )
    parser.add_argument(
        "--gh", default=None, help="the gh executable (default: the one on PATH)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="also emit the entry (entries, with --baseline-job) as JSON on stdout",
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    gh = args.gh or gh_which.safe_which("gh")
    if not gh:
        sys.stdout.write("COULD-NOT-READ | gh is not on PATH\n")
        return EXIT_CODES[STATE_COULD_NOT_READ]

    entry = read_job_timing(
        args.job, gh, run, repo=args.repo, test_step_name=args.test_step_name
    )
    sys.stdout.write(_render(entry) + "\n")

    baseline_entry = None
    if args.baseline_job is not None:
        baseline_entry = read_job_timing(
            args.baseline_job,
            gh,
            run,
            repo=args.repo,
            test_step_name=args.test_step_name,
        )
        sys.stdout.write("baseline: " + _render(baseline_entry) + "\n")
        if entry["state"] == STATE_OK and baseline_entry["state"] == STATE_OK:
            if baseline_entry["step_seconds"] > 0:
                ratio = entry["step_seconds"] / baseline_entry["step_seconds"]
                sys.stdout.write(
                    "step-duration ratio (job / baseline): {0:.2f}x\n".format(ratio)
                )
            else:
                sys.stdout.write(
                    "step-duration ratio: could not compute -- baseline step_seconds is 0\n"
                )

    if args.json:
        payload = {"job": entry}
        if baseline_entry is not None:
            payload["baseline"] = baseline_entry
        sys.stdout.write(json.dumps(payload) + "\n")

    exit_code = EXIT_CODES[entry["state"]]
    if baseline_entry is not None:
        # #1673 self-review: a caller that scripts off the exit code
        # alone must see a failed baseline read too, not only a failed
        # primary read -- folding it into the same int is what the
        # module's own docstring already invites a caller to do.
        exit_code = max(exit_code, EXIT_CODES[baseline_entry["state"]])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
