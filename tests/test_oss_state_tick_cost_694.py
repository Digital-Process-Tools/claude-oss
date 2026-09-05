"""What a tick costs to *carry* -- start context, floor, inherited, calls, context
carried, and cost as a derived column only (#694).

A tick's own dollar cost points at the wrong ticks: ranking 48 ticks by dollars said
twelve were expensive, and the real story was that context inherited from earlier ticks
in the same session -- not the work done -- explained the twelve. This is the
before-reading `scripts/oss_state.py` records so a later optimisation can be graded
against a measurement instead of an argument.

Same discipline as `intake` and `lane_models`: every "must read unknown" case is paired
with a "must read a real number, including zero" case in the same fixture. A broken
counter that reports zero must never render like a perfectly efficient tick, and a
session whose first tick was never observed must never render like one that inherited
nothing.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

WINDOW = "this tick"
SESSION = "9cab99a6"
STAMP = "2026-08-28T09:00:00Z"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------------------- the pure metric


def test_a_first_tick_own_start_ctx_is_its_own_floor():
    """#694: 'floor -- the session's own first-tick start'. Nothing to propagate yet,
    so the first tick's own reading defines it, and inherited is 0 -- not unknown."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=96000,
        calls=12,
        context_carried=180000,
        is_first=True,
    )
    assert record["state"] == oss_state.TICK_COST_MEASURED
    assert record["floor"] == 96000
    assert record["inherited"] == 0
    assert record["start_ctx"] == 96000
    assert record["calls"] == 12
    assert record["context_carried"] == 180000


def test_a_later_tick_derives_inherited_from_the_propagated_floor():
    """Tick 12 of session 9cab99a6 in #694's own table: start 411k against a floor of
    49k (tick 1's own start) inherits 362k -- the recoverable part, per the issue."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=411000,
        calls=9,
        context_carried=2_000_000,
        is_first=False,
        prior_floor=49000,
    )
    assert record["state"] == oss_state.TICK_COST_MEASURED
    assert record["floor"] == 49000
    assert record["inherited"] == 411000 - 49000


def test_a_non_first_tick_with_no_known_floor_is_floor_unknown_not_zero_and_not_start_ctx():
    """#694: 'a session whose first tick was not observed ... has an unknown floor, and
    inherited is then unknown rather than start_ctx'. The raw reading is still kept --
    this is not the could-not-measure state, which is paired below."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=345000,
        calls=6,
        context_carried=2_100_000,
        is_first=False,
        prior_floor=None,
    )
    assert record["state"] == oss_state.TICK_COST_FLOOR_UNKNOWN
    assert record["floor"] is None
    assert record["inherited"] is None
    # The numbers this tick DID measure are not discarded because the floor is unknown.
    assert record["start_ctx"] == 345000
    assert record["calls"] == 6
    assert record["context_carried"] == 2_100_000
    assert record["why"]


def test_could_not_measure_needs_a_why():
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.tick_cost(
            SESSION, WINDOW, start_ctx=None, calls=6, context_carried=100
        )
    assert "why" in str(caught.value)


def test_a_tick_that_cannot_read_its_own_context_is_unknown_not_zero():
    """The founding defect class, pointed at the instrument built to measure it: a
    broken counter reporting zero must not render like an efficient tick."""
    broken = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=None,
        calls=None,
        context_carried=None,
        why="the harness gave no usage block this turn",
    )
    assert broken["state"] == oss_state.TICK_COST_COULD_NOT_MEASURE
    assert broken["start_ctx"] is None
    assert broken["floor"] is None
    assert broken["inherited"] is None
    assert "harness" in broken["why"]


def test_zero_calls_and_zero_context_carried_is_a_real_measurement_not_could_not_measure():
    """The positive control for the pair above: a tick that genuinely did nothing is a
    finding worth reading, and it must not collapse into 'could not measure'."""
    idle = oss_state.tick_cost(
        SESSION, WINDOW, start_ctx=96000, calls=0, context_carried=0, is_first=True
    )
    assert idle["state"] == oss_state.TICK_COST_MEASURED
    assert idle["calls"] == 0
    assert idle["context_carried"] == 0
    assert idle["inherited"] == 0


def test_a_partial_reading_still_reports_the_pieces_that_were_taken():
    """calls and context_carried known, start_ctx unknown -- the missing piece makes
    the state could-not-measure, but the two pieces genuinely read are not discarded,
    the same way `intake`'s no-denominator state still reports the numerator."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=None,
        calls=5,
        context_carried=100000,
        why="usage block truncated",
    )
    assert record["state"] == oss_state.TICK_COST_COULD_NOT_MEASURE
    assert record["start_ctx"] is None
    assert record["calls"] == 5
    assert record["context_carried"] == 100000
    # No floor and no inherited can be derived from a reading that is missing a piece.
    assert record["floor"] is None
    assert record["inherited"] is None


def test_first_tick_asserted_against_a_session_that_already_has_a_floor_is_refused():
    """A `--tick-cost-first` claim that contradicts recorded history names a session id
    reuse rather than silently overwriting the earlier floor with a later, larger one."""
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.tick_cost(
            SESSION,
            WINDOW,
            start_ctx=500000,
            calls=1,
            context_carried=10,
            is_first=True,
            prior_floor=49000,
        )
    assert SESSION in str(caught.value)


def test_first_tick_asserted_against_a_session_with_only_floor_unknown_history_is_refused():
    """Found by the auditor: a session whose earlier ticks never resolved a floor
    (every one recorded floor-unknown) has no `prior_floor` to conflict against, but it
    unambiguously already has history -- `session_has_prior` carries that fact
    separately from `prior_floor`, and `is_first` must be refused against it too, not
    only against an already-resolved floor."""
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.tick_cost(
            SESSION,
            WINDOW,
            start_ctx=411000,
            calls=9,
            context_carried=2000000,
            is_first=True,
            prior_floor=None,
            session_has_prior=True,
        )
    assert SESSION in str(caught.value)


def test_first_tick_conflict_fires_even_when_this_readings_own_counts_are_unknown():
    """Found by review: the is_first/prior conflict used to sit below the
    could-not-measure early return, so an unknown reading skipped the check entirely --
    the session-reuse claim is about which TICK this is, not about whether this tick's
    own counts could be read, so it must fire regardless."""
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.tick_cost(
            SESSION,
            WINDOW,
            start_ctx=None,
            calls=None,
            context_carried=None,
            is_first=True,
            prior_floor=49000,
            why="no usage block this turn",
        )
    assert SESSION in str(caught.value)


def test_no_session_history_and_is_first_true_is_accepted():
    """The positive control for both refusals above: a genuinely first tick, with
    nothing recorded for this session yet, is accepted."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=96000,
        calls=1,
        context_carried=1000,
        is_first=True,
        prior_floor=None,
        session_has_prior=False,
    )
    assert record["state"] == oss_state.TICK_COST_MEASURED
    assert record["floor"] == 96000


def test_the_window_is_required():
    with pytest.raises(oss_state.StateError):
        oss_state.tick_cost(SESSION, "", start_ctx=1, calls=1, context_carried=1)


def test_the_session_is_required():
    """Without a session id, no later tick's floor lookup could ever find this one."""
    with pytest.raises(oss_state.StateError):
        oss_state.tick_cost("", WINDOW, start_ctx=1, calls=1, context_carried=1)


# ------------------------------------------------------------------------ cost, derived


def test_no_rate_means_no_cost_is_claimed():
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=96000,
        calls=1,
        context_carried=2_000_000,
        is_first=True,
    )
    assert record["cost"] is None


def test_a_rate_produces_a_cost_labelled_list_rate_not_a_bill():
    """#694: 'Any cost column must say so where it renders, or it will be quoted as a
    bill.' The disclaimer travels inside the record, not only in a renderer somebody
    might skip."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=96000,
        calls=1,
        context_carried=2_000_000,
        is_first=True,
        rate=1.5,
    )
    assert record["cost"]["list_rate_usd"] == pytest.approx(3.0)
    assert "list-rate" in record["cost"]["note"]
    assert "bill" in record["cost"]["note"]


def test_cost_is_computed_even_when_the_floor_is_unknown():
    """Cost is derived from context_carried, not from inherited -- a tick whose floor
    could not be established still measured what it carried."""
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=345000,
        calls=6,
        context_carried=2_100_000,
        is_first=False,
        prior_floor=None,
        rate=1.5,
    )
    assert record["state"] == oss_state.TICK_COST_FLOOR_UNKNOWN
    assert record["cost"]["list_rate_usd"] == pytest.approx(3.15)


def test_cost_is_never_claimed_when_the_reading_itself_could_not_be_taken():
    record = oss_state.tick_cost(
        SESSION,
        WINDOW,
        start_ctx=None,
        calls=None,
        context_carried=None,
        why="no usage block",
        rate=1.5,
    )
    assert record["cost"] is None


# ------------------------------------------------------------------------------ the line


def test_the_could_not_measure_line_never_says_zero():
    line = oss_state.tick_cost_line(
        oss_state.tick_cost(
            SESSION,
            WINDOW,
            start_ctx=None,
            calls=None,
            context_carried=None,
            why="no usage block this turn",
        )
    )
    assert "could not measure" in line
    assert "not zero" in line


def test_the_floor_unknown_line_never_claims_an_inherited_number():
    line = oss_state.tick_cost_line(
        oss_state.tick_cost(
            SESSION,
            WINDOW,
            start_ctx=345000,
            calls=6,
            context_carried=2_100_000,
            is_first=False,
            prior_floor=None,
        )
    )
    assert "floor unknown" in line or "unknown" in line
    assert "345000" in line


def test_the_measured_line_shows_floor_plus_inherited():
    line = oss_state.tick_cost_line(
        oss_state.tick_cost(
            SESSION,
            WINDOW,
            start_ctx=411000,
            calls=9,
            context_carried=2_000_000,
            is_first=False,
            prior_floor=49000,
        )
    )
    assert "49000" in line
    assert str(411000 - 49000) in line


# -------------------------------------------------------------------------------- the CLI


TICK_COST_ARGV = [
    "--at",
    STAMP,
    "--tick-cost-session",
    SESSION,
    "--tick-cost-window",
    WINDOW,
    "--tick-cost-start-ctx",
    "96000",
    "--tick-cost-calls",
    "5",
    "--tick-cost-context-carried",
    "180000",
    "--tick-cost-first",
]


def _lines_starting(text, prefix):
    return [line for line in text.splitlines() if line.startswith(prefix)]


def test_cli_records_a_first_tick_and_reads_it_back(tmp_path):
    path = tmp_path / "state.json"
    result = _piped([str(path), "--decision", "tick 1"] + TICK_COST_ARGV)
    assert result.returncode == 0, result.stdout
    assert _lines_starting(result.stdout, "RECORDED")

    entries = oss_state.read(path)
    assert len(entries) == 1
    tick_cost = entries[0]["detail"]["tick_cost"]
    assert tick_cost["state"] == oss_state.TICK_COST_MEASURED
    assert tick_cost["floor"] == 96000
    assert tick_cost["inherited"] == 0


def test_cli_propagates_the_floor_to_a_later_tick_in_the_same_session(tmp_path):
    path = tmp_path / "state.json"
    _piped([str(path), "--decision", "tick 1"] + TICK_COST_ARGV)

    later_argv = [
        "--at",
        "2026-08-28T18:00:00Z",
        "--tick-cost-session",
        SESSION,
        "--tick-cost-window",
        WINDOW,
        "--tick-cost-start-ctx",
        "411000",
        "--tick-cost-calls",
        "9",
        "--tick-cost-context-carried",
        "2000000",
    ]
    result = _piped([str(path), "--decision", "tick 12"] + later_argv)
    assert result.returncode == 0, result.stdout

    entries = oss_state.read(path)
    later = entries[-1]["detail"]["tick_cost"]
    assert later["state"] == oss_state.TICK_COST_MEASURED
    assert later["floor"] == 96000
    assert later["inherited"] == 411000 - 96000


def test_cli_a_different_sessions_tick_never_sees_this_sessions_floor(tmp_path):
    """The control on propagation: a genuinely different session's first tick must not
    inherit a floor recorded under a different session id."""
    path = tmp_path / "state.json"
    _piped([str(path), "--decision", "tick 1, session A"] + TICK_COST_ARGV)

    other_session_argv = [
        "--at",
        "2026-08-29T09:00:00Z",
        "--tick-cost-session",
        "a-different-session",
        "--tick-cost-window",
        WINDOW,
        "--tick-cost-start-ctx",
        "50000",
        "--tick-cost-calls",
        "3",
        "--tick-cost-context-carried",
        "10000",
    ]
    result = _piped([str(path), "--decision", "tick 1, session B"] + other_session_argv)
    assert result.returncode == 0, result.stdout
    entries = oss_state.read(path)
    other = entries[-1]["detail"]["tick_cost"]
    assert other["state"] == oss_state.TICK_COST_FLOOR_UNKNOWN


def test_cli_refuses_tick_cost_flags_in_a_reading_mode(tmp_path):
    path = tmp_path / "state.json"
    result = _piped([str(path), "--read"] + TICK_COST_ARGV[2:])  # drop --at
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "--tick-cost-session" in result.stdout


def test_cli_reports_unknown_via_the_unknown_literal_not_a_guessed_number(tmp_path):
    path = tmp_path / "state.json"
    argv = [
        str(path),
        "--decision",
        "no usage data this turn",
        "--at",
        STAMP,
        "--tick-cost-session",
        SESSION,
        "--tick-cost-window",
        WINDOW,
        "--tick-cost-start-ctx",
        "unknown",
        "--tick-cost-calls",
        "unknown",
        "--tick-cost-context-carried",
        "unknown",
        "--tick-cost-why",
        "the transcript truncated before a usage block appeared",
    ]
    result = _piped(argv)
    assert result.returncode == 0, result.stdout
    entry = oss_state.read(path)[0]
    tick_cost = entry["detail"]["tick_cost"]
    assert tick_cost["state"] == oss_state.TICK_COST_COULD_NOT_MEASURE
    assert tick_cost["start_ctx"] is None


def test_a_refused_decision_drops_nothing_silently(tmp_path):
    """Same ordering guarantee as intake/lanes/cohort/wait (#222): a refusal after a
    tick-cost record was built still names what it did not record."""
    path = tmp_path / "state.json"
    long_decision = "x" * (oss_state.MAX_DECISION + 1)
    result = _piped(
        [str(path), "--decision", long_decision, "--at", STAMP] + TICK_COST_ARGV
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "NOT RECORDED" in result.stdout
    assert not path.exists()


def test_cli_a_complete_tick_cost_set_is_not_dropped_by_an_unrelated_intake_refusal(
    tmp_path,
):
    """Found by review: a fully valid `--tick-cost-*` set used to be built LAST among
    the pending records, so an unrelated group's refusal (an incomplete intake set,
    here) short-circuited the function before tick_cost's own block ever ran -- the
    measured record vanished with no `NOT RECORDED` line at all, the exact #222 shape
    the file's own comment says every pending record is protected against."""
    path = tmp_path / "state.json"
    argv = [
        str(path),
        "--decision",
        "tick x",
        "--at",
        STAMP,
        "--filings",
        "5",  # incomplete: no --merged-prs/--window -> refused
    ] + TICK_COST_ARGV
    result = _piped(argv)
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "NOT RECORDED tick cost" in result.stdout, result.stdout
    assert not path.exists()


def test_cli_a_resumed_session_falsely_claiming_first_tick_is_refused(tmp_path):
    """Found by the auditor: a session whose only prior tick recorded floor-unknown
    (never resolved a floor) must still refuse a later, falsely-first-claiming tick --
    the session unambiguously already has history, resolved floor or not."""
    path = tmp_path / "state.json"
    first_argv = [
        str(path),
        "--decision",
        "tick 1",
        "--at",
        STAMP,
        "--tick-cost-session",
        SESSION,
        "--tick-cost-window",
        WINDOW,
        "--tick-cost-start-ctx",
        "50000",
        "--tick-cost-calls",
        "3",
        "--tick-cost-context-carried",
        "1000",
    ]
    first = _piped(first_argv)
    assert first.returncode == 0, first.stdout
    assert (
        oss_state.read(path)[0]["detail"]["tick_cost"]["state"]
        == oss_state.TICK_COST_FLOOR_UNKNOWN
    )

    bogus_first_argv = [
        str(path),
        "--decision",
        "tick 2 bogus first",
        "--at",
        "2026-08-28T10:00:00Z",
        "--tick-cost-session",
        SESSION,
        "--tick-cost-window",
        WINDOW,
        "--tick-cost-start-ctx",
        "411000",
        "--tick-cost-calls",
        "9",
        "--tick-cost-context-carried",
        "2000000",
        "--tick-cost-first",
    ]
    second = _piped(bogus_first_argv)
    assert second.returncode == 1, second.stdout
    assert "FAIL" in second.stdout
    assert len(oss_state.read(path)) == 1, "the bogus first-tick claim must not land"


def test_the_first_tick_conflict_control_fires_on_an_exact_session_repeat(tmp_path):
    """Control for the whitespace case below: an exact repeat of the same session id
    must already be refused, unconditionally on any stripping. If this ever stops
    firing, the whitespace test below would prove nothing about the fix."""
    path = tmp_path / "state.json"
    first = _piped([str(path), "--decision", "tick 1", "--at", STAMP] + TICK_COST_ARGV)
    assert first.returncode == 0, first.stdout

    control = _piped(
        [str(path), "--decision", "control", "--at", "2026-08-28T10:00:00Z"]
        + TICK_COST_ARGV
    )
    assert control.returncode == 1, control.stdout
    assert "FAIL" in control.stdout
    assert "asserted as session" in control.stdout
    assert len(oss_state.read(path)) == 1


def test_a_session_id_differing_only_by_surrounding_whitespace_is_still_refused(
    tmp_path,
):
    """Found by audit (#805): `tick_cost` strips ``session`` before writing a record
    (around line 776), but `_session_tick_cost_floor` used to compare against the
    caller's RAW, unstripped ``--tick-cost-session`` value when looking up prior
    history -- so a session id differing only in surrounding whitespace found no
    matching history, and a resumed session (or a copy-pasted `--tick-cost-first`)
    could manufacture a false floor a second time with the refusal above silently
    not firing. Session ids here are deliberately NOT identical strings -- 's1' vs
    ' s1' -- and the refusal must fire on both."""
    path = tmp_path / "state.json"
    base = [
        "--tick-cost-window",
        WINDOW,
        "--tick-cost-start-ctx",
        "50000",
        "--tick-cost-calls",
        "1",
        "--tick-cost-context-carried",
        "0",
    ]
    first = _piped(
        [
            str(path),
            "--decision",
            "tick 1",
            "--at",
            STAMP,
            "--tick-cost-session",
            "s1",
            "--tick-cost-first",
        ]
        + base
    )
    assert first.returncode == 0, first.stdout

    finding = _piped(
        [
            str(path),
            "--decision",
            "whitespace-padded resume",
            "--at",
            "2026-08-28T11:00:00Z",
            "--tick-cost-session",
            " s1",
            "--tick-cost-first",
        ]
        + base
    )
    assert finding.returncode == 1, finding.stdout
    assert "FAIL" in finding.stdout
    assert "asserted as session" in finding.stdout
    assert len(oss_state.read(path)) == 1, (
        "a whitespace-padded session id must not be treated as a new session"
    )
