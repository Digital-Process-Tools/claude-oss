#!/usr/bin/env python3
"""Report a hot test's share of the suite before somebody notices it by hand -- #910.

`pyproject.toml`'s `addopts` already carries `--durations=25` (#881 step 1), so
every pytest invocation -- CI's or a contributor's -- prints the top 25 slowest
tests as a plain-text tail. Nothing reads that tail. `tests/test_shell_probe.py
::test_a_broken_shell_earlier_on_path_does_not_turn_the_suites_red` measured
43.92s against ~6.5s next-slowest on one CI leg -- roughly a fifth of that
leg's whole runtime -- and it was found only because a maintainer happened to
scroll to the tail of a log by hand.

## Why this reads pytest's resolved stats, not the `--durations` text

A CI-side step that greps the printed `--durations` summary was considered and
rejected: it would have to reparse pytest's own formatting (`"9.00s call ..."`,
subject to change across pytest releases -- this repo alone jumped from an
unpinned floor to 9.1.1 mid-project), it only runs where the CI step is wired,
and a maintainer's own local partial run -- exactly the shape that found the
#908 incident by luck rather than by tooling -- gets nothing. This module is
instead registered as a pytest plugin (`tests/duration_report_plugin.py`,
loaded via `tests/conftest.py`'s existing `pytest_plugins` list, the same
mechanism `must_assert_plugin` already uses for #430) and reads
`terminalreporter.stats` directly -- pytest's own resolved per-test-report
data structure, not a string it prints from that data. It therefore runs on
every invocation of the suite, everywhere pytest runs, with zero CI wiring,
and cannot be broken by a cosmetic change to `--durations`'s own text.

## The three states, and why the third is not optional

  MEASURED           durations were collected this session AND a baseline
                      file was loaded, so the current slowest share is
                      reported next to what it was last recorded at.
  NO_BASELINE         durations were collected, but no baseline file exists
                      (first run) or the one on disk could not be read -- the
                      number is still reported, compared to nothing, and that
                      absence is said out loud rather than rendered as
                      "unchanged" (which is what a silent default would look
                      like next to a real MEASURED report).
  COULD_NOT_MEASURE   no call-phase test report carried a duration at all --
                      a `--collect-only` invocation, an empty test selection,
                      or a `terminalreporter.stats` shape this module does not
                      recognise. This is the state the issue's own acceptance
                      criteria calls out by name: "a step that silently emits
                      nothing when it cannot parse the log is indistinguishable
                      from a suite with no hot test," which is this whole
                      project's own defect class reappearing inside the one
                      detector built to catch it. It outranks the other two --
                      a baseline file merely existing on disk must never turn
                      a session that measured nothing into MEASURED or
                      NO_BASELINE, both of which would print exactly like a
                      real comparison.

## What this deliberately does not do

Per the issue's own "What NOT to add" section: nothing here fails a build, a
leg, or a session on a duration share or a wall-clock number. Every function
below only computes and formats; `tests/duration_report_plugin.py` only
prints. A shared CI runner's load is not in anybody's diff, and a gate that
reddens a pull request for a neighbour's noisy build teaches people to re-run
until green -- the issue's own reasoning, transcribed rather than
re-derived, because it is the one design decision this module must not
quietly relitigate later.

## The baseline file

`tests/duration-baseline.json`, tracked in git like any other test fixture --
this repository has no existing "per-repo local state" convention that fits a
recorded number meant to be compared across commits and reviewed in a diff
(`.oss.json`/`.oss.local.json` are the plugin's own per-repo config, a
different kind of fact entirely, and `.oss/` itself is scaffolded and
replaced wholesale on every run per `CLAUDE.md`'s ownership contracts, which
disqualifies it as a place a human hand-edits). A JSON object, not a
plain number, so a future field (a per-test history, a recorded run date)
does not have to invent a second file format. Updated with
`pytest --record-duration-baseline` (`tests/duration_report_plugin.py`'s own
option), a decision a human makes deliberately, matching the issue's own "the
decision stays with whoever reads it" framing -- nothing here writes the
baseline on an ordinary run.
"""

import json
from pathlib import Path

DEFAULT_TOP_N = 25

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_PATH = REPO_ROOT / "tests" / "duration-baseline.json"

MEASURED = "measured"
NO_BASELINE = "no-baseline"
COULD_NOT_MEASURE = "could-not-measure"

_REQUIRED_BASELINE_KEYS = ("slowest_share", "slowest_nodeid", "total_seconds")


def collect_durations(terminalreporter):
    """`[(nodeid, seconds), ...]`, longest first, one entry per test that
    actually ran its body this session.

    Read from `terminalreporter.stats` -- pytest's own resolved per-report
    data, keyed by outcome ("passed", "failed", "error", ...) -- rather than
    from the `--durations` text pytest prints from that same data, so a
    cosmetic change to that text can never make this silently see nothing.
    Only `when == "call"` reports carry the test body's own duration; `setup`
    and `teardown` measure fixture cost, not the test, and are excluded so a
    test with an expensive fixture and a trivial body is not reported as slow
    itself.
    """
    durations = []
    for reports in terminalreporter.stats.values():
        for report in reports:
            if getattr(report, "when", None) != "call":
                continue
            duration = getattr(report, "duration", None)
            if duration is None:
                continue
            durations.append((report.nodeid, duration))
    durations.sort(key=lambda pair: pair[1], reverse=True)
    return durations


def compute_shape(durations, top_n=DEFAULT_TOP_N):
    """`None` if nothing was measured (empty input, or every duration is
    zero -- indistinguishable from "nothing ran" and cannot support a share
    without dividing by zero); otherwise a dict naming the total, the top
    `top_n` entries, and the slowest single test's share of the whole.

    Returning `None` rather than a shape claiming a 0% share is deliberate:
    a 0% share prints identically to a genuinely healthy suite, which is
    exactly the silent-absence failure the issue's third state exists to
    keep out of this function's own return value, not just out of its
    caller's prose.
    """
    if not durations:
        return None
    total = sum(seconds for _, seconds in durations)
    if total <= 0:
        return None
    slowest_nodeid, slowest_seconds = durations[0]
    return {
        "total_seconds": total,
        "count": len(durations),
        "top": durations[:top_n],
        "slowest_nodeid": slowest_nodeid,
        "slowest_seconds": slowest_seconds,
        "slowest_share": slowest_seconds / total,
    }


def load_baseline(path):
    """`(baseline_dict, None)` on success, `(None, reason)` otherwise.

    `reason == "absent"` is the honest first-run/never-recorded state and is
    told apart from every other failure on purpose: a baseline file that
    exists but will not parse, or is missing the keys this module writes, is
    a real finding (something else wrote or truncated it) and must not be
    folded into the same "absent" answer a first run gives, or the NO_BASELINE
    report would say "first run" about a file that is actually broken.
    """
    # `Path.exists()` is not itself exception-free: it swallows some OSError
    # subclasses and re-raises others, and which is which has differed by
    # CPython version on this repository's own CI matrix (3.9-3.12) --
    # `scripts/release_delta.py` and `scripts/doctor_check_worktree_reap_
    # permission.py` both had to wrap this identical call for the same
    # reason (reviewer finding, #910). An OSError here is exactly as real a
    # "could not look" as one from read_text below, so it lands in the same
    # "unreadable" bucket rather than propagating out of this function and,
    # from there, out of the pytest_terminal_summary hook itself.
    try:
        found = path.exists()
    except OSError as exc:
        return None, "unreadable: {}".format(exc)
    if not found:
        return None, "absent"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, "unreadable: {}".format(exc)
    if not isinstance(payload, dict):
        return None, "malformed: not a JSON object"
    missing = [key for key in _REQUIRED_BASELINE_KEYS if key not in payload]
    if missing:
        return None, "malformed: missing key(s) {}".format(", ".join(missing))
    return payload, None


def write_baseline(path, shape):
    """Write `shape` (from `compute_shape`) as the new baseline at `path`,
    and return the payload written. A deliberate act -- `--record-duration-
    baseline`, never an ordinary run -- matching the issue's "measure,
    report, and stop; the decision stays with whoever reads it" framing.
    """
    payload = {
        "total_seconds": round(shape["total_seconds"], 3),
        "slowest_nodeid": shape["slowest_nodeid"],
        "slowest_seconds": round(shape["slowest_seconds"], 3),
        "slowest_share": round(shape["slowest_share"], 6),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def report_state(shape, baseline, baseline_error):
    """Which of the three states (module-level docstring) this run is in.

    `shape is None` (nothing measured) outranks everything else -- checked
    first, unconditionally -- so a baseline file merely existing on disk can
    never turn a session that measured nothing into MEASURED or NO_BASELINE.
    """
    if shape is None:
        return COULD_NOT_MEASURE
    if baseline is None:
        return NO_BASELINE
    return MEASURED


def format_report(shape, baseline, baseline_error, state, top_n=DEFAULT_TOP_N):
    """The full report, as a list of lines, for either terminal output or a
    test assertion -- one function, so the two can never drift apart.

    The first line always names `state` by its literal value
    (`measured`/`no-baseline`/`could-not-measure`), satisfying the issue's
    acceptance criterion that the three states be "distinguishable in the
    output" without a reader having to infer which one applied from the
    shape of the rest of the text.
    """
    if state == COULD_NOT_MEASURE:
        return [
            "test-durations: {} -- no call-phase test durations were collected "
            "this session (a --collect-only run, an empty selection, or an "
            "unrecognised report shape); a hot test cannot be reported when "
            "nothing was measured".format(COULD_NOT_MEASURE),
        ]

    lines = [
        "test-durations: {} -- top {} of {} test(s) measured".format(
            state, min(top_n, shape["count"]), shape["count"]
        )
    ]
    for nodeid, seconds in shape["top"][:top_n]:
        lines.append("  {:>9.2f}s  {}".format(seconds, nodeid))
    lines.append(
        "slowest test: {} -- {:.2f}s, {:.1%} of {:.2f}s total".format(
            shape["slowest_nodeid"], shape["slowest_seconds"], shape["slowest_share"], shape["total_seconds"]
        )
    )
    if state == NO_BASELINE:
        lines.append(
            "baseline: {} ({}) -- nothing recorded to compare against; "
            "run with --record-duration-baseline to record one".format(NO_BASELINE, baseline_error)
        )
    else:
        delta = shape["slowest_share"] - baseline["slowest_share"]
        lines.append(
            "baseline: slowest share {:+.1%} vs recorded {:.1%} for {}".format(
                delta, baseline["slowest_share"], baseline["slowest_nodeid"]
            )
        )
    return lines
