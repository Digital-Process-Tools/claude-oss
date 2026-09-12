"""#1499: `scripts/loop_cost_report.py` re-derives token spend from the Claude
Code transcripts under a projects directory.

One synthetic projects directory carries everything the assertions need:

* a developer transcript whose context climbs past the defect threshold -- the
  one that must be LISTED;
* a sub-manager transcript that stays under it -- the positive control for the
  "not listed" assertion (a listing that is empty because nothing was read at
  all would pass a bare "developer not listed" check too);
* one malformed line, which must be COUNTED and reported, never silently
  skipped;
* records before `--since`, which must not be summed.

The two non-measured states are exercised on their own fixtures: a readable
directory holding nothing after `--since` is `nothing-in-window`, and an absent
projects directory is `could-not-read`. Neither renders as `measured` with
zeros.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "loop_cost_report.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import loop_cost_report as lcr  # noqa: E402

PROJECT = "-Users-example-Documents-claude-oss"
SINCE = "2026-09-11T13:00:00Z"
OLD = "2026-09-10T00:00:00Z"
IN_WINDOW = "2026-09-11T20:00:00Z"


def _user(text, ts=IN_WINDOW):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


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


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for record in records:
        lines.append(record if isinstance(record, str) else json.dumps(record))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects" / PROJECT
    session = root / "sess-1.jsonl"
    # The main session: one record before the window (must not count), one in.
    _write_jsonl(
        session,
        [
            _user("/oss:run", ts=OLD),
            _assistant(50_000, ts=OLD),
            _assistant(60_000, cache_create=1_000, inp=5, out=20),
        ],
    )
    # A developer lane that climbs past the threshold.
    _write_jsonl(
        root / "sess-1" / "subagents" / "agent-dev.jsonl",
        [
            _user(
                "Implement issue #1234 in the repo named by `.oss.json`.\nlane: fix/1234"
            ),
            _assistant(100_000),
            _assistant(250_000),
            _assistant(450_000),
        ],
    )
    # A sub-manager that stays under the threshold -- the positive control -- with
    # one malformed line in the middle of it.
    _write_jsonl(
        root / "sess-1" / "subagents" / "agent-sub.jsonl",
        [
            _user("Run exactly one tick. spawn token: tick-abc123"),
            _assistant(150_000),
            "{this is not json",
            _assistant(180_000),
        ],
    )
    return tmp_path / "projects"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        check=False,
    )


# --- measured ---------------------------------------------------------------------


def test_measured_sums_only_records_in_the_window(projects):
    result = lcr.measure(projects, since=SINCE)
    assert result["state"] == "measured"
    by_kind = result["projects"][PROJECT]["kinds"]
    # main-session: only the in-window record: 60_000 + 1_000 + 5.
    assert by_kind["main-session"]["records"] == 1
    assert by_kind["main-session"]["context_sent"] == 61_005
    assert by_kind["main-session"]["max_context"] == 61_005
    assert by_kind["developer"]["agents"] == 1
    assert by_kind["developer"]["records"] == 3
    assert by_kind["developer"]["context_sent"] == 800_003
    assert by_kind["developer"]["max_context"] == 450_001
    assert by_kind["sub-manager"]["records"] == 2
    assert by_kind["sub-manager"]["max_context"] == 180_001


def test_shares_sum_to_one_across_kinds(projects):
    result = lcr.measure(projects, since=SINCE)
    kinds = result["projects"][PROJECT]["kinds"]
    total = result["projects"][PROJECT]["context_sent"]
    assert total == 61_005 + 800_003 + 150_001 + 180_001
    assert abs(sum(k["share"] for k in kinds.values()) - 1.0) < 1e-9


def test_context_bands_split_the_context_sent(projects):
    bands = lcr.measure(projects, since=SINCE)["projects"][PROJECT]["bands"]
    assert bands["<100k"] == 61_005
    assert bands["100-200k"] == 100_001 + 150_001 + 180_001
    assert bands["200-300k"] == 250_001
    assert bands["300-400k"] == 0
    assert bands[">400k"] == 450_001


def test_defects_list_the_developer_and_not_the_sub_manager(projects):
    result = lcr.measure(projects, since=SINCE, defect_at=400_000)
    defects = result["defects"]
    assert [d["kind"] for d in defects] == ["developer"]
    assert defects[0]["max_context"] == 450_001
    assert defects[0]["records"] == 3
    assert defects[0]["first_prompt"].startswith("Implement issue #1234")
    assert defects[0]["transcript"].endswith("agent-dev.jsonl")
    # Positive control: the sub-manager WAS read (its records are counted), and
    # lowering the threshold lists it too -- so "not listed" above is a verdict,
    # not an absence of reading.
    assert result["projects"][PROJECT]["kinds"]["sub-manager"]["records"] == 2
    lowered = lcr.measure(projects, since=SINCE, defect_at=170_000)
    assert sorted(d["kind"] for d in lowered["defects"]) == ["developer", "sub-manager"]


def test_malformed_lines_are_counted_and_reported(projects):
    result = lcr.measure(projects, since=SINCE)
    assert result["malformed_lines"] == 1
    assert [
        m["transcript"].endswith("agent-sub.jsonl") for m in result["malformed"]
    ] == [True]
    assert result["malformed"][0]["line"] == 3


def test_repo_dir_filter_keeps_only_that_project(projects):
    other = projects / "-Users-example-Documents-other"
    _write_jsonl(other / "s.jsonl", [_user("hi"), _assistant(10)])
    everything = lcr.measure(projects, since=SINCE)
    assert set(everything["projects"]) == {PROJECT, "-Users-example-Documents-other"}
    filtered = lcr.measure(projects, since=SINCE, repo_dir=PROJECT)
    assert set(filtered["projects"]) == {PROJECT}


def test_classify_covers_every_kind():
    assert lcr.classify("x spawn token: abc", subagent=True) == "sub-manager"
    assert lcr.classify("Run one release for this repo", subagent=True) == "releaser"
    assert lcr.classify("Read and follow commands/run/triage.md", subagent=True) == (
        "scheduler-step"
    )
    assert lcr.classify("anything", subagent=False) == "main-session"
    assert lcr.classify("Implement issue #1", subagent=True) == "developer"
    assert lcr.classify("Audit one diff", subagent=True) == "audit-review"
    assert lcr.classify("Review PR #3", subagent=True) == "audit-review"
    assert lcr.classify("Do something else", subagent=True) == "other"
    # The window is bounded: "issue" past 300 chars does not make a developer.
    assert lcr.classify("z" * 301 + " issue", subagent=True) == "other"


# --- the CLI ------------------------------------------------------------------------


def test_cli_text_prints_a_state_line_and_the_defect(projects):
    proc = _run("--projects-dir", str(projects), "--since", SINCE)
    assert proc.returncode == 0, proc.stderr
    assert "STATE: measured" in proc.stdout
    assert "malformed lines: 1" in proc.stdout
    assert "agent-dev.jsonl" in proc.stdout
    assert "developer" in proc.stdout
    assert ">400k" in proc.stdout


def test_cli_json_carries_the_state(projects):
    proc = _run("--projects-dir", str(projects), "--since", SINCE, "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["state"] == "measured"
    assert payload["malformed_lines"] == 1
    assert payload["defect_at"] == 400_000


# --- the two non-measured states --------------------------------------------------


def test_nothing_in_window_when_every_record_is_older_than_since(tmp_path):
    projects = tmp_path / "projects"
    _write_jsonl(
        projects / PROJECT / "s.jsonl", [_user("x", ts=OLD), _assistant(5, ts=OLD)]
    )
    result = lcr.measure(projects, since=SINCE)
    assert result["state"] == "nothing-in-window"
    assert result["defects"] == []
    proc = _run("--projects-dir", str(projects), "--since", SINCE)
    assert proc.returncode == 0
    assert "STATE: nothing-in-window" in proc.stdout


def test_could_not_read_when_the_projects_dir_is_absent(tmp_path):
    missing = tmp_path / "nope"
    result = lcr.measure(missing, since=SINCE)
    assert result["state"] == "could-not-read"
    assert "nope" in result["why"]
    proc = _run("--projects-dir", str(missing), "--since", SINCE, "--json")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["state"] == "could-not-read"


def test_could_not_read_is_not_nothing_in_window_when_the_dir_is_a_file(tmp_path):
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x", encoding="utf-8")
    assert lcr.measure(not_a_dir, since=SINCE)["state"] == "could-not-read"


def test_since_must_be_an_iso_timestamp():
    proc = _run("--projects-dir", "/nonexistent", "--since", "yesterday")
    assert proc.returncode == 2
    assert "since" in (proc.stdout + proc.stderr).lower()
