"""#1499: `scripts/agent_cost.py` measures one agent's own token spend from its
transcript, so a developer lane's report carries a measured `cost` block rather
than a recalled one.

The agent cannot read a context counter from the harness; what it can do is
name a string only its own tool calls carried (its worktree path, its branch)
and let the script find the transcript holding it. One synthetic projects
directory carries:

* the lane transcript that MUST be found (its Bash calls name `fix/4242`);
* a second lane in the same session that names `fix/9999` -- the positive
  control that the match is on the string, not on "the newest file";
* a sub-manager transcript whose `Agent` spawn prompt names `fix/4242` --
  a spawner's brief describes another agent's work, so `Agent` inputs are
  never matched -- and whose own Bash call names `fix/1111`, so a string
  several transcripts carry is `ambiguous`, never a confident pick of one.

`no-match` and `could-not-read` are exercised on their own fixtures; neither
renders as `measured` with zeros.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "agent_cost.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_cost  # noqa: E402

PROJECT = "-Users-example-Documents-claude-oss"
SESSION = "11111111-2222-3333-4444-555555555555"


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(cache_read, command=None, out=10, tool="Bash"):
    content = [{"type": "text", "text": "ok"}]
    if command is not None:
        content.append(
            {
                "type": "tool_use",
                "id": "toolu_x",
                "name": tool,
                "input": {"command": command},
            }
        )
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": content,
            "usage": {
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": 100,
                "input_tokens": 1,
                "output_tokens": out,
            },
        },
    }


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"
    sub = root / PROJECT / SESSION / "subagents"
    _write_jsonl(
        sub / "agent-aaaa.jsonl",
        [
            _user("Implement issue #4242 in a worktree"),
            _assistant(60_000, "git worktree add ../wt/4242 -b fix/4242"),
            _assistant(150_000, "cat scripts/x.py"),
            _assistant(450_000, "git commit -m 'fix/4242 done'"),
            _assistant(300_000),
        ],
    )
    (sub / "agent-aaaa.meta.json").write_text(
        json.dumps({"agentType": "oss:developer", "toolUseId": "toolu_a"}),
        encoding="utf-8",
    )
    _write_jsonl(
        sub / "agent-bbbb.jsonl",
        [
            _user("Implement issue #9999"),
            _assistant(70_000, "git checkout -b fix/9999"),
            _assistant(90_000, "echo done"),
        ],
    )
    _write_jsonl(
        sub / "agent-cccc.jsonl",
        [
            _user("Run one tick, spawn token abc"),
            _assistant(80_000, "Implement #4242 on branch fix/4242", tool="Agent"),
            _assistant(85_000, "git branch -a | grep fix/1111"),
        ],
    )
    (sub / "agent-cccc.meta.json").write_text(
        json.dumps({"agentType": "oss:sub-manager"}), encoding="utf-8"
    )
    _write_jsonl(
        root / PROJECT / (SESSION + ".jsonl"),
        [_user("start"), _assistant(50_000, "ls")],
    )
    return root


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
    )


def test_a_unique_match_is_measured_from_that_transcript_only(projects):
    result = agent_cost.measure(projects, "fix/4242", session=SESSION)
    assert result["state"] == agent_cost.STATE_MEASURED
    assert result["transcript"].endswith("agent-aaaa.jsonl")
    assert result["agent_type"] == "oss:developer"
    assert result["turns"] == 4
    assert result["bash_calls"] == 3
    assert result["tool_calls"] == 3
    assert result["max_context"] == 450_101
    assert result["last_context"] == 300_101
    assert result["output_tokens"] == 40
    assert result["over_threshold"] is True
    assert result["threshold"] == agent_cost.DEFAULT_THRESHOLD


def test_the_other_lane_is_the_positive_control_and_stays_under(projects):
    result = agent_cost.measure(projects, "fix/9999", session=SESSION)
    assert result["state"] == agent_cost.STATE_MEASURED
    assert result["transcript"].endswith("agent-bbbb.jsonl")
    assert result["agent_type"] == "unknown"
    assert result["max_context"] == 90_101
    assert result["over_threshold"] is False


def test_a_string_two_transcripts_carry_is_ambiguous_not_a_pick(projects):
    # `fix/4242` alone is unique; every lane's Bash calls carry `fix/`.
    result = agent_cost.measure(projects, "fix/", session=SESSION)
    assert result["state"] == agent_cost.STATE_AMBIGUOUS
    assert len(result["candidates"]) == 3
    assert "max_context" not in result


def test_no_transcript_carrying_the_string_is_no_match(projects):
    result = agent_cost.measure(projects, "fix/0000", session=SESSION)
    assert result["state"] == agent_cost.STATE_NO_MATCH
    assert result["searched"] == 4


def test_a_missing_projects_dir_is_could_not_read_not_zero(tmp_path):
    result = agent_cost.measure(tmp_path / "absent", "fix/4242", session=SESSION)
    assert result["state"] == agent_cost.STATE_COULD_NOT_READ
    assert "absent" in result["why"]


def test_without_a_session_every_project_dir_is_searched(projects):
    result = agent_cost.measure(projects, "fix/4242", session=None)
    assert result["state"] == agent_cost.STATE_MEASURED
    assert result["transcript"].endswith("agent-aaaa.jsonl")


def test_a_spawn_prompt_naming_the_branch_is_not_a_match(projects):
    # agent-cccc's Agent call says "fix/4242"; only agent-aaaa's own Bash
    # calls do. Excluding Agent inputs is what keeps the lane unique.
    result = agent_cost.measure(projects, "fix/4242", session=SESSION)
    assert result["state"] == agent_cost.STATE_MEASURED
    assert result["transcript"].endswith("agent-aaaa.jsonl")
    result = agent_cost.measure(projects, "branch fix/4242", session=SESSION)
    assert result["state"] == agent_cost.STATE_NO_MATCH


def test_the_match_is_on_tool_input_not_on_prose(projects):
    # The user prompt of agent-aaaa says "#4242"; only its tool calls say
    # "fix/4242". A match on the prompt text alone would also hit agent-cccc's
    # spawn prompt shape, so the search reads tool_use inputs only.
    result = agent_cost.measure(projects, "issue #4242", session=SESSION)
    assert result["state"] == agent_cost.STATE_NO_MATCH


def test_cli_json_is_a_report_cost_block(projects):
    proc = _run(
        "--projects-dir",
        str(projects),
        "--session",
        SESSION,
        "--match",
        "fix/4242",
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    block = json.loads(proc.stdout)
    assert block["state"] == "measured"
    assert block["max_context"] == 450_101
    assert "note" in block


def test_cli_exit_codes_follow_the_state(projects):
    assert (
        _run(
            "--projects-dir", str(projects), "--session", SESSION, "--match", "fix/9999"
        ).returncode
        == 0
    )
    assert (
        _run(
            "--projects-dir", str(projects), "--session", SESSION, "--match", "fix/0000"
        ).returncode
        == 1
    )
    assert (
        _run(
            "--projects-dir", str(projects), "--session", SESSION, "--match", "fix/"
        ).returncode
        == 1
    )
    assert (
        _run(
            "--projects-dir", str(projects / "absent"), "--match", "fix/4242"
        ).returncode
        == 2
    )


def test_into_matches_on_the_report_path_and_writes_the_block(projects, tmp_path):
    # The lane wrote its report at a path only its own calls name; --into
    # uses that path as the match and completes the report in place.
    report = tmp_path / "reports" / "4242.json"
    report.parent.mkdir()
    report.write_text(
        json.dumps({"schema_version": 14, "issue": 4242}), encoding="utf-8"
    )
    path = projects / PROJECT / SESSION / "subagents" / "agent-aaaa.jsonl"
    with open(str(path), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(_assistant(200_000, "paste:" + str(report))) + "\n")
    proc = _run(
        "--projects-dir", str(projects), "--session", SESSION, "--into", str(report)
    )
    assert proc.returncode == 0, proc.stderr
    assert "written into" in proc.stderr
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["issue"] == 4242
    assert written["cost"]["state"] == "measured"
    assert written["cost"]["match"] == str(report)
    assert written["cost"]["turns"] == 5


def test_a_path_typed_through_a_variable_falls_back_to_its_basename(projects, tmp_path):
    # Dogfooded: `--into $S/report.json` puts `$S/report.json` in the tool
    # input, never the full path. The basename is the next most specific
    # string the lane typed, and the fallback says it was used.
    report = tmp_path / "elsewhere" / "fix-4242-20260912T114300Z.json"
    report.parent.mkdir()
    report.write_text("{}", encoding="utf-8")
    path = projects / PROJECT / SESSION / "subagents" / "agent-aaaa.jsonl"
    with open(str(path), "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(_assistant(1, "paste:$S/fix-4242-20260912T114300Z.json")) + "\n"
        )
    result = agent_cost.measure(
        projects, str(report), session=SESSION, basename_fallback=True
    )
    assert result["state"] == agent_cost.STATE_MEASURED
    assert result["matched_on"] == "basename"
    assert result["transcript"].endswith("agent-aaaa.jsonl")
    # Off by default: `basename("branch fix/4242")` is `4242`, a wider
    # question than the one asked, not a narrower one.
    result = agent_cost.measure(projects, str(report), session=SESSION)
    assert result["state"] == agent_cost.STATE_NO_MATCH
    full = agent_cost.measure(projects, "fix/4242", session=SESSION)
    assert full["matched_on"] == "match"


def test_into_a_missing_report_still_prints_and_exits_2(projects, tmp_path):
    report = tmp_path / "absent.json"
    proc = _run(
        "--projects-dir",
        str(projects),
        "--session",
        SESSION,
        "--into",
        str(report),
        "--match",
        "fix/4242",
    )
    assert proc.returncode == 2
    assert "does not exist" in proc.stderr
    assert "measured" in proc.stdout


def test_neither_match_nor_into_is_a_usage_error(projects):
    proc = _run("--projects-dir", str(projects))
    assert proc.returncode == 2
    assert "one of --match or --into" in proc.stderr


def test_a_malformed_line_is_counted_not_silently_skipped(projects):
    path = projects / PROJECT / SESSION / "subagents" / "agent-aaaa.jsonl"
    with open(str(path), "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    result = agent_cost.measure(projects, "fix/4242", session=SESSION)
    assert result["state"] == agent_cost.STATE_MEASURED
    assert result["malformed"] == 1
