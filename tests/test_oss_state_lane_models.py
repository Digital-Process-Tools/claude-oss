"""#316: the model a delegated lane ran on, recorded so the mix stays recomputable.

The prose half of #316 says how the choice is made. This is the half that outlives
prose: a machine-readable record beside ``detail.intake``, built under the same
discipline the intake metric is built under, because the failure it is guarding
against is the same one -- a tick that recorded nothing and a tick that dispatched
nothing render identically unless something keeps them apart.

Every "must not" below is paired with a "must", in the same fixture. A test that only
asserts a state is absent passes against a module that returns nothing at all.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


WINDOW = "lanes dispatched this tick"


def _piped(argv):
    """Run the CLI as a real process with the two streams merged into one pipe.

    `capsys` keeps stdout and stderr apart, so it cannot see the ordering FAIL-then-NOT-
    RECORDED asserts: stdout is block-buffered the moment it is a pipe rather than a
    terminal, and a FAIL printed first still surfaces second unless something flushes.
    A transcript is read as one merged stream, so that is what the fixture has to be --
    same mechanism `test_oss_state_cli.py`'s own `_piped` exists for.
    """
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _lane(issue=316, model="opus", choice="default", why=None):
    lane = {"issue": issue, "model": model, "choice": choice}
    if why is not None:
        lane["why"] = why
    return lane


# --------------------------------------------------------------- the three states


def test_a_recorded_tick_keeps_every_lane_it_was_given():
    record = oss_state.lane_models(
        [
            _lane(316, "opus", "default"),
            _lane(312, "sonnet", "override", "mechanical scope, strict brief"),
        ],
        window=WINDOW,
    )
    assert record["state"] == oss_state.LANES_RECORDED
    assert record["window"] == WINDOW
    assert [lane["issue"] for lane in record["lanes"]] == [316, 312]
    assert [lane["model"] for lane in record["lanes"]] == ["opus", "sonnet"]
    assert record["lanes"][1]["why"] == "mechanical scope, strict brief"
    assert record["why"] is None


def test_no_lanes_dispatched_is_not_the_same_state_as_no_record():
    """The pair this whole file exists for.

    A tick that dispatched nothing is a fact somebody established. A tick that said
    nothing about its lanes established no such thing. Both end up with zero lanes in
    any sum, and only one of them is evidence.
    """
    dispatched_none = oss_state.lane_models([], window=WINDOW)
    assert dispatched_none["state"] == oss_state.LANES_NONE_DISPATCHED
    assert dispatched_none["lanes"] == []

    # The must-fire half: the trend below is what tells the two apart, and it must
    # actually distinguish them rather than both landing in one bucket.
    said_nothing = oss_state.lane_model_trend([{"at": "t", "decision": "d"}])
    counted = oss_state.lane_model_trend(
        [{"at": "t", "decision": "d", "detail": {"lanes": dispatched_none}}]
    )
    assert said_nothing["state"] == oss_state.LANES_COULD_NOT_ESTABLISH
    assert counted["state"] == oss_state.LANES_NONE_DISPATCHED
    assert said_nothing["state"] != counted["state"]


def test_could_not_establish_needs_a_reason_and_never_renders_as_a_mix():
    record = oss_state.lane_models(
        None, window=WINDOW, why="resumed from a session whose transcripts were reaped"
    )
    assert record["state"] == oss_state.LANES_COULD_NOT_ESTABLISH
    assert record["lanes"] is None, "an empty list here would read as 'no lanes ran'"
    assert "reaped" in record["why"]

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_models(None, window=WINDOW)
    assert "why" in str(caught.value)


def test_a_window_is_required_exactly_as_intake_requires_one():
    for lanes in ([_lane()], [], None):
        with pytest.raises(oss_state.StateError):
            oss_state.lane_models(lanes, window="   ", why="x")
    # Must-fire control: the same calls with a window are accepted.
    assert oss_state.lane_models([_lane()], window=WINDOW)["state"]
    assert oss_state.lane_models([], window=WINDOW)["state"]
    assert oss_state.lane_models(None, window=WINDOW, why="x")["state"]


# ------------------------------------------------------- what a lane has to carry


def test_an_override_without_a_reason_is_refused():
    """The accretion #316 was filed about, in one field.

    An override nobody explained is exactly the state the issue describes -- a fleet
    two-thirds one model by accident rather than by decision -- and it is cheap to
    refuse at the boundary rather than discover a month later.
    """
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_models([_lane(choice="override")], window=WINDOW)
    message = str(caught.value)
    assert "override" in message and "reason" in message

    # Must-fire: the default arm needs no reason, so the refusal is about overrides
    # and not about `why` being absent.
    assert oss_state.lane_models([_lane(choice="default")], window=WINDOW)


def test_a_choice_that_is_neither_word_is_refused_rather_than_coerced():
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_models([_lane(choice="probably the default")], window=WINDOW)
    assert "probably the default" in str(caught.value)
    for good in (oss_state.CHOICE_DEFAULT, oss_state.CHOICE_OVERRIDE):
        why = "a reason" if good == oss_state.CHOICE_OVERRIDE else None
        assert oss_state.lane_models([_lane(choice=good, why=why)], window=WINDOW)


def test_the_model_name_is_not_checked_against_a_list_of_models():
    """Deliberate, and the reason is this repository's governing rule.

    Which models exist is a fact about the harness, not about this repository. An
    allow-list here would refuse a model that ships next month and would be a second
    copy of somebody else's roster. What is refused is an empty name, which carries
    nothing.
    """
    record = oss_state.lane_models(
        [_lane(model="a-model-that-does-not-exist-yet")], window=WINDOW
    )
    assert record["lanes"][0]["model"] == "a-model-that-does-not-exist-yet"
    for empty in ("", "   ", None):
        with pytest.raises(oss_state.StateError):
            oss_state.lane_models([_lane(model=empty)], window=WINDOW)


def test_an_issue_number_that_is_a_bool_is_refused():
    """`True` is an `int`, and would land in the history as lane number one."""
    with pytest.raises(oss_state.StateError):
        oss_state.lane_models([_lane(issue=True)], window=WINDOW)
    for empty in ("", None):
        with pytest.raises(oss_state.StateError):
            oss_state.lane_models([_lane(issue=empty)], window=WINDOW)
    # Must-fire: both shapes a real lane key can take are accepted.
    assert oss_state.lane_models([_lane(issue=316)], window=WINDOW)
    assert oss_state.lane_models([_lane(issue="288/289")], window=WINDOW)


def test_a_lane_that_is_not_a_mapping_is_refused_with_its_own_position():
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_models([_lane(), "sonnet"], window=WINDOW)
    assert "lane 2" in str(caught.value)


# ------------------------------------------------------------------- the trend


def _entry(record):
    return {"at": "2026-08-20T00:00:00+00:00", "decision": "d", "detail": {"lanes": record}}


def test_the_trend_re_adds_the_mix_and_counts_the_overrides():
    entries = [
        _entry(oss_state.lane_models([_lane(1, "opus"), _lane(2, "opus")], window=WINDOW)),
        _entry(
            oss_state.lane_models(
                [_lane(3, "sonnet", "override", "mechanical")], window=WINDOW
            )
        ),
    ]
    trend = oss_state.lane_model_trend(entries)
    assert trend["state"] == oss_state.LANES_RECORDED
    assert trend["counts"] == {"opus": 2, "sonnet": 1}
    assert trend["lanes"] == 3
    assert trend["overrides"] == 1
    assert trend["ticks_counted"] == 2
    assert trend["ticks_without_record"] == 0


def test_one_tick_with_no_record_makes_the_whole_sum_partial():
    """A partial sum labelled partial is usable; labelled total it is the trap."""
    entries = [
        _entry(oss_state.lane_models([_lane(1, "opus")], window=WINDOW)),
        {"at": "t", "decision": "a tick that said nothing about its lanes"},
    ]
    trend = oss_state.lane_model_trend(entries)
    assert trend["state"] == oss_state.LANES_PARTIAL
    assert trend["counts"] == {"opus": 1}, "the real sum is still returned"
    assert trend["ticks_without_record"] == 1
    assert "1 of 2" in trend["why"]

    # Must-fire control: drop the hole and the same history is no longer partial.
    whole = oss_state.lane_model_trend(entries[:1])
    assert whole["state"] == oss_state.LANES_RECORDED
    assert whole["why"] is None


def test_a_history_that_recorded_nothing_has_no_counts_rather_than_empty_counts():
    trend = oss_state.lane_model_trend([{"at": "t", "decision": "d"}, {"at": "u", "decision": "e"}])
    assert trend["state"] == oss_state.LANES_COULD_NOT_ESTABLISH
    assert trend["counts"] is None, "{} here would read as 'no lane ran on any model'"
    assert trend["lanes"] is None
    assert "2" in trend["why"]


def test_an_unrecognised_state_in_the_history_is_a_hole_not_a_zero():
    entries = [
        _entry(oss_state.lane_models([_lane(1, "opus")], window=WINDOW)),
        _entry({"state": "invented-later", "lanes": [], "window": WINDOW}),
    ]
    trend = oss_state.lane_model_trend(entries)
    assert trend["state"] == oss_state.LANES_PARTIAL
    assert trend["ticks_uncounted"] == 1
    assert trend["counts"] == {"opus": 1}


def test_the_trend_survives_a_detail_that_is_not_a_mapping():
    trend = oss_state.lane_model_trend(
        [{"at": "t", "decision": "d", "detail": "a string"}, "not an entry at all"]
    )
    assert trend["state"] == oss_state.LANES_COULD_NOT_ESTABLISH
    assert trend["ticks_without_record"] == 2


# ------------------------------------------------------------------ the sentence


def test_every_state_renders_as_its_own_sentence():
    """Rendering is where a third state gets lost, so each one is checked apart."""
    sentences = {}
    sentences["recorded"] = oss_state.lane_models(
        [_lane(1, "opus"), _lane(2, "sonnet", "override", "mechanical")], window=WINDOW
    )
    sentences["none"] = oss_state.lane_models([], window=WINDOW)
    sentences["unknown"] = oss_state.lane_models(None, window=WINDOW, why="no transcripts")
    rendered = {key: oss_state.lane_models_line(value) for key, value in sentences.items()}

    assert len(set(rendered.values())) == 3, rendered
    for line in rendered.values():
        assert line.startswith("lane models {}: ".format(WINDOW))

    assert "1 opus" in rendered["recorded"] and "1 sonnet" in rendered["recorded"]
    assert "1 override" in rendered["recorded"]
    assert "dispatched no developer lane" in rendered["none"]
    assert "could not establish" in rendered["unknown"]
    assert "no transcripts" in rendered["unknown"]
    # The one rendering that must never happen: an unestablished mix as an empty one.
    assert "0 lanes" not in rendered["unknown"]


def test_an_unrecognised_record_claims_nothing():
    line = oss_state.lane_models_line({"state": "invented-later", "window": WINDOW})
    assert "invented-later" in line and "nothing is claimed" in line
    with pytest.raises(oss_state.StateError):
        oss_state.lane_models_line("not a record")


# ----------------------------------------------------------------------- the CLI


def _state_file(tmp_path):
    return str(tmp_path / "state.json")


def test_the_cli_records_lanes_and_receipts_them_after_the_write(tmp_path, capsys):
    path = _state_file(tmp_path)
    code = oss_state._main(
        [
            path,
            "--decision",
            "dispatched two lanes",
            "--at",
            "2026-08-20T09:00:00+00:00",
            "--lane",
            "316=opus:default",
            "--lane",
            "312=sonnet:override:mechanical scope, strict brief",
            "--lane-window",
            WINDOW,
        ]
    )
    assert code == 0
    out = capsys.readouterr()
    assert "RECORDED lane models" in out.err
    entry = json.loads(out.out)
    record = entry["detail"]["lanes"]
    assert record["state"] == oss_state.LANES_RECORDED
    assert record["lanes"][1] == {
        "issue": 312,
        "model": "sonnet",
        "choice": "override",
        "why": "mechanical scope, strict brief",
    }
    # It lands on disk, not only in the printed entry.
    assert json.loads(Path(path).read_text(encoding="utf-8"))[0]["detail"]["lanes"]


def test_an_override_with_no_reason_is_refused_at_the_cli(tmp_path, capsys):
    path = _state_file(tmp_path)
    code = oss_state._main(
        [path, "--decision", "d", "--at", "t", "--lane", "312=sonnet:override",
         "--lane-window", WINDOW]
    )
    assert code == 1
    # FAIL is stdout, matching every other refusal this CLI prints (test_oss_state_cli.py) --
    # a receipt goes to stderr, a verdict a caller might pipe on its own goes to stdout.
    assert "FAIL" in capsys.readouterr().out
    assert not Path(path).exists(), "a refused run must write no history"


def test_a_lane_this_run_dropped_says_so_under_the_FAIL(tmp_path):
    """#222's rule, one field over: a refusal after the record was built must name
    what went nowhere, or a mix somebody established is lost in silence.

    FAIL and NOT RECORDED go to different streams (stdout and stderr, matching every
    other refusal this CLI prints), so their relative order can only be observed on a
    merged pipe -- `capsys` keeps the two apart and would prove nothing here.
    """
    (tmp_path / "state.json").write_text("{ not json", encoding="utf-8")
    result = _piped(
        [str(tmp_path / "state.json"), "--decision", "d", "--at", "t", "--lane",
         "316=opus:default", "--lane-window", WINDOW]
    )
    assert result.returncode == 1, result.stdout
    lines = result.stdout.splitlines()
    fail_at = next(i for i, line in enumerate(lines) if line.startswith("FAIL"))
    dropped_at = next(
        i for i, line in enumerate(lines) if line.startswith("NOT RECORDED lane models")
    )
    assert fail_at < dropped_at, lines


def test_lane_flags_are_refused_by_the_reading_modes(tmp_path, capsys):
    path = _state_file(tmp_path)
    for mode in ("--read", "--last", "--trend", "--model-trend"):
        code = oss_state._main([path, mode, "--lane", "316=opus:default"])
        assert code == 1, mode
        assert "--lane" in capsys.readouterr().out, mode
    # Must-fire: the same reading modes work when no lane flag is passed.
    for mode in ("--read", "--last", "--trend", "--model-trend"):
        assert oss_state._main([path, mode]) == 0, mode
        capsys.readouterr()


def test_the_model_trend_mode_prints_the_sentence_and_the_record(tmp_path, capsys):
    path = _state_file(tmp_path)
    oss_state._main(
        [path, "--decision", "d", "--at", "t", "--lane", "316=opus:default",
         "--lane-window", WINDOW]
    )
    capsys.readouterr()
    assert oss_state._main([path, "--model-trend"]) == 0
    out = capsys.readouterr()
    assert out.err.startswith("TREND lane models")
    assert json.loads(out.out)["counts"] == {"opus": 1}


def test_a_malformed_lane_argument_is_refused_by_the_parser(tmp_path):
    path = _state_file(tmp_path)
    for bad in ("316", "316=", "=opus:default", "316=opus", "316=opus:maybe"):
        with pytest.raises(SystemExit):
            oss_state._main([path, "--decision", "d", "--at", "t", "--lane", bad,
                             "--lane-window", WINDOW])


def test_lanes_none_and_lanes_unknown_are_separate_declarations(tmp_path, capsys):
    none_path = _state_file(tmp_path)
    assert oss_state._main(
        [none_path, "--decision", "d", "--at", "t", "--lanes", "none",
         "--lane-window", WINDOW]
    ) == 0
    assert json.loads(capsys.readouterr().out)["detail"]["lanes"]["state"] == (
        oss_state.LANES_NONE_DISPATCHED
    )

    unknown_path = str(tmp_path / "other.json")
    assert oss_state._main(
        [unknown_path, "--decision", "d", "--at", "t", "--lanes", "unknown",
         "--lane-window", WINDOW, "--lane-why", "transcripts were reaped"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["detail"]["lanes"]["state"] == (
        oss_state.LANES_COULD_NOT_ESTABLISH
    )

    # `unknown` with no reason is refused; `none` needs none.
    third = str(tmp_path / "third.json")
    assert oss_state._main(
        [third, "--decision", "d", "--at", "t", "--lanes", "unknown",
         "--lane-window", WINDOW]
    ) == 1


def test_a_lane_record_needs_its_window_at_the_cli(tmp_path, capsys):
    path = _state_file(tmp_path)
    assert oss_state._main(
        [path, "--decision", "d", "--at", "t", "--lane", "316=opus:default"]
    ) == 1
    assert "--lane-window" in capsys.readouterr().out


def test_lanes_and_lane_cannot_both_be_given(tmp_path, capsys):
    path = _state_file(tmp_path)
    assert oss_state._main(
        [path, "--decision", "d", "--at", "t", "--lanes", "none",
         "--lane", "316=opus:default", "--lane-window", WINDOW]
    ) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_detail_already_carrying_lanes_is_refused(tmp_path, capsys):
    path = _state_file(tmp_path)
    assert oss_state._main(
        [path, "--decision", "d", "--at", "t", "--lane", "316=opus:default",
         "--lane-window", WINDOW, "--detail", '{"lanes": {}}']
    ) == 1
    assert "lanes" in capsys.readouterr().out


def test_intake_and_lanes_travel_in_one_entry_without_colliding(tmp_path, capsys):
    path = _state_file(tmp_path)
    assert oss_state._main(
        [path, "--decision", "d", "--at", "t",
         "--filings", "3", "--merged-prs", "2", "--window", "since the last tick",
         "--lane", "316=opus:default", "--lane-window", WINDOW]
    ) == 0
    out = capsys.readouterr()
    detail = json.loads(out.out)["detail"]
    assert detail["intake"]["state"] == oss_state.INTAKE_MEASURED
    assert detail["lanes"]["state"] == oss_state.LANES_RECORDED
    assert "RECORDED intake" in out.err and "RECORDED lane models" in out.err
