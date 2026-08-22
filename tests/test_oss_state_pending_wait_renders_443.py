"""`--pending-wait` must not render `could-not-evaluate` the same as nothing pending
(#443).

Found by the release-auditor at gate 3 of the v0.10.0 release, round 2. `check_wait`'s own
docstring says a could-not-evaluate wait "must never render the same as `holds`... `holds`
is a measurement that came back negative, this is no measurement" -- but the CLI reading
route folded it into the `else` branch of `if record["state"] == WAIT_HOLDS`, which is the
same branch `cleared` and `no wait ever recorded` fall into. So a tick that could not test
its own wait proceeded as though nothing was pending, at exit 0, with the recorded `why`
reaching nobody.

The settled reading, argued in the issue and adopted here: `--pending-wait` answers *is
anything pending*, not *is a wait record open*. A `could-not-evaluate` wait is exactly as
unresolved as a `holds` wait -- neither is a negative measurement -- so both belong on the
"something is pending, look at this" side of the answer. That is a reclassification, not a
third output string: `could-not-evaluate` joins `holds` in the record-printing branch, and
the two remain distinguishable because the printed record itself carries a different
`state` (and a `why` `holds` never has), never collapsing into the same bytes. `cleared` and
"no wait ever recorded" are unaffected -- both are genuine negatives, and that pairing was
never the defect this issue reports.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


DISPATCH = "gate 3 audit dispatched at 23:12Z"
OBSERVABLE = "four output issues filed on the tracker"
RECORDED_AT = "2026-08-16T23:12:00Z"
WHY = "the tracker API returned a 503 for the whole check window"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _record_and_read(tmp_path, check_wait=None, cleared_by=None, why=None):
    """Record a fresh wait, optionally re-derive it once, then read `--pending-wait`
    back. Returns the CLI's stdout for the final `--pending-wait` call.
    """
    path = tmp_path / "state.json"
    _piped(
        [
            str(path),
            "--decision", "blocked on gate 3 audit",
            "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
            "--wait-observable", OBSERVABLE,
        ]
    )
    if check_wait is not None:
        argv = [
            str(path),
            "--decision", "re-derived",
            "--at", "2026-08-17T01:15:00Z",
            "--check-wait", check_wait,
        ]
        if cleared_by is not None:
            argv += ["--wait-cleared-by", cleared_by]
        if why is not None:
            argv += ["--wait-why", why]
        result = _piped(argv)
        assert result.returncode == 0, result.stdout
    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    return result.stdout


def test_no_wait_ever_recorded_reports_none(tmp_path):
    path = tmp_path / "state.json"
    _piped([str(path), "--decision", "first tick", "--at", "2026-08-16T00:00:00Z"])
    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert "no pending wait" in result.stdout.lower()


def test_holds_prints_the_record(tmp_path):
    stdout = _record_and_read(tmp_path)
    assert oss_state.WAIT_HOLDS in stdout
    assert DISPATCH in stdout


def test_cleared_reports_none(tmp_path):
    stdout = _record_and_read(tmp_path, check_wait="cleared", cleared_by="issues filed")
    assert "no pending wait" in stdout.lower()


def test_could_not_evaluate_does_not_report_none(tmp_path):
    """The bug: this used to be byte-identical to `no pending wait`, dropping `why`
    on the floor and reading, to the next tick, as nothing being pending at all.
    """
    stdout = _record_and_read(tmp_path, check_wait="could-not-evaluate", why=WHY)
    assert "no pending wait" not in stdout.lower()


def test_could_not_evaluate_carries_why_and_its_own_state_to_the_reader(tmp_path):
    stdout = _record_and_read(tmp_path, check_wait="could-not-evaluate", why=WHY)
    assert oss_state.WAIT_COULD_NOT_EVALUATE in stdout
    assert WHY in stdout
    assert DISPATCH in stdout


def test_no_two_of_the_four_wait_states_render_alike_except_the_two_true_negatives(
    tmp_path,
):
    """The control this file exists to enforce: drive all four states this reading
    route can meet through it and check every pairing. `cleared` and "no wait ever
    recorded" are both genuine negatives -- nothing is pending either way -- and were
    never the defect #443 reports, so they are allowed, and expected, to render
    identically. Every other pairing must differ, and in particular
    `could-not-evaluate` must not collapse into either negative: it is no measurement
    at all, not one that came back clean.
    """
    never_recorded_dir = tmp_path / "never"
    never_recorded_dir.mkdir()
    never_recorded = never_recorded_dir / "never.json"
    _piped([str(never_recorded), "--decision", "first tick", "--at", "2026-08-16T00:00:00Z"])

    holds_dir = tmp_path / "holds"
    holds_dir.mkdir()
    cleared_dir = tmp_path / "cleared"
    cleared_dir.mkdir()
    cne_dir = tmp_path / "cne"
    cne_dir.mkdir()

    outputs = {
        "no wait ever recorded": _piped(
            [str(never_recorded), "--pending-wait"]
        ).stdout,
        "holds": _record_and_read(holds_dir),
        "cleared": _record_and_read(
            cleared_dir, check_wait="cleared", cleared_by="issues filed"
        ),
        "could-not-evaluate": _record_and_read(
            cne_dir, check_wait="could-not-evaluate", why=WHY
        ),
    }
    # Positive control: `holds` still prints the record, so this test cannot pass by
    # making every state distinct-but-useless (e.g. all four raising, or all four
    # printing their own state name and nothing else).
    assert oss_state.WAIT_HOLDS in outputs["holds"]
    assert DISPATCH in outputs["holds"]

    allowed_alike = {frozenset({"no wait ever recorded", "cleared"})}
    seen = {}
    for label, stdout in outputs.items():
        normalized = stdout.strip()
        if normalized in seen:
            other = seen[normalized]
            pair = frozenset({label, other})
            assert pair in allowed_alike, (
                "{!r} and {!r} both rendered as {!r} -- must not render alike".format(
                    label, other, normalized
                )
            )
        else:
            seen[normalized] = label


def test_could_not_evaluate_does_not_render_the_same_as_holds(tmp_path):
    """`check_wait`'s own docstring: could-not-evaluate "must never render the same as
    `holds`... `holds` is a measurement that came back negative, this is no
    measurement." Both land in the record-printing branch (#443), so this asserts the
    printed record itself still differs rather than trusting the branch alone.
    """
    holds_dir = tmp_path / "holds"
    holds_dir.mkdir()
    cne_dir = tmp_path / "cne"
    cne_dir.mkdir()
    holds_stdout = _record_and_read(holds_dir)
    cne_stdout = _record_and_read(
        cne_dir, check_wait="could-not-evaluate", why=WHY
    )
    assert holds_stdout.strip() != cne_stdout.strip()
