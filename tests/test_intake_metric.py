"""Filings per merged pull request: the intake metric, and the state that is not zero (#137).

The board's growth is a number or it is a feeling. ``oss_state.intake`` computes the
number from two counts the caller took; ``oss_state.intake_trend`` sums the recorded
pairs across a run of ticks. Both live beside the state file because that is where a
per-tick number belongs, and both take their counts as **arguments** -- for exactly the
reason ``append`` takes its timestamp as one. A function that reaches out to the forge
cannot be tested for what it writes, and this file is evidence.

Three things this file holds, each with both arms in the same fixture:

* **A ratio of 0 filings over 3 merged pull requests is a finding.** A ratio that could
  not be computed is not a finding at all, and it must never render as 0.
* **Zero merged pull requests is not a denominator.** 3/0 is not 3 and it is not 0; it
  is ``no-denominator``, and the numerator is still worth reporting.
* **The window travels with the number.** A ratio whose denominator nobody wrote down
  means nothing, so ``window`` is required rather than defaulted -- a default would be
  one repository's counting rule living in shared code, one indirection away.

The pair is stored, never the quotient. A metric nobody can recompute is a claim, and a
history of quotients cannot be re-added: 1/2 and 3/4 do not average to the ratio over
six pull requests. ``intake_trend`` re-adds the numerators and denominators, which is
only possible because both were kept.

**No threshold is asserted anywhere, deliberately.** One day of one repository measured
roughly 0.6 filings per merged pull request; an upstream project measured roughly 3.
Which of those is right -- or whether the two ends count a "filing" the same way at all
-- is not knowable from either number. A target read off a single sample would be the
hardcoded repository fact this codebase forbids, wearing a decimal point.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

WINDOW = "since the last tick"
STAMP = "2026-08-15T09:00:00Z"


# --------------------------------------------------------------------------- the states


def test_a_measured_tick_keeps_both_counts_and_the_window():
    """The quotient is derived. The pair is what is stored, so it can be re-added."""
    record = oss_state.intake(6, 11, window=WINDOW)
    assert record["state"] == oss_state.INTAKE_MEASURED
    assert record["filings"] == 6
    assert record["merged_prs"] == 11
    assert record["window"] == WINDOW
    assert record["ratio"] == pytest.approx(0.545, abs=0.001)


def test_zero_filings_is_measured_and_uncounted_filings_is_not():
    """Both arms in one fixture: the whole point of the third state is this pair.

    A loop that filed nothing against three merged pull requests has a finding worth
    reading. A loop that could not count has no finding at all, and the two must not
    render alike.
    """
    found_nothing = oss_state.intake(0, 3, window=WINDOW)
    could_not_look = oss_state.intake(None, 3, window=WINDOW, why="gh unreachable")

    assert found_nothing["state"] == oss_state.INTAKE_MEASURED
    assert found_nothing["ratio"] == 0.0

    assert could_not_look["state"] == oss_state.INTAKE_COULD_NOT_COUNT
    assert could_not_look["ratio"] is None
    assert could_not_look["filings"] is None
    assert "gh unreachable" in could_not_look["why"]


def test_an_uncounted_denominator_is_could_not_count_too():
    assert (
        oss_state.intake(6, None, window=WINDOW, why="the state file was absent")["state"]
        == oss_state.INTAKE_COULD_NOT_COUNT
    )


def test_could_not_count_without_a_reason_is_refused():
    """An unexplained absence is the absence this plugin is named after."""
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.intake(None, 11, window=WINDOW)
    assert "why" in str(caught.value)


def test_nothing_merged_is_no_denominator_and_one_merged_is_measured():
    """Both arms again. 6/0 is not 6, and it is not 0."""
    nothing_merged = oss_state.intake(6, 0, window=WINDOW)
    one_merged = oss_state.intake(6, 1, window=WINDOW)

    assert nothing_merged["state"] == oss_state.INTAKE_NO_DENOMINATOR
    assert nothing_merged["ratio"] is None
    assert nothing_merged["filings"] == 6  # the numerator still says something

    assert one_merged["state"] == oss_state.INTAKE_MEASURED
    assert one_merged["ratio"] == 6.0


def test_the_window_is_required_rather_than_defaulted():
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.intake(6, 11, window="  ")
    assert "window" in str(caught.value)


def test_a_bool_is_not_a_count():
    """``True`` is an ``int`` in Python and would silently count as one filing."""
    with pytest.raises(oss_state.StateError):
        oss_state.intake(True, 11, window=WINDOW)
    with pytest.raises(oss_state.StateError):
        oss_state.intake(6, False, window=WINDOW)


def test_a_negative_count_is_refused():
    with pytest.raises(oss_state.StateError):
        oss_state.intake(-1, 11, window=WINDOW)


# ----------------------------------------------------------------------- how it renders


def test_the_measured_line_carries_the_ratio_and_the_window():
    line = oss_state.intake_line(oss_state.intake(6, 11, window=WINDOW))
    assert "filings per merged pull request" in line
    assert WINDOW in line
    assert "6 filings" in line and "11 merged pull requests" in line


def test_could_not_count_never_renders_as_a_ratio():
    """The rendering is where the third state gets lost, so it is asserted here."""
    line = oss_state.intake_line(
        oss_state.intake(None, 11, window=WINDOW, why="gh unreachable")
    )
    assert "could not count" in line
    assert "filings per merged pull request" not in line
    assert "gh unreachable" in line


def test_no_denominator_never_renders_as_a_ratio_of_zero():
    line = oss_state.intake_line(oss_state.intake(6, 0, window=WINDOW))
    assert "filings per merged pull request" not in line
    assert "not a ratio of zero" in line


def test_intake_line_refuses_something_that_is_not_a_record():
    """It would otherwise print a sentence about an object nobody handed it."""
    with pytest.raises(oss_state.StateError):
        oss_state.intake_line("measured")


def test_an_unrecognised_state_claims_nothing_rather_than_guessing_a_ratio():
    """A record from a newer writer, read by an older reader. Both arms: the state this
    function knows renders a ratio, and the one it does not renders a refusal."""
    known = oss_state.intake_line(oss_state.intake(6, 11, window=WINDOW))
    unknown = oss_state.intake_line(
        {"state": "invented-later", "window": WINDOW, "filings": 6, "merged_prs": 11}
    )
    assert "filings per merged pull request" in known
    assert "filings per merged pull request" not in unknown
    assert "nothing is claimed" in unknown


def test_a_partial_trend_does_not_render_as_a_plain_ratio():
    """The number a skimmer takes away must carry its own caveat, not sit beside one.

    Both arms: the same sum renders as a ratio when every tick counted, and as PARTIAL
    when one did not.
    """
    complete = oss_state.intake_trend(
        [{"at": STAMP, "decision": "d", "detail": {"intake": oss_state.intake(3, 4, window=WINDOW)}}]
    )
    holed = oss_state.intake_trend(
        [
            {"at": STAMP, "decision": "d", "detail": {"intake": oss_state.intake(3, 4, window=WINDOW)}},
            {"at": STAMP, "decision": "d"},
        ]
    )
    assert "filings per merged pull request" in oss_state.intake_line(complete)
    partial_line = oss_state.intake_line(holed)
    assert "PARTIAL" in partial_line
    assert "filings per merged pull request" not in partial_line
    assert "unrecognised" not in partial_line


def test_the_cli_prints_the_sentence_to_stderr_and_the_record_to_stdout(tmp_path, capsys):
    """A caller piping into `jq` still gets JSON; a human still gets the sentence."""
    path = tmp_path / "state.json"
    assert (
        oss_state._main(
            [
                str(path),
                "--decision",
                "d",
                "--at",
                STAMP,
                "--filings",
                "unknown",
                "--merged-prs",
                "11",
                "--window",
                WINDOW,
                "--intake-why",
                "gh was down",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["detail"]["intake"]["state"] == (
        oss_state.INTAKE_COULD_NOT_COUNT
    )
    assert "could not count" in captured.err
    assert "this is not zero" in captured.err


def test_every_state_this_module_emits_has_a_sentence():
    """A state added without a rendering arm falls through to `unrecognised`, which is
    a real answer and a useless one. This is the registry that stops it being silent."""
    records = {
        oss_state.INTAKE_MEASURED: oss_state.intake(1, 2, window=WINDOW),
        oss_state.INTAKE_NO_DENOMINATOR: oss_state.intake(1, 0, window=WINDOW),
        oss_state.INTAKE_COULD_NOT_COUNT: oss_state.intake(
            None, 2, window=WINDOW, why="gh was down"
        ),
        oss_state.INTAKE_PARTIAL: {
            "state": oss_state.INTAKE_PARTIAL,
            "window": WINDOW,
            "filings": 1,
            "merged_prs": 2,
            "why": "one tick contributed no pair",
        },
    }
    assert set(records) == {
        oss_state.INTAKE_MEASURED,
        oss_state.INTAKE_NO_DENOMINATOR,
        oss_state.INTAKE_COULD_NOT_COUNT,
        oss_state.INTAKE_PARTIAL,
    }
    for state, record in records.items():
        assert "unrecognised" not in oss_state.intake_line(record), state


# ------------------------------------------------------------------------- the trend


def _entry(intake_record=None):
    entry = {"at": STAMP, "decision": "merged something"}
    if intake_record is not None:
        entry["detail"] = {"intake": intake_record}
    return entry


def test_a_trend_over_complete_ticks_re_adds_the_pairs():
    """3/4 and 1/2 is 4 over 6, not the average of two quotients."""
    entries = [
        _entry(oss_state.intake(3, 4, window=WINDOW)),
        _entry(oss_state.intake(1, 2, window=WINDOW)),
    ]
    trend = oss_state.intake_trend(entries)
    assert trend["state"] == oss_state.INTAKE_MEASURED
    assert (trend["filings"], trend["merged_prs"]) == (4, 6)
    assert trend["ratio"] == pytest.approx(4 / 6)
    assert trend["ticks_counted"] == 2
    assert trend["ticks_uncounted"] == 0
    assert trend["ticks_without_record"] == 0


def test_one_uncounted_tick_makes_the_whole_trend_partial():
    """A partial sum rendering as a total is the trap this file exists under.

    Both arms: the same two countable ticks are ``measured`` on their own and
    ``partial`` the moment a third tick could not count.
    """
    countable = [
        _entry(oss_state.intake(3, 4, window=WINDOW)),
        _entry(oss_state.intake(1, 2, window=WINDOW)),
    ]
    assert oss_state.intake_trend(countable)["state"] == oss_state.INTAKE_MEASURED

    with_a_hole = countable + [
        _entry(oss_state.intake(None, None, window=WINDOW, why="gh was down"))
    ]
    trend = oss_state.intake_trend(with_a_hole)
    assert trend["state"] == oss_state.INTAKE_PARTIAL
    assert trend["ticks_counted"] == 2
    assert trend["ticks_uncounted"] == 1
    assert (trend["filings"], trend["merged_prs"]) == (4, 6)


def test_a_tick_that_recorded_no_intake_at_all_is_counted_as_a_hole():
    """Not recording is an absence too, and a silent one."""
    trend = oss_state.intake_trend(
        [_entry(oss_state.intake(3, 4, window=WINDOW)), _entry()]
    )
    assert trend["state"] == oss_state.INTAKE_PARTIAL
    assert trend["ticks_without_record"] == 1


def test_a_history_with_no_countable_tick_is_could_not_count_not_zero():
    """Both arms: an empty history and a history of holes answer the same way, and a
    history with one countable tick does not."""
    assert oss_state.intake_trend([])["state"] == oss_state.INTAKE_COULD_NOT_COUNT
    assert (
        oss_state.intake_trend([_entry(), _entry()])["state"]
        == oss_state.INTAKE_COULD_NOT_COUNT
    )
    assert (
        oss_state.intake_trend([_entry(oss_state.intake(0, 1, window=WINDOW))])["state"]
        == oss_state.INTAKE_MEASURED
    )


def test_a_trend_whose_ticks_all_merged_nothing_is_no_denominator():
    trend = oss_state.intake_trend(
        [
            _entry(oss_state.intake(2, 0, window=WINDOW)),
            _entry(oss_state.intake(1, 0, window=WINDOW)),
        ]
    )
    assert trend["state"] == oss_state.INTAKE_NO_DENOMINATOR
    assert trend["filings"] == 3
    assert trend["ratio"] is None


def test_a_detail_that_is_not_a_dict_does_not_crash_the_trend():
    """Entries are written by hand as often as by the CLI."""
    trend = oss_state.intake_trend(
        [
            {"at": STAMP, "decision": "d", "detail": "a string"},
            {"at": STAMP, "decision": "d", "detail": {"intake": "not a record"}},
            _entry(oss_state.intake(1, 2, window=WINDOW)),
        ]
    )
    assert trend["state"] == oss_state.INTAKE_PARTIAL
    assert trend["ticks_without_record"] == 2


# ---------------------------------------------------------------------------- the CLI


def test_the_cli_attaches_the_intake_record_to_the_entry(tmp_path, capsys):
    path = tmp_path / "state.json"
    code = oss_state._main(
        [
            str(path),
            "--decision",
            "merged 11 PRs",
            "--at",
            STAMP,
            "--filings",
            "6",
            "--merged-prs",
            "11",
            "--window",
            WINDOW,
        ]
    )
    assert code == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["detail"]["intake"]["state"] == oss_state.INTAKE_MEASURED
    assert entry["detail"]["intake"]["merged_prs"] == 11
    assert oss_state.read(path)[0]["detail"]["intake"]["filings"] == 6


def test_the_cli_takes_unknown_for_a_count_it_could_not_take(tmp_path, capsys):
    path = tmp_path / "state.json"
    code = oss_state._main(
        [
            str(path),
            "--decision",
            "merged something",
            "--at",
            STAMP,
            "--filings",
            "unknown",
            "--merged-prs",
            "11",
            "--window",
            WINDOW,
            "--intake-why",
            "gh rate limited",
        ]
    )
    assert code == 0
    record = json.loads(capsys.readouterr().out)["detail"]["intake"]
    assert record["state"] == oss_state.INTAKE_COULD_NOT_COUNT
    assert record["why"] == "gh rate limited"


def test_the_cli_refuses_half_an_intake_record(tmp_path, capsys):
    """``--filings`` alone would write a numerator with no denominator and no window."""
    path = tmp_path / "state.json"
    assert (
        oss_state._main(
            [str(path), "--decision", "d", "--at", STAMP, "--filings", "6"]
        )
        == 1
    )
    out = capsys.readouterr().out
    assert "--merged-prs" in out and "--window" in out
    assert not path.exists()


def test_a_reason_with_no_counts_beside_it_is_refused(tmp_path, capsys):
    """`--intake-why` alone is a reason for a measurement nobody took, and it used to be
    accepted and dropped: the record trigger only watched the other three flags."""
    path = tmp_path / "state.json"
    assert (
        oss_state._main(
            [str(path), "--decision", "d", "--at", STAMP, "--intake-why", "gh was down"]
        )
        == 1
    )
    assert "--filings" in capsys.readouterr().out
    assert not path.exists()


def test_the_cli_refuses_a_count_that_is_not_a_number_rather_than_guessing(tmp_path):
    path = tmp_path / "state.json"
    with pytest.raises(SystemExit):
        oss_state._main(
            [
                str(path),
                "--decision",
                "d",
                "--at",
                STAMP,
                "--filings",
                "six",
                "--merged-prs",
                "11",
                "--window",
                WINDOW,
            ]
        )


def test_intake_flags_on_a_read_mode_are_refused_rather_than_ignored(tmp_path, capsys):
    """Counts passed to `--read` went nowhere and said nothing, which is a count
    somebody took and the tool discarded. Both arms: refused on a read mode, accepted
    on the append mode they belong to."""
    path = tmp_path / "state.json"
    assert (
        oss_state._main(
            [str(path), "--read", "--filings", "6", "--merged-prs", "11", "--window", WINDOW]
        )
        == 1
    )
    assert "only recorded with --decision" in capsys.readouterr().out
    assert (
        oss_state._main(
            [
                str(path),
                "--decision",
                "d",
                "--at",
                STAMP,
                "--filings",
                "6",
                "--merged-prs",
                "11",
                "--window",
                WINDOW,
            ]
        )
        == 0
    )


def test_the_cli_prints_the_trend_over_the_file(tmp_path, capsys):
    path = tmp_path / "state.json"
    for filings, merged in ((3, 4), (1, 2)):
        oss_state.append(
            path,
            STAMP,
            "a tick",
            detail={"intake": oss_state.intake(filings, merged, window=WINDOW)},
        )
    assert oss_state._main([str(path), "--trend"]) == 0
    trend = json.loads(capsys.readouterr().out)
    assert trend["state"] == oss_state.INTAKE_MEASURED
    assert (trend["filings"], trend["merged_prs"]) == (4, 6)


def test_the_cli_trend_on_an_empty_history_says_could_not_count(tmp_path, capsys):
    assert oss_state._main([str(tmp_path / "state.json"), "--trend"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["state"] == oss_state.INTAKE_COULD_NOT_COUNT
    )


def test_the_cli_refuses_a_negative_count(tmp_path):
    with pytest.raises(SystemExit):
        oss_state._main(
            [
                str(tmp_path / "state.json"),
                "--decision",
                "d",
                "--at",
                STAMP,
                "--filings",
                "-1",
                "--merged-prs",
                "11",
                "--window",
                WINDOW,
            ]
        )


def _intake_argv(path, detail):
    return [
        str(path),
        "--decision",
        "d",
        "--at",
        STAMP,
        "--detail",
        detail,
        "--filings",
        "6",
        "--merged-prs",
        "11",
        "--window",
        WINDOW,
    ]


def test_the_cli_refuses_to_bury_an_intake_record_in_a_non_object_detail(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main(_intake_argv(path, '"a string"')) == 1
    assert "JSON object" in capsys.readouterr().out
    assert not path.exists()


def test_the_cli_refuses_to_overwrite_an_intake_key_the_caller_supplied(tmp_path, capsys):
    """Silently winning would replace a record somebody wrote with one it computed."""
    path = tmp_path / "state.json"
    assert oss_state._main(_intake_argv(path, '{"intake": "mine"}')) == 1
    assert "already carries" in capsys.readouterr().out
    assert not path.exists()


def test_a_detail_object_survives_alongside_the_intake_record(tmp_path, capsys):
    """The positive control for the two refusals above."""
    path = tmp_path / "state.json"
    assert oss_state._main(_intake_argv(path, '{"pr": 152}')) == 0
    detail = json.loads(capsys.readouterr().out)["detail"]
    assert detail["pr"] == 152
    assert detail["intake"]["state"] == oss_state.INTAKE_MEASURED


# --------------------------------------------------------- the duty, where it is written


def _missing(text, phrases):
    """The phrases not present, case-insensitively. Returns a list, never a bool."""
    lowered = text.lower()
    return [phrase for phrase in phrases if phrase.lower() not in lowered]


def test_the_prose_checker_can_find_something_and_can_find_nothing():
    """The positive control. Four toothless prose anchors turned up on this repo in one
    day; each passed against the file it was supposed to be about. So the checker is
    made to fail on a text that lacks the phrase before it is pointed at a real file."""
    assert _missing("a document mentioning nothing", ["filings per merged"]) == [
        "filings per merged"
    ]
    assert _missing("filings per merged pull request", ["filings per merged"]) == []


def _read(relative):
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_the_manager_skill_names_the_metric_its_window_and_its_third_state():
    missing = _missing(
        _read("skills/manager/SKILL.md"),
        [
            "filings per merged pull request",
            "since the last tick",
            "could-not-count",
            "no-denominator",
            "oss_state.py",
        ],
    )
    assert missing == [], "skills/manager/SKILL.md does not say: {}".format(missing)


def test_the_manager_skill_states_that_no_target_ratio_is_claimed():
    """The one number this must not carry. A threshold off one sample is the hardcoded
    repository fact this codebase forbids."""
    assert _missing(_read("skills/manager/SKILL.md"), ["no target ratio"]) == []


def test_the_manager_skill_carries_the_per_page_aggregation_trap():
    """It lived only in the triager, and the manager is what computes the tick metric."""
    assert (
        _missing(
            _read("skills/manager/SKILL.md"), ["--paginate", "one number per page"]
        )
        == []
    )


def test_the_tick_command_names_the_flags_that_record_it():
    missing = _missing(
        _read("commands/tick.md"), ["--filings", "--merged-prs", "--window", "--trend"]
    )
    assert missing == [], "commands/tick.md does not say: {}".format(missing)

