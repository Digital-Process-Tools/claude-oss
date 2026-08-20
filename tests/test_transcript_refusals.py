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
import pathlib
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


def test_parse_supertool_calls_finds_a_call_on_a_later_line_of_a_multiline_command():
    """Regression, found by review: a newline is bash's own default statement
    separator (this repo's own agent briefs model multi-line command blocks as
    the norm), but the call-boundary class only listed `;`, `&`, `|` -- so a
    supertool call sitting on any line after the first in a multi-line Bash
    command was silently dropped, the same undercount shape as the
    absolute-path/env-var gap this module's own docstring already documents
    having fixed once."""
    cmd = "gh api repos/OWNER/REPO/milestones -q '.[].title'\nsupertool 'gh-labels' 'gh-issues:per=100'"
    assert tr.parse_supertool_calls(cmd) == [["gh-labels", "gh-issues:per=100"]]


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
            pytest.skip(
                "chmod 000 did not deny listing on this platform/user (root, or a "
                "filesystem that ignores the mode bit) -- UNTESTED HERE: whether "
                "discover_transcripts reports an unreadable subtree in unreadable_dirs "
                "rather than silently omitting it"
            )
        assert any(str(blocked_sub) in d["path"] for d in unreadable_dirs)
        assert any(str(readable_sub / "agent-ok.jsonl") == str(f) for f in files)
    finally:
        os.chmod(blocked_sub, old_mode)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows chmod semantics differ")
def test_discover_transcripts_reports_a_root_whose_own_path_is_unreadable(tmp_path):
    """Regression, found by audit: `Path.exists()` swallows PermissionError on
    some interpreter versions (CLAUDE.md documents this exact class for
    `_read_config` in scripts/release_delta.py) and re-raises it on others --
    either way, checking a root's existence via `exists()`/`is_file()` with no
    handler around it either crashes discover_transcripts (breaking its "never
    raises" contract) or silently treats a root it could not even check as one
    that plainly does not exist, which renders identically to a genuinely
    empty root. Both are the third-state failure this module exists to avoid."""
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "sub"
    root.mkdir()
    old_mode = parent.stat().st_mode
    os.chmod(parent, 0o000)
    try:
        # Control: root.exists() is False either because exists() raised
        # (caught below) or because it swallowed the PermissionError -- both
        # are "the deny took". Only an unambiguous True means it did not, on
        # a platform/user where the mode bit is ignored (root, some
        # filesystems), and that case is skipped rather than asserted on.
        try:
            still_exists = root.exists()
        except OSError:
            still_exists = False
        if still_exists:
            pytest.skip(
                "chmod 000 on the parent did not block traversal on this platform/user "
                "(root, or a filesystem that ignores the mode bit) -- UNTESTED HERE: "
                "whether discover_transcripts reports a root whose own path could not "
                "be stat'd rather than silently treating it as absent"
            )
        files, unreadable_dirs = tr.discover_transcripts([root])
        assert files == []
        assert unreadable_dirs, "an inaccessible root must be named, not silently treated as absent"
    finally:
        os.chmod(parent, old_mode)


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


def test_default_transcripts_root_encodes_a_windows_backslash_cwd():
    """Regression, found by audit: os.getcwd() on Windows returns a
    backslash-separated path, and the first version of the encoding only
    substituted forward slash and dot, leaving backslashes and the drive
    colon untouched -- so the default guess silently pointed nowhere on
    Windows and a real absence there rendered identically to
    no-transcripts-found.

    Fixed once already and wrong again in a second way, caught by CI rather
    than locally: the first version of *this test* asserted no backslash
    anywhere in the whole rendered tail, including the OS path separators
    pathlib itself inserts between Path.home(), ".claude", "projects" and
    the encoded segment -- on a real Windows runner those separators ARE
    backslashes, so the assertion was wrong by construction on that
    platform, not merely wrong on the machine that wrote it. `root.name` is
    the final path component, derived by pathlib from parsed parts rather
    than string splitting, so it is separator-agnostic and names only the
    thing this function actually encodes. It also does not depend on
    Path.home(), which a Windows CI job can override via HOME.

    Positive control: exact equality, not just "no backslash" -- a
    regression that silently dropped the backslash substitution from the
    encoding would leave one in the segment, which the negative assertion
    alone also catches, but exact equality additionally fails if the
    substitution fires on the wrong character or the encoding regresses in
    some other way the negative half would not notice.
    """
    root = tr.default_transcripts_root(cwd=r"C:\Users\x\Documents\some.repo")
    segment = root.name
    assert "\\" not in segment, segment
    assert segment == "C--Users-x-Documents-some-repo", segment


def test_encode_cwd_segment_does_not_leave_a_windows_drive_prefix():
    """A second, deeper bug found while verifying the coordinator's PR-358
    correction, not merely the one CI reported: encoding backslash but not
    the drive colon left the encoded segment starting with "C:" for almost
    every real Windows cwd, and PureWindowsPath/WindowsPath treats a
    component shaped like "<letter>:..." as a drive-relative path -- joining
    it onto an already-built Path SILENTLY DROPS every segment joined before
    it. Reproduced directly against the actual PR-358 CI failure shape: the
    reported tail (\\.claude\\projects\\-Users-x-Documents-some-repo) already
    has no drive letter in it on a real Windows runner, which is this same
    bug already firing there, not a coincidence of the over-broad
    assertion. Exercised here with PureWindowsPath so it is testable
    without a Windows machine.
    """
    home = pathlib.PureWindowsPath("C:/Users/runneradmin")
    segment = tr._encode_cwd_segment(r"C:\Users\x\Documents\some.repo")
    root = home / ".claude" / "projects" / segment
    # Must-fire: before the colon fix, this exact join silently dropped
    # every component before the encoded segment.
    assert root.parts[:3] == ("C:\\", "Users", "runneradmin"), root.parts
    assert root.name == "C--Users-x-Documents-some-repo", root.name
    # Positive control, same fixture: two cwds differing only by drive
    # letter must not collapse onto the same encoded segment -- they did,
    # silently, before this fix (both became "-Users-x-...").
    other_drive = tr._encode_cwd_segment(r"D:\Users\x\Documents\some.repo")
    assert segment != other_drive, (segment, other_drive)


def test_main_exits_with_the_no_transcripts_state_code(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = tr.main(["--root", str(empty)])
    assert code == tr.EXIT_NO_TRANSCRIPTS
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "no-transcripts-found"


# ---------------------------------------------------------------------------
# #374: the agent filter must not be subtracted from transcripts_parsed.
# ---------------------------------------------------------------------------


def _three_agent_fixture(root):
    """Three transcripts, three different attributionAgent values, all valid.
    One matches the `oss:developer` filter used below."""
    _write_jsonl(root / "agent-dev.jsonl", [_assistant(attribution="oss:developer")])
    _write_jsonl(root / "agent-aud.jsonl", [_assistant(attribution="oss:auditor")])
    _write_jsonl(root / "agent-tri.jsonl", [_assistant(attribution="oss:triager")])


def test_filtered_run_does_not_report_the_filtered_out_files_as_unparsed(tmp_path):
    """#374. A filtered run reported `found: 3, parsed: 1, unreadable_files: []`
    over three files that all parsed cleanly, because the filter was applied
    before the count. `found - parsed` then reads as two parse failures, and the
    third state a reader would check to disprove that -- `unreadable_files` -- is
    empty, which makes the wrong reading the only available one.

    The invariant asserted here is the one that carries the meaning:
    `found - parsed == len(unreadable_files)`, always, filtered or not. The
    filtered subset gets a name of its own so the fact a filter ran is still
    legible rather than being erased by making the two numbers agree.
    """
    root = tmp_path / "root"
    root.mkdir()
    _three_agent_fixture(root)

    filtered = tr.run(roots=[root], agent_filter="oss:developer")
    assert filtered["state"] == "measured"
    assert filtered["transcripts_found"] == 3
    assert filtered["unreadable_files"] == []
    # The load-bearing assertion: nothing failed to parse, so the receipt must
    # not imply that anything did.
    assert filtered["transcripts_parsed"] == 3, (
        "a file the filter excluded was never offered to the parser and must "
        "not be counted as unparsed"
    )
    assert (
        filtered["transcripts_found"] - filtered["transcripts_parsed"]
        == len(filtered["unreadable_files"])
    )
    # ...and the filter is still visible, in its own named field, so a filtered
    # run cannot be mistaken for an unfiltered one now that found == parsed.
    assert filtered["agent_filter"] == "oss:developer"
    assert filtered["transcripts_matched_agent_filter"] == 1
    # The aggregates are the filtered subset -- that is what the filter is for.
    assert filtered["overall"]["count"] == 1
    assert list(filtered["by_agent"]) == ["oss:developer"]

    # Control 1: the same three files with no filter. found and parsed agree,
    # and the filter fields say "no filter was applied" rather than "zero
    # matched" -- an absence of a question, not an answer of nothing.
    unfiltered = tr.run(roots=[root])
    assert unfiltered["transcripts_found"] == 3
    assert unfiltered["transcripts_parsed"] == 3
    assert unfiltered["unreadable_files"] == []
    assert unfiltered["agent_filter"] is None
    assert unfiltered["transcripts_matched_agent_filter"] is None
    assert unfiltered["overall"]["count"] == 3


def test_a_filter_matching_nothing_is_not_the_same_as_no_filter(tmp_path):
    """The other half of #374's third state: zero matched is a finding, and it
    must not render like the field a run with no filter produces."""
    root = tmp_path / "root"
    root.mkdir()
    _three_agent_fixture(root)

    empty_match = tr.run(roots=[root], agent_filter="oss:nobody")
    assert empty_match["transcripts_found"] == 3
    assert empty_match["transcripts_parsed"] == 3
    assert empty_match["transcripts_matched_agent_filter"] == 0
    assert empty_match["agent_filter"] == "oss:nobody"
    assert empty_match["overall"]["count"] == 0

    no_filter = tr.run(roots=[root])
    assert no_filter["transcripts_matched_agent_filter"] is None


def test_no_transcripts_found_carries_the_filter_but_neither_count(tmp_path):
    """A contract pin, not a regression: this shape already held at the commit
    that added the field, and the finding it answers was in the prose beside it,
    which claimed three states for `transcripts_matched_agent_filter` without
    saying they are the `measured` state's three. Pinned here so the two cannot
    drift apart again -- in `no-transcripts-found` a `0` would claim a
    measurement over an empty set and a `None` would say no filter was passed
    when one was, so neither count is emitted and `state` is what a caller
    reads first."""
    empty = tmp_path / "empty"
    empty.mkdir()
    report = tr.run(roots=[empty], agent_filter="oss:developer")
    assert report["state"] == "no-transcripts-found"
    # The filter is echoed, so the run is still legible as a filtered one.
    assert report["agent_filter"] == "oss:developer"
    assert "transcripts_matched_agent_filter" not in report
    assert "transcripts_parsed" not in report
    # Control, same fixture shape: with files present the counts do appear, so
    # this test cannot pass by the report being empty or run() having failed.
    populated = tmp_path / "populated"
    _three_agent_fixture(populated)
    measured = tr.run(roots=[populated], agent_filter="oss:developer")
    assert measured["state"] == "measured"
    assert measured["transcripts_parsed"] == 3
    assert measured["transcripts_matched_agent_filter"] == 1


def test_a_filtered_run_still_fills_unreadable_files_for_a_real_failure(tmp_path):
    """Control 2: the gap between found and parsed must still open -- and be
    named -- when a file genuinely cannot be parsed, filter or no filter. A fix
    that made the two numbers agree unconditionally would pass the test above
    and break this one."""
    root = tmp_path / "root"
    root.mkdir()
    _three_agent_fixture(root)
    (root / "agent-broken.jsonl").write_text("{not json\n", encoding="utf-8")

    filtered = tr.run(roots=[root], agent_filter="oss:developer")
    assert filtered["transcripts_found"] == 4
    assert filtered["transcripts_parsed"] == 3
    assert [item["path"] for item in filtered["unreadable_files"]] == [
        str(root / "agent-broken.jsonl")
    ]
    assert (
        filtered["transcripts_found"] - filtered["transcripts_parsed"]
        == len(filtered["unreadable_files"])
    )
    assert filtered["transcripts_matched_agent_filter"] == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows chmod semantics differ")
def test_a_filtered_run_names_a_file_it_could_not_open_at_all(tmp_path):
    """Control 2, the stronger form: a file that cannot be *opened* (not merely
    one whose bytes do not parse) under a filtered run. Kept in its own test
    because a `pytest.skip` aborts the whole test function, and the deterministic
    assertions above must not be able to vanish behind this fixture's skip."""
    root = tmp_path / "root"
    root.mkdir()
    _three_agent_fixture(root)
    blocked = root / "agent-blocked.jsonl"
    _write_jsonl(blocked, [_assistant(attribution="oss:developer")])

    old_mode = blocked.stat().st_mode
    os.chmod(blocked, 0o000)
    try:
        # Control: attempt the exact operation analyze_transcript performs --
        # Path.read_text -- rather than trusting the chmod. Root and some
        # filesystems ignore the mode bit entirely.
        try:
            blocked.read_text(encoding="utf-8")
            deny_took = False
        except PermissionError:
            deny_took = True

        report = tr.run(roots=[root], agent_filter="oss:developer")
        if not deny_took:
            pytest.skip(
                "chmod 000 did not deny reading on this platform/user (root, or "
                "a filesystem that ignores the mode bit) -- UNTESTED HERE: "
                "whether a filtered run still names a file it could not open in "
                "unreadable_files rather than folding it into the parsed count"
            )
        assert report["transcripts_found"] == 4
        assert report["transcripts_parsed"] == 3
        assert [item["path"] for item in report["unreadable_files"]] == [str(blocked)]
        # The one that matched the filter is the readable dev transcript.
        assert report["transcripts_matched_agent_filter"] == 1
    finally:
        os.chmod(blocked, old_mode)


def test_main_exits_zero_when_measured(tmp_path, capsys):
    root = tmp_path / "root"
    _write_jsonl(root / "agent-10.jsonl", [_assistant(attribution="oss:developer")])
    code = tr.main(["--root", str(root)])
    assert code == tr.EXIT_MEASURED
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "measured"
