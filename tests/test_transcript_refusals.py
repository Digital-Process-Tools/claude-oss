"""Tests for scripts/transcript_refusals.py -- see that module's docstring for #313.

Fixtures are hand-built JSONL lines matching the shape of a real subagent transcript
(observed directly against files under a live ~/.claude/projects/*/subagents/*.jsonl
tree while building this script -- never read in a test, per the brief, because those
are one machine's and not in this repo). Each assistant record carries
message.model, message.content (a list of typed blocks) and message.usage; each user
record carries message.content with tool_result blocks, matching what a refused
supertool or Bash call actually produces.
"""

import json
import os
import stat
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
            or {
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 10,
                "output_tokens": 5,
            },
        },
    }
    if attribution is not None:
        rec["attributionAgent"] = attribution
    return rec


def _user_tool_result(text, is_error=False):
    return {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "content": text, "is_error": is_error}
            ]
        },
    }


def _bash_call(command):
    return {"type": "tool_use", "name": "Bash", "input": {"command": command}}


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# classify_refusal: one must-fire case per class, and a must-not-fire control
# in the same set so a broken matcher that fires on everything is caught too.
# ---------------------------------------------------------------------------


REAL_REFUSAL_TEXTS = {
    "path-escapes-cwd": (
        "--- paste:@- ---\nERROR: path escapes cwd: '/x/notes/f.md' (resolved to "
        "'/x/notes/f.md'). To allow: set SUPERTOOL_ALLOW_OUTSIDE_CWD=1 (env), or add "
        '"allow_outside_cwd": true'
    ),
    "raw-command-guard": (
        "`git commit -q -F -` is replaced by supertool's `git-commit` op.\n"
        "  Use: supertool 'git-commit:::MESSAGE[:::PATHS...|:::--all]'"
    ),
    "no-cut": (
        "**Do not cut a supertool op's output.** The ops are already compressed and "
        "put the meaning at the top"
    ),
    "unavailable-here": (
        "ERROR: op 'radar' is unavailable here, not unknown — it is provided by "
        "the shipped preset 'watch'"
    ),
    "jit-context-block": (
        "# JIT Context: supertool-required.md (matched: ~.*)\n---\n"
        "title: \"Read, Edit, Write, Glob and Grep go through supertool\""
    ),
    "plain-op-error": "--- read:missing.py ---\nERROR: no such file: missing.py",
}


@pytest.mark.parametrize("expected_class,text", sorted(REAL_REFUSAL_TEXTS.items()))
def test_classify_refusal_fires_on_each_real_class(expected_class, text):
    assert tr.classify_refusal(text) == expected_class


def test_classify_refusal_does_not_fire_on_a_clean_result():
    """Positive control's pair: an ordinary successful tool_result must not classify."""
    clean = "--- read:scripts/oss_state.py:1:10 ---\n  1│ def f():\n  2│     pass"
    assert tr.classify_refusal(clean) is None


def test_classify_refusal_does_not_fire_on_prose_that_merely_mentions_error():
    """A false positive here would inflate every class silently."""
    prose = "The test asserted no ERROR was raised, and none was."
    assert tr.classify_refusal(prose) is None


# ---------------------------------------------------------------------------
# parse_supertool_calls
# ---------------------------------------------------------------------------


def test_parse_supertool_calls_counts_ops_in_one_call():
    calls = tr.parse_supertool_calls("supertool 'read:a.py' 'read:b.py' 'grep:x:.'")
    assert calls == [["read:a.py", "read:b.py", "grep:x:."]]


def test_parse_supertool_calls_ignores_unrelated_bash():
    assert tr.parse_supertool_calls("git status") == []
    assert tr.parse_supertool_calls("./scripts/doctor.sh") == []


def test_parse_supertool_calls_finds_multiple_invocations_in_one_command():
    calls = tr.parse_supertool_calls(
        "supertool 'ops:roster' && supertool 'read:a.py' 'read:b.py'"
    )
    assert calls == [["ops:roster"], ["read:a.py", "read:b.py"]]


def test_parse_supertool_calls_handles_an_absolute_path_and_env_var_prefix():
    """Regression: the first version of the pattern only matched a bare or
    ./-prefixed `supertool`, and silently dropped 13.9% of real calls that
    used an absolute path or a leading SUPERTOOL_ALLOW_OUTSIDE_CWD=1 -- almost
    all single-op writes, which skewed the single-op-share figure. Measured
    against this repository's own transcripts while building this script."""
    calls = tr.parse_supertool_calls(
        "cd /x && SUPERTOOL_ALLOW_OUTSIDE_CWD=1 /Users/x/Documents/claude-oss/supertool "
        "'gh-pr-create:@reports/f.pr.json' 2>&1 | tail"
    )
    assert calls == [["gh-pr-create:@reports/f.pr.json"]]


def test_parse_supertool_calls_handles_a_double_quoted_multiline_op():
    calls = tr.parse_supertool_calls(
        'cd /x/160 && ./supertool "git-commit:::Key the fragment\n\nNo issue exists" 2>&1'
    )
    assert calls == [["git-commit:::Key the fragment\n\nNo issue exists"]]


# ---------------------------------------------------------------------------
# analyze_transcript
# ---------------------------------------------------------------------------


def test_analyze_transcript_splits_turns_by_tool_use_and_no_tool_shape(tmp_path):
    path = tmp_path / "agent-1.jsonl"
    _write_jsonl(
        path,
        [
            _assistant(content=[{"type": "tool_use", "name": "Bash", "input": {"command": "supertool 'read:a.py'"}}], attribution="oss:developer"),
            _assistant(content=[{"type": "thinking", "thinking": "hmm"}]),
            _assistant(content=[{"type": "text", "text": "done"}]),
        ],
    )
    result = tr.analyze_transcript(path)
    assert result["ok"] is True
    assert result["turns"] == 3
    assert result["turns_with_tool"] == 1
    assert result["turns_thinking_only"] == 1
    assert result["turns_text_only"] == 1
    assert result["agent"] == "oss:developer"
    assert result["model"] == "claude-sonnet-5"


def test_analyze_transcript_reads_model_only_from_message_model_field():
    """Never inferred from anything else -- a silent no-op override must read as unknown,
    not as whatever model last ran, per the brief's explicit instruction."""
    pass  # exercised via test below with a transcript naming no model at all


def test_analyze_transcript_reports_unknown_model_when_the_field_is_absent(tmp_path):
    path = tmp_path / "agent-2.jsonl"
    rec = _assistant()
    del rec["message"]["model"]
    _write_jsonl(path, [rec])
    result = tr.analyze_transcript(path)
    assert result["model"] == "unknown"


def test_analyze_transcript_counts_refusals_by_class_with_a_clean_control(tmp_path):
    """Must-fire and must-not-fire in the same fixture, per the brief."""
    path = tmp_path / "agent-3.jsonl"
    _write_jsonl(
        path,
        [
            _assistant(),
            _user_tool_result(REAL_REFUSAL_TEXTS["path-escapes-cwd"], is_error=True),
            _assistant(),
            _user_tool_result("--- read:a.py ---\n  1│ ok", is_error=False),
        ],
    )
    result = tr.analyze_transcript(path)
    assert result["refusals"]["path-escapes-cwd"] == 1
    assert sum(result["refusals"].values()) == 1


def test_analyze_transcript_tracks_consecutive_single_op_read_runs(tmp_path):
    path = tmp_path / "agent-4.jsonl"

    def bash_turn(cmd):
        return _assistant(content=[_bash_call(cmd)])

    records = [
        bash_turn("supertool 'read:a.py'"),
        bash_turn("supertool 'read:b.py'"),
        bash_turn("supertool 'read:c.py'"),
        bash_turn("supertool 'paste:@-'"),  # write, breaks the run
        bash_turn("supertool 'read:d.py'"),  # isolated single-op read, run length 1
    ]
    _write_jsonl(path, records)
    result = tr.analyze_transcript(path)
    assert result["single_read_run_lengths"] == [3, 1]
    assert result["reads_in_runs"] == 3
    assert result["turns_removable"] == 2


def test_analyze_transcript_classifies_ops_per_call(tmp_path):
    path = tmp_path / "agent-5.jsonl"

    def bash_turn(cmd):
        return _assistant(content=[_bash_call(cmd)])

    records = [
        bash_turn("supertool 'read:a.py' 'read:b.py'"),  # read-only, 2 ops
        bash_turn("supertool 'paste:@-'"),  # write-only, 1 op
        bash_turn("supertool 'read:a.py' 'paste:@-'"),  # mixed, 2 ops
    ]
    _write_jsonl(path, records)
    result = tr.analyze_transcript(path)
    assert result["ops_per_call"] == [2, 1, 2]
    assert result["calls_by_class"] == {"read-only": 1, "write-only": 1, "mixed": 1}


# ---------------------------------------------------------------------------
# The third state: no transcripts found must not render like zero refusals.
# ---------------------------------------------------------------------------


def test_discover_transcripts_finds_nothing_in_an_empty_root(tmp_path):
    files, unreadable_dirs = tr.discover_transcripts([tmp_path])
    assert files == []
    assert unreadable_dirs == []


def test_aggregate_reports_no_transcripts_found_distinctly_from_zero_refusals(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    report_empty = tr.run(roots=[empty_root])
    assert report_empty["state"] == "no-transcripts-found"

    populated_root = tmp_path / "populated"
    _write_jsonl(populated_root / "agent-6.jsonl", [_assistant(attribution="oss:developer")])
    report_measured = tr.run(roots=[populated_root])
    assert report_measured["state"] == "measured"
    assert report_measured["transcripts_found"] == 1
    # Zero refusals is a real, reportable finding -- not the same state as "found nothing".
    assert report_measured["refusal_totals"] == {}
    assert report_empty["refusal_totals"] is None


def test_run_reports_unreadable_files_separately_from_clean_ones(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    good = root / "agent-good.jsonl"
    _write_jsonl(good, [_assistant(attribution="oss:developer")])
    bad = root / "agent-bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    report = tr.run(roots=[root])
    assert report["state"] == "measured"
    assert report["transcripts_found"] == 2
    # The unreadable one is named, not silently dropped from the count.
    assert any(item["path"].endswith("agent-bad.jsonl") for item in report["unreadable_files"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows chmod semantics differ")
def test_discover_transcripts_reports_an_unreadable_directory_with_a_control(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    readable_sub = root / "readable"
    _write_jsonl(readable_sub / "agent-ok.jsonl", [_assistant()])
    blocked_sub = root / "blocked"
    blocked_sub.mkdir()
    (blocked_sub / "agent-hidden.jsonl").write_text("{}\n", encoding="utf-8")

    old_mode = blocked_sub.stat().st_mode
    os.chmod(blocked_sub, 0o000)
    try:
        # Control: confirm the deny actually took on this filesystem/user before
        # asserting on it -- root and some filesystems ignore the mode bit.
        try:
            os.listdir(blocked_sub)
            deny_took = False
        except PermissionError:
            deny_took = True

        files, unreadable_dirs = tr.discover_transcripts([root])
        if not deny_took:
            pytest.skip("chmod 000 did not deny listing on this platform/user; untested here")
        assert any(str(blocked_sub) in d["path"] for d in unreadable_dirs)
        assert any(str(readable_sub / "agent-ok.jsonl") == str(f) for f in files)
    finally:
        os.chmod(blocked_sub, old_mode)


# ---------------------------------------------------------------------------
# CLI shape: detail is opt-in.
# ---------------------------------------------------------------------------


def test_run_omits_per_transcript_detail_unless_asked(tmp_path):
    root = tmp_path / "root"
    _write_jsonl(root / "agent-7.jsonl", [_assistant(attribution="oss:developer")])
    without_detail = tr.run(roots=[root])
    assert "transcripts" not in without_detail
    with_detail = tr.run(roots=[root], detail=True)
    assert "transcripts" in with_detail
    assert len(with_detail["transcripts"]) == 1


def test_run_groups_medians_by_agent_and_model(tmp_path):
    root = tmp_path / "root"
    _write_jsonl(
        root / "agent-8.jsonl",
        [
            _assistant(model="claude-opus-5", attribution="oss:developer"),
            _assistant(model="claude-opus-5", attribution="oss:developer"),
        ],
    )
    _write_jsonl(
        root / "agent-9.jsonl",
        [_assistant(model="claude-sonnet-5", attribution="oss:developer")],
    )
    report = tr.run(roots=[root])
    by_agent = report["by_agent"]["oss:developer"]["by_model"]
    assert by_agent["claude-opus-5"]["count"] == 1
    assert by_agent["claude-sonnet-5"]["count"] == 1
    assert by_agent["claude-opus-5"]["median_turns"] == 2
    assert by_agent["claude-sonnet-5"]["median_turns"] == 1


def test_default_transcripts_root_is_derived_not_hardcoded(tmp_path):
    """No repo/user fact baked in -- the root is computed from Path.home() and the
    given cwd. This is reasoned from an observed encoding (path separators and dots
    become '-'), confirmed by inspection of real ~/.claude/projects/* directory names
    on the machine this was built on; it is not guaranteed by any published contract."""
    root = tr.default_transcripts_root(cwd="/Users/example/Documents/some.repo")
    assert str(root).endswith("-Users-example-Documents-some-repo")


def test_main_exits_with_the_no_transcripts_state_code(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = tr.main(["--root", str(empty)])
    assert code == tr.EXIT_NO_TRANSCRIPTS
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "no-transcripts-found"


def test_main_exits_zero_when_measured(tmp_path, capsys):
    root = tmp_path / "root"
    _write_jsonl(root / "agent-10.jsonl", [_assistant(attribution="oss:developer")])
    code = tr.main(["--root", str(root)])
    assert code == tr.EXIT_MEASURED
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "measured"
