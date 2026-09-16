"""``--per-issue`` -- tokens per issue resolved, not tokens per tick (#1618).

`scripts/loop_cost_report.py` already sums spend by project, agent kind and
context band. This is the join CLAUDE.md's token-economy section names as
the real metric but that nothing computed: spend attributed to the issue(s)
each transcript's own first prompt (or, for an auditor, its worktree/branch;
or, for a tick-review/tick-merge spawn, a pull-request-to-issue map) names,
with an explicit ``unattributed`` bucket for everything else -- never folded
silently into a neighbour, per
``.claude/jit-context/paths/00-manual/counter-scripts-silent-gaps.md``.

Positive/negative control pairing, per fixture:
* a developer transcript naming one issue directly IS attributed;
* an Explore transcript naming nothing attributable is NOT, and lands in
  ``unattributed`` rather than being dropped.
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
IN_WINDOW = "2026-09-11T20:00:00Z"


def _user(text, ts=IN_WINDOW):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def _assistant(
    cache_read, cache_create=0, inp=1, out=10, ts=IN_WINDOW, attribution=None
):
    record = {
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
    if attribution is not None:
        record["attributionAgent"] = attribution
    return record


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        check=False,
    )


# --- issue-number extraction (the four phrasings #1618 cites) ----------------------


def test_issue_number_extraction_covers_the_four_observed_phrasings():
    assert lcr.attribute_issues("Issue: 1477.\nDo the thing.") == (
        [1477],
        "prompt-issue-number",
    )
    assert lcr.attribute_issues("Issues: 1389, 1499, 1576.\nDo the thing.") == (
        [1389, 1499, 1576],
        "prompt-issue-number",
    )
    assert lcr.attribute_issues(
        "Recon issues 1361 and 1511 in the claude-oss repo.\nLocate, do not design."
    ) == ([1361, 1511], "prompt-issue-number")
    assert lcr.attribute_issues(
        "Issue #1566: release_trigger.py's stale-head guard.\nImplement it."
    ) == ([1566], "prompt-issue-number")


def test_issue_number_extraction_is_bounded_not_a_whole_prompt_scan():
    # A number appearing well past the "issue" mention, in unrelated prose,
    # must not be swept in -- the window is bounded, per test_classify_covers_
    # every_kind's own "z" * 301 precedent for this module's other bounded scan.
    far = "Issue: 142.\n" + ("filler " * 40) + "unrelated 999"
    assert lcr.attribute_issues(far) == ([142], "prompt-issue-number")


# --- worktree / branch attribution (oss:auditor) ------------------------------------


def test_worktree_path_attributes_the_auditor():
    prompt = "Audit the diff in worktree /Users/example/claude-oss-wt/1583."
    assert lcr.attribute_issues(prompt) == ([1583], "worktree-or-branch")


def test_branch_name_attributes_the_auditor_when_no_worktree_path_is_named():
    prompt = "Audit one diff. Look at branch fix/1583 for the change."
    assert lcr.attribute_issues(prompt) == ([1583], "worktree-or-branch")


# --- pull-request-to-issue map (oss:tick-review / oss:tick-merge) ------------------


def test_pr_number_resolves_through_the_map_when_one_is_given():
    prompt = "Merge pull request #1587 once CI is green."
    assert lcr.attribute_issues(prompt, pr_issue_map={1587: [1580]}) == (
        [1580],
        "pr-to-issue-map",
    )


def test_pr_number_without_a_map_is_unattributed():
    prompt = "Merge pull request #1587 once CI is green."
    assert lcr.attribute_issues(prompt) == ([], "unattributed")


def test_pr_number_not_present_in_the_given_map_is_unattributed():
    prompt = "Merge pull request #1587 once CI is green."
    assert lcr.attribute_issues(prompt, pr_issue_map={9999: [1]}) == (
        [],
        "unattributed",
    )


# --- the third state: unattributed is a line, never a drop -------------------------


def test_nothing_attributable_is_unattributed_not_silently_dropped():
    assert lcr.attribute_issues("Explore the auth module and report findings.") == (
        [],
        "unattributed",
    )
    assert lcr.attribute_issues(None) == ([], "unattributed")
    assert lcr.attribute_issues("") == ([], "unattributed")


# --- measure_per_issue: the join, at the report level -------------------------------


@pytest.fixture
def per_issue_projects(tmp_path):
    root = tmp_path / "projects" / PROJECT
    # main-session: unattributed by construction (no issue phrase).
    _write_jsonl(root / "sess.jsonl", [_user("/oss:run"), _assistant(60_000)])
    # A developer lane naming one issue directly.
    _write_jsonl(
        root / "sess" / "subagents" / "agent-dev.jsonl",
        [
            _user("Issue: 1477.\nFix the thing."),
            _assistant(100_000, attribution="oss:developer"),
        ],
    )
    # A recon spawn for the SAME issue -- must join into the same bucket as the
    # developer lane above, not its own, since #1618 asks for cost per issue
    # summed across every agent that worked on it.
    _write_jsonl(
        root / "sess" / "subagents" / "agent-recon.jsonl",
        [
            _user("Issue: 1477.\nLocate, do not design."),
            _assistant(20_000, attribution="oss:recon"),
        ],
    )
    # A multi-issue developer lane -- joins to a composite key, never duplicated
    # across three separate buckets (that would break the reconciliation total).
    _write_jsonl(
        root / "sess" / "subagents" / "agent-multi.jsonl",
        [
            _user("Issues: 1389, 1499, 1576.\nWork the three."),
            _assistant(90_000, attribution="oss:developer"),
        ],
    )
    # An Explore spawn naming nothing attributable -- the positive control's
    # negative pair: it WAS read (its records count), but it lands in
    # unattributed rather than being silently dropped.
    _write_jsonl(
        root / "sess" / "subagents" / "agent-explore.jsonl",
        [
            _user("Explore the auth module and report findings."),
            _assistant(15_000, attribution="Explore"),
        ],
    )
    return tmp_path / "projects"


def test_measure_per_issue_joins_developer_and_recon_onto_the_same_issue(
    per_issue_projects,
):
    result = lcr.measure_per_issue(per_issue_projects, since=SINCE)
    assert result["state"] == "measured"
    bucket = result["issues"]["1477"]
    assert bucket["issue_numbers"] == [1477]
    assert bucket["context_sent"] == 100_001 + 20_001
    assert bucket["kinds"]["developer"]["agents"] == 1
    assert (
        bucket["kinds"]["other"]["agents"] == 1
    )  # oss:recon has no dedicated KINDS row
    assert bucket["kinds"]["developer"]["rules"]["prompt-issue-number"] == 1


def test_measure_per_issue_multi_issue_lane_is_one_composite_bucket(per_issue_projects):
    result = lcr.measure_per_issue(per_issue_projects, since=SINCE)
    bucket = result["issues"]["1389,1499,1576"]
    assert bucket["issue_numbers"] == [1389, 1499, 1576]
    assert bucket["context_sent"] == 90_001
    # Must NOT also appear as three separate single-issue buckets -- that would
    # triple-count the same spend and break the reconciliation total below.
    assert "1389" not in result["issues"]
    assert "1499" not in result["issues"]
    assert "1576" not in result["issues"]


def test_measure_per_issue_unattributed_bucket_carries_the_explore_and_main_session_spend(
    per_issue_projects,
):
    result = lcr.measure_per_issue(per_issue_projects, since=SINCE)
    assert result["unattributed"]["context_sent"] == 60_001 + 15_001
    assert result["unattributed"]["agents"] == 2


def test_measure_per_issue_reconciles_with_the_window_total(per_issue_projects):
    result = lcr.measure_per_issue(per_issue_projects, since=SINCE)
    whole = lcr.measure(per_issue_projects, since=SINCE)
    window_total = whole["projects"][PROJECT]["context_sent"]
    attributed_total = sum(b["context_sent"] for b in result["issues"].values())
    assert attributed_total + result["unattributed"]["context_sent"] == window_total


def test_measure_per_issue_malformed_line_is_counted_not_dropped(tmp_path):
    root = tmp_path / "projects" / PROJECT
    _write_jsonl(
        root / "sess" / "subagents" / "agent-dev.jsonl",
        [
            _user("Issue: 1.\nDo it."),
            _assistant(10_000, attribution="oss:developer"),
            "{not json",
        ],
    )
    result = lcr.measure_per_issue(tmp_path / "projects", since=SINCE)
    assert result["malformed_lines"] == 1
    assert result["malformed"][0]["transcript"].endswith("agent-dev.jsonl")


def test_measure_per_issue_could_not_read_when_the_projects_dir_is_absent(tmp_path):
    result = lcr.measure_per_issue(tmp_path / "nope", since=SINCE)
    assert result["state"] == "could-not-read"


def test_measure_per_issue_nothing_in_window(tmp_path):
    root = tmp_path / "projects" / PROJECT
    _write_jsonl(
        root / "s.jsonl",
        [
            _user("x", ts="2026-09-10T00:00:00Z"),
            _assistant(5, ts="2026-09-10T00:00:00Z"),
        ],
    )
    result = lcr.measure_per_issue(tmp_path / "projects", since=SINCE)
    assert result["state"] == "nothing-in-window"


# --- resolve_pr_issue_map: the PR -> issue join for tick-review/tick-merge ----------


class _FakeDone:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_resolve_pr_issue_map_reads_closing_issues_references():
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        payload = {"number": 1587, "closingIssuesReferences": [{"number": 1580}]}
        return _FakeDone(stdout=json.dumps(payload).encode("utf-8"))

    mapping, unresolved = lcr.resolve_pr_issue_map("owner/repo", [1587], "gh", fake_run)
    assert mapping == {1587: [1580]}
    assert unresolved == []
    assert calls[0][:3] == ["gh", "pr", "view"]


def test_resolve_pr_issue_map_records_a_failed_lookup_not_a_silent_skip():
    def fake_run(command, **kwargs):
        return _FakeDone(returncode=1, stderr=b"HTTP 404: Not Found")

    mapping, unresolved = lcr.resolve_pr_issue_map("owner/repo", [9999], "gh", fake_run)
    assert mapping == {}
    assert len(unresolved) == 1
    assert unresolved[0]["pr"] == 9999


# --- resolved_issues_in_window: the denominator -------------------------------------


def test_resolved_issues_in_window_filters_by_closed_at_and_excludes_prs():
    def fake_run(command, **kwargs):
        rows = [
            {"number": 10, "pull_request": None, "closed_at": "2026-09-12T00:00:00Z"},
            {"number": 11, "pull_request": None, "closed_at": "2026-09-01T00:00:00Z"},
            {"number": 12, "pull_request": {}, "closed_at": "2026-09-12T00:00:00Z"},
            {"number": 13, "pull_request": None, "closed_at": None},
        ]
        return _FakeDone(stdout=json.dumps(rows).encode("utf-8"))

    since_dt = lcr.parse_since(SINCE)
    state, numbers, reason = lcr.resolved_issues_in_window(
        "owner/repo", since_dt, "gh", fake_run
    )
    assert state == "ok"
    assert numbers == [10]
    assert reason == ""


def test_resolved_issues_in_window_could_not_read_on_gh_failure():
    def fake_run(command, **kwargs):
        return _FakeDone(returncode=1, stderr=b"rate limited")

    since_dt = lcr.parse_since(SINCE)
    state, numbers, reason = lcr.resolved_issues_in_window(
        "owner/repo", since_dt, "gh", fake_run
    )
    assert state == "could-not-read"
    assert numbers == []
    assert "rate limited" in reason


# --- the CLI --------------------------------------------------------------------------


def test_cli_per_issue_json_reports_attribution_and_reconciliation(per_issue_projects):
    proc = _run(
        "--projects-dir",
        str(per_issue_projects),
        "--since",
        SINCE,
        "--per-issue",
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["state"] == "measured"
    assert "1477" in payload["issues"]
    assert payload["unattributed"]["context_sent"] > 0
    assert (
        payload["resolved_issues"] is None
    )  # --repo not given: not-requested, never zero


def test_cli_per_issue_text_prints_unattributed_line(per_issue_projects):
    proc = _run(
        "--projects-dir", str(per_issue_projects), "--since", SINCE, "--per-issue"
    )
    assert proc.returncode == 0, proc.stderr
    assert "unattributed" in proc.stdout.lower()
    assert "1477" in proc.stdout


def test_cli_per_issue_pr_issue_map_file(tmp_path, per_issue_projects):
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps({"1587": [1580]}), encoding="utf-8")
    root = per_issue_projects / PROJECT
    _write_jsonl(
        root / "sess" / "subagents" / "agent-tick-merge.jsonl",
        [
            _user("Merge pull request #1587 once CI is green."),
            _assistant(30_000, attribution="oss:tick-merge"),
        ],
    )
    proc = _run(
        "--projects-dir",
        str(per_issue_projects),
        "--since",
        SINCE,
        "--per-issue",
        "--pr-issue-map",
        str(map_path),
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["issues"]["1580"]["kinds"]["tick-merge"]["agents"] == 1


def test_cli_per_issue_bad_pr_issue_map_file_is_could_not_read(
    tmp_path, per_issue_projects
):
    map_path = tmp_path / "map.json"
    map_path.write_text("not json", encoding="utf-8")
    proc = _run(
        "--projects-dir",
        str(per_issue_projects),
        "--since",
        SINCE,
        "--per-issue",
        "--pr-issue-map",
        str(map_path),
        "--json",
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["state"] == "could-not-read"
