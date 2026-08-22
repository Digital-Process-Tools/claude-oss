"""Tests for #498's lane-length and orientation-byte measurement, added to
scripts/transcript_refusals.py rather than a new parser -- see the developer
report for why. Measured after a lane completes, never surfaced in-context.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import transcript_refusals as tr  # noqa: E402


def _assistant(model="claude-sonnet-5", content=None, usage=None, attribution=None):
    rec = {
        "type": "assistant",
        "message": {
            "model": model,
            "content": content if content is not None else [{"type": "text", "text": "hi"}],
            "usage": usage
            or {"cache_read_input_tokens": 1, "cache_creation_input_tokens": 1, "output_tokens": 1},
        },
    }
    if attribution is not None:
        rec["attributionAgent"] = attribution
    return rec


def _tool_use_turn(command, attribution="oss:developer"):
    return _assistant(
        content=[{"type": "tool_use", "name": "Bash", "input": {"command": command}}],
        attribution=attribution,
    )


def _user_tool_result(text):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": text, "is_error": False}]},
    }


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _lane(n_calls, byte_sizes):
    # n_calls tool-call/result pairs; byte_sizes[i] is the byte length of the
    # i-th tool_result content, in order.
    records = []
    for i in range(n_calls):
        records.append(_tool_use_turn("supertool " + repr("read:file{0}.py".format(i))))
        records.append(_user_tool_result("x" * byte_sizes[i]))
    return records


# ---------------------------------------------------------------------------
# analyze_transcript records the byte size of every tool_result, in order.
# ---------------------------------------------------------------------------


def test_analyze_transcript_records_tool_result_bytes_in_order(tmp_path):
    path = tmp_path / "agent.jsonl"
    _write_jsonl(path, _lane(3, [100, 50, 10]))
    result = tr.analyze_transcript(path)
    assert result["ok"]
    assert result["tool_result_bytes"] == [100, 50, 10]


def test_tool_result_bytes_counts_utf8_bytes_not_characters(tmp_path):
    """A positive control for the encoding choice: a multi-byte character must
    count as more than one byte, or an orientation share computed from this
    field would understate non-ASCII-heavy reads."""
    path = tmp_path / "agent.jsonl"
    _write_jsonl(path, _lane(1, [0]))
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["message"]["content"][0]["content"] = chr(233) * 5  # 5 chars, 10 bytes in utf-8
    lines[1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = tr.analyze_transcript(path)
    assert result["tool_result_bytes"] == [10]


# ---------------------------------------------------------------------------
# decile_shares: bytes-by-decile-of-a-lane own length, the #498 finding.
# ---------------------------------------------------------------------------


def test_decile_shares_is_no_data_when_no_tool_calls_at_all(tmp_path):
    # Third state: a group of transcripts that carried no tool_result at all
    # must not render identically to one whose calls returned zero bytes each
    # -- no-data and measured-all-zero are different findings.
    path = tmp_path / "agent.jsonl"
    _write_jsonl(path, [_assistant()])
    analyses = [tr.analyze_transcript(path)]
    shares = tr.decile_shares(analyses)
    assert shares["state"] == "no-data"
    assert "deciles" not in shares


def test_decile_shares_measured_with_a_lopsided_lane(tmp_path):
    # A lane whose early calls return far more than its late ones -- the
    # shape #498 measured -- must show up as a first-fifth share well above
    # the 20% an even split would produce.
    path = tmp_path / "agent.jsonl"
    # 10 calls: first two return 1000 bytes each, remaining eight return 10
    # bytes each. Total = 2080 bytes; decile 0 (call 0 alone) carries 1000 of
    # 2080 -- overwhelmingly more than an even 10%/decile.
    sizes = [1000, 1000] + [10] * 8
    _write_jsonl(path, _lane(10, sizes))
    analyses = [tr.analyze_transcript(path)]
    shares = tr.decile_shares(analyses)
    assert shares["state"] == "measured"
    assert len(shares["deciles"]) == 10
    total_bytes = sum(sizes)
    assert shares["deciles"][0]["bytes"] == 1000
    assert shares["first_fifth_byte_share"] == pytest.approx(2000 / total_bytes)
    # Control: call counts are flat across deciles even though bytes are not
    # -- exactly the asymmetry #498 measured (bytes skew early, calls do not).
    assert all(d["calls"] == 1 for d in shares["deciles"])


# ---------------------------------------------------------------------------
# turns-over-threshold: the lane-length half of #498.
# ---------------------------------------------------------------------------


def test_summarize_group_reports_turns_over_threshold(tmp_path):
    short = tmp_path / "short.jsonl"
    long_ = tmp_path / "long.jsonl"
    _write_jsonl(short, [_assistant()] * 5)
    _write_jsonl(long_, [_assistant()] * 200)
    analyses = [tr.analyze_transcript(short), tr.analyze_transcript(long_)]
    summary = tr._summarize_group(analyses, turns_threshold=140)
    assert summary["turns_threshold"] == 140
    assert summary["turns_over_threshold_count"] == 1
    assert summary["turns_over_threshold_share"] == pytest.approx(0.5)


def test_run_uses_the_default_threshold_and_cli_can_override(tmp_path):
    root = tmp_path / "root"
    _write_jsonl(root / "long.jsonl", [_assistant(attribution="oss:developer")] * 200)
    default_report = tr.run(roots=[root])
    assert default_report["overall"]["turns_threshold"] == tr.DEFAULT_TURNS_THRESHOLD
    assert default_report["overall"]["turns_over_threshold_count"] == 1

    lenient_report = tr.run(roots=[root], turns_threshold=1000)
    assert lenient_report["overall"]["turns_over_threshold_count"] == 0


def test_cli_turns_threshold_flag(tmp_path, capsys):
    root = tmp_path / "root"
    _write_jsonl(root / "long.jsonl", [_assistant(attribution="oss:developer")] * 200)
    code = tr.main(["--root", str(root), "--turns-threshold", "1000"])
    assert code == tr.EXIT_MEASURED
    out = json.loads(capsys.readouterr().out)
    assert out["overall"]["turns_threshold"] == 1000
    assert out["overall"]["turns_over_threshold_count"] == 0
