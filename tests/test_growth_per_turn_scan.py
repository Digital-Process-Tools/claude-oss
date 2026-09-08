"""Tests for scripts/growth_per_turn_scan.py -- #455.

Fixtures are hand-built JSONL lines matching the shape of a real subagent
transcript (record-level `attributionAgent` and `timestamp`, an
`assistant` record's `message.usage` carrying `input_tokens`,
`cache_creation_input_tokens` and `cache_read_input_tokens`) -- the same
shape tests/test_transcript_refusals.py already pins, confirmed against a
live ~/.claude/projects/*/subagents/*.jsonl tree while building this
scan, never read here (those files are one machine's own data, per the
brief).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import growth_per_turn_scan as gp  # noqa: E402

SPLIT_AT = "2026-08-22T11:05:29Z"


def _assistant(usage, timestamp, attribution="oss:developer"):
    return {
        "type": "assistant",
        "attributionAgent": attribution,
        "timestamp": timestamp,
        "message": {
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": "hi"}],
            "usage": usage,
        },
    }


def _usage(input_tokens=0, cache_creation=0, cache_read=0):
    return {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
    }


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _lane(turn1_context, final_context, turns, ts, attribution="oss:developer"):
    """Build a transcript with `turns` assistant records: the first carries
    `turn1_context` tokens, the last carries `final_context`, and any middle
    ones (turns > 2) carry the average -- growth_per_turn only reads first
    and last, so the middle shape doesn't matter for these tests."""
    records = [_assistant(_usage(cache_read=turn1_context), ts, attribution)]
    for _ in range(max(0, turns - 2)):
        mid = (turn1_context + final_context) // 2
        records.append(_assistant(_usage(cache_read=mid), ts, attribution))
    if turns >= 2:
        records.append(_assistant(_usage(cache_read=final_context), ts, attribution))
    return records


# ---------------------------------------------------------------------------
# _context_size / analyze_growth
# ---------------------------------------------------------------------------


def test_context_size_sums_the_three_token_fields():
    usage = _usage(input_tokens=1, cache_creation=2, cache_read=3)
    assert gp._context_size(usage) == 6


def test_context_size_treats_missing_fields_as_zero_not_a_raise():
    assert gp._context_size({}) == 0
    assert gp._context_size(None) == 0


def test_analyze_growth_computes_delta_over_turns_minus_one(tmp_path):
    path = tmp_path / "agent-1.jsonl"
    _write_jsonl(path, _lane(1000, 4000, 4, "2026-08-01T00:00:00Z"))
    result = gp.analyze_growth(path)
    assert result["ok"] is True
    assert result["turns"] == 4
    assert result["turn1_context"] == 1000
    assert result["final_context"] == 4000
    assert result["growth_per_turn"] == 1000  # (4000-1000)/3


def test_analyze_growth_is_none_for_a_single_turn_lane(tmp_path):
    """Must-not-fire control: one turn has no delta to compute."""
    path = tmp_path / "agent-2.jsonl"
    _write_jsonl(path, [_assistant(_usage(cache_read=500), "2026-08-01T00:00:00Z")])
    result = gp.analyze_growth(path)
    assert result["ok"] is True
    assert result["turns"] == 1
    assert result["growth_per_turn"] is None


def test_analyze_growth_reports_unreadable_file_distinctly(tmp_path):
    """Must-fire: garbage bytes are a read failure, never a clean zero-growth
    reading -- CLAUDE.md's own defect class, applied to this scan."""
    path = tmp_path / "agent-3.jsonl"
    path.write_bytes(b"\xff\xfe not json at all \x00\x01")
    result = gp.analyze_growth(path)
    assert result["ok"] is False
    assert "reason" in result

    # Control, same test: a clean file next to the bad one still reads fine.
    good = tmp_path / "agent-4.jsonl"
    _write_jsonl(good, _lane(100, 300, 3, "2026-08-01T00:00:00Z"))
    good_result = gp.analyze_growth(good)
    assert good_result["ok"] is True
    assert good_result["growth_per_turn"] == 100  # (300-100)/2


# ---------------------------------------------------------------------------
# run(): the three states
# ---------------------------------------------------------------------------


def test_run_is_measured_with_before_and_after_populations(tmp_path):
    root = tmp_path / "root"
    _write_jsonl(root / "before-1.jsonl", _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    _write_jsonl(root / "before-2.jsonl", _lane(1000, 5000, 3, "2026-08-02T00:00:00Z"))
    _write_jsonl(root / "after-1.jsonl", _lane(1000, 2000, 3, "2026-08-23T00:00:00Z"))
    _write_jsonl(root / "after-2.jsonl", _lane(1000, 2400, 3, "2026-08-24T00:00:00Z"))
    report = gp.run(roots=[root], split_at=SPLIT_AT)
    assert report["state"] == gp.STATE_MEASURED
    assert report["before"]["growth_samples"] == 2
    assert report["after"]["growth_samples"] == 2
    # before deltas: (3000-1000)/2=1000, (5000-1000)/2=2000 -> median 1500
    assert report["before"]["median_growth_per_turn"] == 1500
    # after deltas: (2000-1000)/2=500, (2400-1000)/2=700 -> median 600
    assert report["after"]["median_growth_per_turn"] == 600
    assert report["median_growth_per_turn_delta"] == 600 - 1500


def test_run_reports_no_post_fix_transcripts_distinctly_from_no_improvement(tmp_path):
    """The state named in #455 that must never render as 'no improvement':
    there simply is no post-fix data yet."""
    root = tmp_path / "root"
    _write_jsonl(root / "before-1.jsonl", _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    report = gp.run(roots=[root], split_at=SPLIT_AT)
    assert report["state"] == gp.STATE_NO_POST_FIX
    assert report["before"]["growth_samples"] == 1
    assert report["after"]["growth_samples"] == 0
    assert report.get("median_growth_per_turn_delta") is None

    # Control, same fixture root plus one after-split lane: now it measures.
    _write_jsonl(root / "after-1.jsonl", _lane(1000, 2000, 3, "2026-08-23T00:00:00Z"))
    measured = gp.run(roots=[root], split_at=SPLIT_AT)
    assert measured["state"] == gp.STATE_MEASURED


def test_run_is_could_not_read_when_no_transcripts_exist(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    report = gp.run(roots=[empty], split_at=SPLIT_AT)
    assert report["state"] == gp.STATE_COULD_NOT_READ

    # Control: the same root, populated, measures instead.
    _write_jsonl(empty / "before-1.jsonl", _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    _write_jsonl(empty / "after-1.jsonl", _lane(1000, 2000, 3, "2026-08-23T00:00:00Z"))
    populated = gp.run(roots=[empty], split_at=SPLIT_AT)
    assert populated["state"] == gp.STATE_MEASURED


def test_run_is_could_not_read_when_every_matching_file_fails_to_parse(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "bad.jsonl").write_bytes(b"\xff\xfe garbage \x00")
    report = gp.run(roots=[root], split_at=SPLIT_AT)
    assert report["state"] == gp.STATE_COULD_NOT_READ
    assert len(report["unreadable_files"]) == 1


def test_run_is_could_not_read_when_agent_filter_matches_nothing(tmp_path):
    root = tmp_path / "root"
    _write_jsonl(
        root / "other.jsonl",
        _lane(1000, 3000, 3, "2026-08-01T00:00:00Z", attribution="Explore"),
    )
    report = gp.run(roots=[root], agent_filter="oss:developer", split_at=SPLIT_AT)
    assert report["state"] == gp.STATE_COULD_NOT_READ

    # Control: same fixture, no filter -> not could-not-read.
    unfiltered = gp.run(roots=[root], agent_filter=None, split_at=SPLIT_AT)
    assert unfiltered["state"] != gp.STATE_COULD_NOT_READ


def test_agent_filter_excludes_other_agents_from_the_population(tmp_path):
    root = tmp_path / "root"
    _write_jsonl(
        root / "dev.jsonl",
        _lane(1000, 3000, 3, "2026-08-01T00:00:00Z", "oss:developer"),
    )
    _write_jsonl(
        root / "aud.jsonl", _lane(1000, 9000, 3, "2026-08-01T00:00:00Z", "oss:auditor")
    )
    _write_jsonl(
        root / "dev2.jsonl",
        _lane(1000, 2000, 3, "2026-08-23T00:00:00Z", "oss:developer"),
    )
    report = gp.run(roots=[root], agent_filter="oss:developer", split_at=SPLIT_AT)
    assert report["transcripts_matched_agent_filter"] == 2


# ---------------------------------------------------------------------------
# main(): exit codes and split-at override
# ---------------------------------------------------------------------------


def test_main_exits_measured_when_both_sides_present(tmp_path, capsys):
    root = tmp_path / "root"
    _write_jsonl(root / "before-1.jsonl", _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    _write_jsonl(root / "after-1.jsonl", _lane(1000, 2000, 3, "2026-08-23T00:00:00Z"))
    code = gp.main(["--root", str(root)])
    assert code == gp.EXIT_MEASURED
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "measured"


def test_main_exits_no_post_fix_when_after_side_is_empty(tmp_path, capsys):
    root = tmp_path / "root"
    _write_jsonl(root / "before-1.jsonl", _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    code = gp.main(["--root", str(root)])
    assert code == gp.EXIT_NO_POST_FIX
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "no-post-fix-transcripts"


def test_main_exits_could_not_read_for_an_empty_root(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = gp.main(["--root", str(empty)])
    assert code == gp.EXIT_COULD_NOT_READ
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "could-not-read"


def test_main_split_at_is_overridable(tmp_path, capsys):
    """A lane timestamped after the default split but before a custom one
    passed via --split-at lands on the before side instead."""
    root = tmp_path / "root"
    _write_jsonl(root / "lane-1.jsonl", _lane(1000, 3000, 3, "2026-08-23T00:00:00Z"))
    code = gp.main(["--root", str(root), "--split-at", "2026-08-30T00:00:00Z"])
    assert code == gp.EXIT_NO_POST_FIX
    out = json.loads(capsys.readouterr().out)
    assert out["before"]["growth_samples"] == 1
    assert out["after"]["growth_samples"] == 0


def test_default_split_at_matches_pr_454s_merge_timestamp():
    """Pin against drift: this is #454's own merged_at, read from the forge
    when this scan was built, not a guess."""
    assert gp.DEFAULT_SPLIT_AT == "2026-08-22T11:05:29Z"


# ---------------------------------------------------------------------------
# Self-review (#455): a bare string compare of a whole-second split against
# a millisecond-precision real timestamp misclassifies anything inside the
# split second, because "." sorts below "Z" in ASCII -- ".500Z" (500ms
# *after* the second) compares less than the bare "Z" (the second itself).
# Real transcripts carry milliseconds; DEFAULT_SPLIT_AT does not.
# ---------------------------------------------------------------------------


def test_timestamp_key_orders_a_fractional_second_after_its_bare_second():
    """Must-fire: this is exactly the bug a naive string compare has."""
    bare = gp._timestamp_key("2026-08-22T11:05:29Z")
    frac = gp._timestamp_key("2026-08-22T11:05:29.500Z")
    assert frac > bare
    # Control, same pair: a plain string compare gets this backwards.
    assert "2026-08-22T11:05:29.500Z" < "2026-08-22T11:05:29Z"


def test_timestamp_key_still_orders_distinct_whole_seconds_correctly():
    """Must-not-fire control: differing whole seconds order correctly either
    way, so the fix must not have broken the ordinary case."""
    earlier = gp._timestamp_key("2026-08-22T11:05:28.999Z")
    later = gp._timestamp_key("2026-08-22T11:05:29.001Z")
    assert earlier < later


def test_run_places_a_millisecond_timestamp_in_the_split_second_after_split(
    tmp_path,
):
    """The scenario found by review: a real-shaped lane timestamped 500ms
    into the split second must land on the after side, not before."""
    root = tmp_path / "root"
    _write_jsonl(root / "before-1.jsonl", _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    _write_jsonl(
        root / "boundary.jsonl",
        _lane(1000, 2000, 3, "2026-08-22T11:05:29.500Z"),
    )
    report = gp.run(roots=[root], split_at=SPLIT_AT)
    assert report["after"]["growth_samples"] == 1
    assert report["before"]["growth_samples"] == 1


# ---------------------------------------------------------------------------
# Self-review (#455): a present-but-empty usage dict silently contributes a
# context of 0, indistinguishable from a turn whose context genuinely was 0.
# ---------------------------------------------------------------------------


def test_analyze_growth_counts_turns_with_no_usable_usage_field(tmp_path):
    """Must-fire: a usage dict present but carrying none of the three
    context fields is flagged, not silently folded into a real zero."""
    path = tmp_path / "agent-unusable.jsonl"
    _write_jsonl(
        path,
        [
            _assistant({"some_other_field": 1}, "2026-08-01T00:00:00Z"),
            _assistant(_usage(cache_read=500), "2026-08-01T00:00:01Z"),
        ],
    )
    result = gp.analyze_growth(path)
    assert result["ok"] is True
    assert result["turns_with_unusable_usage"] == 1


def test_analyze_growth_reports_zero_unusable_usage_on_a_clean_transcript(
    tmp_path,
):
    """Must-not-fire control, same test shape: an ordinary transcript with
    real usage fields on every turn reports zero."""
    path = tmp_path / "agent-clean.jsonl"
    _write_jsonl(path, _lane(1000, 3000, 3, "2026-08-01T00:00:00Z"))
    result = gp.analyze_growth(path)
    assert result["ok"] is True
    assert result["turns_with_unusable_usage"] == 0


def test_no_post_fix_state_is_legible_even_when_the_before_side_has_no_growth_samples(
    tmp_path,
):
    """The degenerate case review flagged: every pre-split transcript is a
    single turn, so `before.growth_samples` is 0 too -- the state must still
    be no-post-fix-transcripts (not measured, not could-not-read), and the
    caller can tell from `growth_samples` that neither side has a reading."""
    root = tmp_path / "root"
    _write_jsonl(
        root / "before-single-turn.jsonl",
        [_assistant(_usage(cache_read=500), "2026-08-01T00:00:00Z")],
    )
    report = gp.run(roots=[root], split_at=SPLIT_AT)
    assert report["state"] == gp.STATE_NO_POST_FIX
    assert report["before"]["transcript_count"] == 1
    assert report["before"]["growth_samples"] == 0
    assert report["after"]["growth_samples"] == 0
