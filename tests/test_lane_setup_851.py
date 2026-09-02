"""#851: the lane-bundling sweep has no mechanism, so it is the step that
gets skipped.

`suggest_companions` and its CLI wrapper `--suggest-companions` give the
disjointness check's sibling a shape: take a lane's own claimed file set and
an open board (handed in as JSON on stdin, never fetched by this script
itself -- the same separation of concerns `dispatch_rank.py` already uses),
and answer in three states -- `candidates`, `none`, `could-not-tell` -- never
letting an absence of signal (a capped board, an issue with no derivable
file set) render as the confident `none` this repository is named for
catching.

Every case below pairs the fix with a positive control, per this repo's own
rule that a negative assertion needs one.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LANE_SETUP_PATH = REPO_ROOT / "scripts" / "lane_setup.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _board(issues, capped=False, cap_detail=""):
    return {"capped": capped, "cap_detail": cap_detail, "issues": issues}


# --- _derive_declared_files: option (1), backtick paths in title/body ---------


def test_derives_a_path_named_in_the_body():
    resolved = lane_setup._derive_declared_files(
        REPO_ROOT, "a title", "touches `scripts/lane_setup.py` directly"
    )
    assert resolved is not None
    assert "scripts/lane_setup.py" in resolved["files"]


def test_derives_a_path_named_in_the_title_too():
    resolved = lane_setup._derive_declared_files(
        REPO_ROOT, "fix `scripts/doctor.py`", "no backticks here"
    )
    assert resolved is not None
    assert "scripts/doctor.py" in resolved["files"]


def test_returns_none_when_nothing_survives_the_filter():
    """The issue's own third-state trigger: an issue naming no repo-relative
    path at all must report `None`, never an empty-but-checked lane."""
    resolved = lane_setup._derive_declared_files(
        REPO_ROOT, "a vague title", "no backticks and no paths anywhere"
    )
    assert resolved is None


def test_control_a_backtick_state_word_is_not_read_as_a_path():
    """Control: this repo's own issues constantly quote state words like
    `` `could-not-tell` `` in backticks -- a token with no separator and no
    dot must not be treated as a path candidate."""
    resolved = lane_setup._derive_declared_files(
        REPO_ROOT, "discusses `could-not-tell` and `resolved-to-nothing`", ""
    )
    assert resolved is None


def test_a_directory_path_expands_like_an_ordinary_lane_pattern():
    resolved = lane_setup._derive_declared_files(
        REPO_ROOT, "touches everything under `skills/manager/phases/`", ""
    )
    assert resolved is not None
    assert "skills/manager/phases/dispatch.md" in resolved["files"]


# --- suggest_companions: the three states --------------------------------------


def test_candidates_state_names_the_issue_and_the_overlapping_paths():
    board = _board(
        [
            {
                "number": 100,
                "title": "fix scripts/lane_setup.py",
                "body": "see `scripts/lane_setup.py`",
            },
            {
                "number": 200,
                "title": "unrelated",
                "body": "touches `scripts/doctor.py` only",
            },
        ]
    )
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "candidates"
    assert result["candidates"] == [
        {"number": 100, "files": ["scripts/lane_setup.py"]}
    ]


def test_own_issue_is_excluded_from_the_sweep():
    board = _board(
        [{"number": 851, "title": "self", "body": "`scripts/lane_setup.py`"}]
    )
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "none"


def test_none_state_when_board_read_in_full_and_nothing_overlaps():
    board = _board(
        [{"number": 200, "title": "t", "body": "touches `scripts/doctor.py` only"}]
    )
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "none"
    assert result["candidates"] == []


def test_could_not_tell_when_board_was_capped():
    board = _board([], capped=True, cap_detail="capped at --limit 50")
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "could-not-tell"
    assert "capped at --limit 50" in result["detail"]


def test_could_not_tell_when_an_issues_file_set_could_not_be_derived():
    """The issue's third state, second trigger: even one issue this sweep
    could not read a file set for must block a confident `none` -- reporting
    `none` over an unread population is the exact false negative #851 exists
    to stop."""
    board = _board([{"number": 200, "title": "vague", "body": "no paths anywhere"}])
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "could-not-tell"
    assert "#200" in result["detail"]


def test_control_could_not_tell_is_not_forced_by_a_derivable_but_non_overlapping_issue():
    """Control: an issue whose file set WAS derived, and simply does not
    overlap, must not push the sweep into could-not-tell -- only a genuinely
    undetermined issue does that."""
    board = _board(
        [{"number": 200, "title": "t", "body": "touches `scripts/doctor.py` only"}]
    )
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "none"


def test_candidates_found_still_reports_an_undetermined_sibling_rather_than_dropping_it():
    """#851's own wording: 'never silently dropped' -- a real candidate found
    elsewhere on the board must not make an undetermined issue disappear
    from the record."""
    board = _board(
        [
            {"number": 100, "title": "t", "body": "`scripts/lane_setup.py`"},
            {"number": 300, "title": "vague", "body": "no paths anywhere"},
        ]
    )
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], board
    )
    assert result["state"] == "candidates"
    assert result["undetermined"] == [300]
    line = lane_setup._receipt_companions_line(result)
    assert "#300" in line


def test_no_other_open_issues_reads_none_not_could_not_tell():
    """Control: a board with nothing else open is a real, checked emptiness
    -- vacuously true, not a signal of anything unread."""
    result = lane_setup.suggest_companions(
        REPO_ROOT, 851, ["scripts/lane_setup.py"], _board([])
    )
    assert result["state"] == "none"


# --- the CLI wrapper ------------------------------------------------------------


def _run_cli(args, stdin_text=None):
    return subprocess.run(
        [sys.executable, str(LANE_SETUP_PATH)] + args,
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_cli_reports_candidates_and_exits_ok():
    board_json = json.dumps(
        _board(
            [{"number": 100, "title": "t", "body": "`scripts/lane_setup.py`"}]
        )
    )
    done = _run_cli(
        ["--suggest-companions", "851", "--lane", "scripts/lane_setup.py"],
        stdin_text=board_json,
    )
    assert done.returncode == 0, done.stderr
    assert "candidates: #100" in done.stdout


def test_cli_exits_could_not_run_when_capped():
    board_json = json.dumps(_board([], capped=True, cap_detail="capped at --limit 50"))
    done = _run_cli(
        ["--suggest-companions", "851", "--lane", "scripts/lane_setup.py"],
        stdin_text=board_json,
    )
    assert done.returncode == lane_setup.EXIT_COULD_NOT_RUN, done.stdout
    assert "COULD NOT TELL" in done.stdout


def test_cli_refuses_the_positional_issue_argument_alongside_the_flag():
    done = _run_cli(["--suggest-companions", "851", "851", "--lane", "x"])
    assert done.returncode == 2
    assert "--suggest-companions" in done.stderr


def test_cli_refuses_combination_with_claim():
    done = _run_cli(["--suggest-companions", "851", "--lane", "x", "--claim"])
    assert done.returncode == 2
    assert "--claim" in done.stderr


def test_cli_refuses_combination_with_release():
    done = _run_cli(["--suggest-companions", "851", "--release"])
    assert done.returncode == 2
    assert "--release" in done.stderr


def test_cli_refuses_combination_with_derive_held():
    done = _run_cli(["--suggest-companions", "851", "--derive-held"])
    assert done.returncode == 2
    assert "--derive-held" in done.stderr


def test_cli_refuses_combination_with_against():
    done = _run_cli(["--suggest-companions", "851", "--against", "x"])
    assert done.returncode == 2
    assert "--against" in done.stderr


def test_cli_requires_positional_issue_in_ordinary_mode():
    done = _run_cli([])
    assert done.returncode == 2
    assert "issue" in done.stderr


def test_cli_json_mode_emits_the_full_payload():
    board_json = json.dumps(
        _board([{"number": 100, "title": "t", "body": "`scripts/lane_setup.py`"}])
    )
    done = _run_cli(
        ["--suggest-companions", "851", "--lane", "scripts/lane_setup.py", "--json"],
        stdin_text=board_json,
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["state"] == "candidates"
    assert payload["candidates"][0]["number"] == 100


def test_cli_rejects_non_json_stdin():
    done = _run_cli(
        ["--suggest-companions", "851", "--lane", "x"],
        stdin_text="not json at all",
    )
    assert done.returncode == lane_setup.EXIT_COULD_NOT_RUN
    assert "not JSON" in done.stdout
