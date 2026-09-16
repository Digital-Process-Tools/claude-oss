"""Position-weighted delegation cost accounting -- #1595.

Three pieces, each independently testable against the issue's own worked
numbers:

* ``break_even_context`` / ``should_delegate`` / ``delegation_cost`` -- the
  quadratic break-even model from the issue body, checked against its own
  table (Q3).
* ``block_multiplier`` / ``multiplier_table`` / ``cached_multiplier_table``
  -- the "nth 100K block costs (2n-1)x the first" model and its cached
  approximation from the issue's comment (Q1's shape, without a live
  session).
* ``per_turn_records`` / ``detect_cache_misses`` / ``session_actual_cost``
  -- the real, per-turn read of a transcript (Q1 and the comment's Q4:
  which turn broke the prefix).

The cache-miss fixture pairs a healthy turn with an unhealthy one in the
same transcript, per the negative-assertion-needs-a-positive-control rule:
a checker that flags everything, or flags nothing, must not pass either
test alone.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "delegation_cost.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import delegation_cost as dc  # noqa: E402

IN_WINDOW = "2026-09-16T12:00:00Z"
OLD = "2026-09-15T00:00:00Z"


def _assistant(cache_read, cache_create=0, inp=1, out=10, ts=IN_WINDOW):
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "..."}],
            "usage": {
                "input_tokens": inp,
                "cache_creation_input_tokens": cache_create,
                "cache_read_input_tokens": cache_read,
                "output_tokens": out,
            },
        },
    }


def _user(text, ts=IN_WINDOW):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- break-even

ISSUE_TABLE = [
    # (work, brief, expected break-even A)
    (100_000, 20_000, 22_000),
    (100_000, 50_000, 63_000),
    (100_000, 100_000, 150_000),
    (100_000, 200_000, 400_000),
    (50_000, 10_000, 11_000),
    (50_000, 50_000, 75_000),
]


@pytest.mark.parametrize("work,brief,expected", ISSUE_TABLE)
def test_break_even_context_matches_issue_table(work, brief, expected):
    got = dc.break_even_context(work, brief)
    assert got == pytest.approx(expected, rel=0.01)


def test_break_even_context_cached_is_the_ballpark_of_the_comments_worked_example():
    # #1595 comment: "150K uncached becomes 173K cached" for work=100K, brief=100K.
    # The exact algebraic dual used here (see the function's own docstring)
    # is not the same model as the comment's more granular one, so this is
    # a ballpark check, not an exact-number check.
    got = dc.break_even_context(100_000, 100_000, cached=True)
    assert got == pytest.approx(173_000, rel=0.1)


@pytest.mark.parametrize(
    "work,brief", [(100_000, 20_000), (100_000, 100_000), (50_000, 10_000)]
)
def test_break_even_context_cached_is_self_consistent_with_delegation_cost(work, brief):
    # The bug this pins: an earlier version scaled the *uncached* threshold
    # by the premium directly, which is not delegation_cost's own dual and
    # disagreed with it by a wide margin near the threshold (#1595 review).
    threshold = dc.break_even_context(work, brief, cached=True)
    result = dc.delegation_cost(threshold, brief, work, cached=True)
    assert result["saved"] == pytest.approx(0, abs=1)


def test_break_even_context_rejects_non_positive_work():
    with pytest.raises(ValueError):
        dc.break_even_context(0, 10_000)


def test_break_even_context_rejects_negative_brief():
    with pytest.raises(ValueError):
        dc.break_even_context(10_000, -1)


def test_should_delegate_true_above_threshold_false_below():
    threshold = dc.break_even_context(100_000, 20_000)
    assert dc.should_delegate(threshold + 1_000, 100_000, 20_000) is True
    assert dc.should_delegate(threshold - 1_000, 100_000, 20_000) is False


def test_delegation_cost_saved_is_zero_at_the_break_even_point():
    work, brief = 100_000, 20_000
    threshold = dc.break_even_context(work, brief)
    result = dc.delegation_cost(threshold, brief, work)
    assert result["saved"] == pytest.approx(0, abs=1)


def test_delegation_cost_saved_flips_sign_around_the_break_even_point():
    work, brief = 100_000, 20_000
    threshold = dc.break_even_context(work, brief)
    above = dc.delegation_cost(threshold + 10_000, brief, work)
    below = dc.delegation_cost(threshold - 10_000, brief, work)
    assert above["saved"] > 0
    assert below["saved"] < 0


# -------------------------------------------------------------- multipliers


def test_block_multiplier_is_2n_minus_1():
    assert [dc.block_multiplier(n) for n in range(1, 6)] == [1, 3, 5, 7, 9]


def test_block_multiplier_rejects_n_below_one():
    with pytest.raises(ValueError):
        dc.block_multiplier(0)


def test_multiplier_table_matches_issue_table():
    rows = dc.multiplier_table(500_000, block=100_000)
    assert [m for _, m in rows] == [1, 3, 5, 7, 9]
    assert len(rows) == 5


def test_cached_multiplier_table_first_block_is_one_and_monotonic():
    rows = dc.cached_multiplier_table(
        500_000, block=100_000, turn_tokens=2_000, write_premium=12.5
    )
    multipliers = [m for _, m in rows]
    assert multipliers[0] == pytest.approx(1.0)
    assert multipliers == sorted(multipliers)
    # #1595 comment's worked table: block 3 lands near 3.7x cached.
    assert multipliers[2] == pytest.approx(3.7, abs=0.2)


# ------------------------------------------------------------- per-turn read


def test_per_turn_records_reads_each_assistant_turn_separately(tmp_path):
    path = tmp_path / "sess.jsonl"
    _write_jsonl(
        path,
        [
            _user("hi"),
            _assistant(0, cache_create=5_000, inp=2, out=10),
            "not json",
            _assistant(5_000, cache_create=200, inp=3, out=20),
        ],
    )
    records, malformed = dc.per_turn_records(path)
    assert [r["turn"] for r in records] == [0, 1]
    assert records[0]["cache_creation"] == 5_000
    assert records[1]["cache_read"] == 5_000
    assert malformed[0][0] == 3
    assert "not JSON" in malformed[0][1]


def test_per_turn_records_since_filters_earlier_records(tmp_path):
    path = tmp_path / "sess.jsonl"
    _write_jsonl(
        path,
        [
            _assistant(0, cache_create=1_000, ts=OLD),
            _assistant(1_000, cache_create=100, ts=IN_WINDOW),
        ],
    )
    records, _ = dc.per_turn_records(path, since=IN_WINDOW)
    assert len(records) == 1
    assert records[0]["cache_read"] == 1_000


def test_per_turn_records_unreadable_path_reports_could_not_open(tmp_path):
    records, malformed = dc.per_turn_records(tmp_path / "missing.jsonl")
    assert records is None
    assert malformed[0][0] == 0
    assert "could not open" in malformed[0][1]


def test_per_turn_records_reports_an_assistant_record_missing_usage(tmp_path):
    # #1595 review: an assistant record with no message/usage object used
    # to vanish silently -- neither counted as a turn nor as malformed, so
    # a transcript where every assistant record lacked usage rendered as
    # "nothing-in-window" indistinguishable from a window nothing ran in.
    path = tmp_path / "sess.jsonl"
    _write_jsonl(
        path,
        [
            {
                "type": "assistant",
                "timestamp": IN_WINDOW,
                "message": {"role": "assistant"},
            },
            _assistant(1_000, cache_create=100),
        ],
    )
    records, malformed = dc.per_turn_records(path)
    assert len(records) == 1
    assert malformed == [(1, "assistant record has no usage object")]


# ----------------------------------------------------------- cache misses


def test_detect_cache_misses_flags_a_rewritten_prefix():
    # Positive control: turn 1 writes more than it reads -- the prefix was
    # invalidated and had to be rebuilt from (near) scratch.
    records = [
        {"turn": 0, "cache_read": 0, "cache_creation": 50_000},
        {"turn": 1, "cache_read": 500, "cache_creation": 51_000},
    ]
    assert dc.detect_cache_misses(records) == [1]


def test_detect_cache_misses_does_not_flag_a_healthy_turn():
    # Negative-assertion control: a normal warm turn reads a large cached
    # prefix and writes only its own small delta -- must NOT be flagged.
    records = [
        {"turn": 0, "cache_read": 0, "cache_creation": 50_000},
        {"turn": 1, "cache_read": 50_000, "cache_creation": 2_000},
    ]
    assert dc.detect_cache_misses(records) == []


def test_detect_cache_misses_never_flags_turn_zero():
    records = [{"turn": 0, "cache_read": 0, "cache_creation": 50_000}]
    assert dc.detect_cache_misses(records) == []


def test_detect_cache_misses_does_not_flag_a_legitimately_large_early_write():
    # #1595 review: comparing a turn's own write against its own read
    # false-positives here -- turn 1 writes a lot (a big tool result) but
    # still reads back everything the previous turn had cached, so nothing
    # was invalidated. The ratio-against-the-prior-turn's-total rule must
    # not flag it.
    records = [
        {"turn": 0, "cache_read": 0, "cache_creation": 5_000},
        {"turn": 1, "cache_read": 5_000, "cache_creation": 40_000},
    ]
    assert dc.detect_cache_misses(records) == []


# ----------------------------------------------------------- session cost


def test_session_actual_cost_measured_sums_and_flags_misses(tmp_path):
    path = tmp_path / "sess.jsonl"
    _write_jsonl(
        path,
        [
            _assistant(0, cache_create=50_000, inp=1),
            _assistant(50_000, cache_create=2_000, inp=1),
            _assistant(500, cache_create=52_000, inp=1),  # miss
        ],
    )
    result = dc.session_actual_cost(
        path, price_read=0.5e-6, price_write=6.25e-6, price_input=15e-6
    )
    assert result["state"] == "measured"
    assert len(result["turns"]) == 3
    assert result["cache_misses"] == [2]
    manual_total = (
        0 * 0.5e-6
        + 50_000 * 6.25e-6
        + 1 * 15e-6
        + 50_000 * 0.5e-6
        + 2_000 * 6.25e-6
        + 1 * 15e-6
        + 500 * 0.5e-6
        + 52_000 * 6.25e-6
        + 1 * 15e-6
    )
    assert result["total_cost"] == pytest.approx(manual_total)


def test_session_actual_cost_nothing_in_window(tmp_path):
    path = tmp_path / "sess.jsonl"
    _write_jsonl(path, [_assistant(0, cache_create=1_000, ts=OLD)])
    result = dc.session_actual_cost(path, 0.5e-6, 6.25e-6, 15e-6, since=IN_WINDOW)
    assert result["state"] == "nothing-in-window"


def test_session_actual_cost_could_not_read(tmp_path):
    result = dc.session_actual_cost(tmp_path / "missing.jsonl", 0.5e-6, 6.25e-6, 15e-6)
    assert result["state"] == "could-not-read"


# ------------------------------------------------------------------- CLI


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
    )


def test_cli_break_even_prints_threshold_and_decision():
    proc = _run(
        "break-even", "--work", "100000", "--brief", "20000", "--context", "30000"
    )
    assert proc.returncode == 0
    assert "22000" in proc.stdout or "22,000" in proc.stdout
    assert "DELEGATE" in proc.stdout


def test_cli_table_prints_five_rows():
    proc = _run("table", "--total", "500000")
    assert proc.returncode == 0
    assert proc.stdout.count("x") >= 5


def test_cli_session_requires_the_session_subcommand(tmp_path):
    path = tmp_path / "sess.jsonl"
    _write_jsonl(path, [_assistant(0, cache_create=1_000)])
    proc = _run(
        str(path),
        "--price-read",
        "0.5e-6",
        "--price-write",
        "6.25e-6",
        "--price-input",
        "15e-6",
    )
    assert proc.returncode != 0


def test_cli_session_subcommand_reports_state(tmp_path):
    path = tmp_path / "sess.jsonl"
    _write_jsonl(path, [_assistant(0, cache_create=1_000)])
    proc = _run(
        "session",
        str(path),
        "--price-read",
        "0.5e-6",
        "--price-write",
        "6.25e-6",
        "--price-input",
        "15e-6",
    )
    assert proc.returncode == 0
    assert "STATE: measured" in proc.stdout
