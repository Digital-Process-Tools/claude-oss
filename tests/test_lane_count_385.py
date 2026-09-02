"""#385: nothing could report how many sibling lanes are live, so each one sized
`pytest -n auto` against the whole machine -- the overcommit #367 was filed from.

#367 added the worker-sizing line to `doctor.py` and deliberately claimed no lane
count: no process can enumerate its sibling lanes (`ps` / `lsof` cannot see a
sandboxed agent, the same limit `#81` records for the harness's own registry, and the
reason `git-worktrees` has a `cannot tell` state rather than an occupancy number). So
this cannot be a probe; it has to be a record written by the thing that starts a lane.

`scripts/lane_setup.py` is that thing -- every lane brief starts with a call to it, and
its own module docstring already re-derives facts a brief would otherwise hand-carry
stale (#317). `lanes_snapshot` adds one more: it writes this lane's own record into a
registry beside the numbered worktree directories and reports how many are live *right
now*, which is the only moment the count is useful -- before doctor typically runs.

Three states on the read side, never two:
  resolved       one or more live records, aged under the TTL.
  unknown        the registry could not be located, does not exist, or is empty. A
                 registry with zero live entries and a registry nothing has ever
                 written to render identically on disk, so both report `unknown`,
                 never `0` -- reporting `0` here is exactly the confident-absence
                 defect the mechanism exists to close.
  could-not-run  the registry exists and has entries, but one could not be read at
                 all (corrupt JSON, a missing field) -- a partial count would
                 undercount silently, so this is reported rather than swallowed.

A record older than `LANE_RECORD_TTL_SECONDS` is pruned as a side effect of reading,
which is the only cleanup this mechanism has: nothing calls `lane_setup.py` when a
lane ends, so the next lane to check is what clears a dead one out. It is dropped from
the count rather than folding the whole answer to `unknown`, because the TTL is a
direct filesystem timestamp comparison -- not a guess reached by asking a sandboxed
process whether it is still there, which is the thing this file's own docstring says
cannot be done.
"""

import builtins
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _write_record(worktree_root, issue, age_seconds=0):
    root = lane_setup.lane_registry_dir(worktree_root)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "{0}.json".format(issue))
    payload = {
        "issue": issue,
        "branch": "fix/{0}".format(issue),
        "path": None,
        "recorded_at": time.time() - age_seconds,
        "pid": 1,
    }
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return path


def test_two_recorded_live_lanes_count_as_two(tmp_path):
    root = str(tmp_path / "worktrees")
    _write_record(root, 111, age_seconds=60)
    _write_record(root, 222, age_seconds=120)

    result = lane_setup.lane_count(root)

    assert result["state"] == "resolved"
    assert result["count"] == 2


def test_a_machine_with_no_recorded_lanes_reports_unknown_not_zero(tmp_path):
    """The paired control #385 asks for. A registry that was never written to and a
    registry confirmed to hold zero live lanes are indistinguishable on disk, so
    neither may render as `0` -- `0` is a specific, false claim of certainty.
    """
    root = str(tmp_path / "never-written")

    result = lane_setup.lane_count(root)

    assert result["state"] == "unknown"
    assert result["count"] is None
    assert result["count"] != 0


def test_an_existing_but_empty_registry_also_reports_unknown(tmp_path):
    root = str(tmp_path / "worktrees")
    os.makedirs(root, exist_ok=True)

    result = lane_setup.lane_count(root)

    assert result["state"] == "unknown"
    assert result["count"] is None


def test_no_worktree_root_reports_unknown(tmp_path):
    result = lane_setup.lane_count(None)

    assert result["state"] == "unknown"
    assert result["count"] is None


def test_a_stale_record_is_pruned_and_excluded_from_the_count(tmp_path):
    root = str(tmp_path / "worktrees")
    live_path = _write_record(root, 111, age_seconds=60)
    stale_path = _write_record(
        root, 222, age_seconds=lane_setup.LANE_RECORD_TTL_SECONDS + 3600
    )

    result = lane_setup.lane_count(root)

    assert result["state"] == "resolved"
    assert result["count"] == 1
    assert os.path.exists(live_path)
    assert not os.path.exists(stale_path), (
        "a stale record must be pruned by the next reader -- nothing else cleans it up"
    )


def test_a_stale_record_alone_leaves_the_registry_reporting_unknown(tmp_path):
    root = str(tmp_path / "worktrees")
    _write_record(root, 222, age_seconds=lane_setup.LANE_RECORD_TTL_SECONDS + 3600)

    result = lane_setup.lane_count(root)

    assert result["state"] == "unknown"
    assert result["count"] is None


def test_an_unreadable_record_reports_could_not_run_not_a_partial_count(tmp_path):
    root = str(tmp_path / "worktrees")
    _write_record(root, 111, age_seconds=60)
    registry_dir = lane_setup.lane_registry_dir(root)
    with open(os.path.join(registry_dir, "222.json"), "w") as fh:
        fh.write("{not valid json")

    result = lane_setup.lane_count(root)

    assert result["state"] == "could-not-run"
    assert result["count"] is None


def test_record_lane_writes_and_refresh_overwrites_the_same_file(tmp_path):
    root = str(tmp_path / "worktrees")

    first = lane_setup.record_lane(root, 385, "fix/385", "/some/path")
    assert first["state"] == "recorded"

    registry_dir = lane_setup.lane_registry_dir(root)
    entries = os.listdir(registry_dir)
    assert entries == ["385.json"]

    second = lane_setup.record_lane(root, 385, "fix/385", "/some/path")
    assert second["state"] == "recorded"
    assert os.listdir(registry_dir) == ["385.json"], "a re-invocation refreshes, not duplicates"

    result = lane_setup.lane_count(root)
    assert result["state"] == "resolved"
    assert result["count"] == 1


def test_record_lane_with_no_worktree_root_is_unknown_not_could_not_write(tmp_path):
    result = lane_setup.record_lane(None, 385, "fix/385", "/some/path")

    assert result["state"] == "unknown"


def test_compute_wires_lanes_snapshot_into_the_payload_and_counts_itself(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    # #865 review round: `compute(..., claim=True)` now checks
    # `linked_worktree_state(repo)`, and a bare directory with no `.git` at
    # all answers `could-not-tell` -- measured directly, not a real linked
    # worktree -- and is refused for the identical reason a genuine one is.
    # This fixture stands in for an ordinary clone (every other
    # git-dependent call below is monkeypatched specifically so this test
    # needs no real remote or history), so it needs a real, ordinary --
    # non-worktree -- git identity for that one check to answer truthfully.
    # `git init` alone is sufficient; no commit is needed.
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    worktree_root = tmp_path / "worktrees"

    config = {
        "repo": "example/example",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "true",
        "docs_targets": [],
        "changelog_dir": "changelog.d",
    }
    (repo / lane_setup.CONFIG_NAME).write_text(json.dumps(config))

    monkeypatch.setattr(
        lane_setup, "resolve_base", lambda *a, **k: {
            "state": "resolved", "remote": "origin", "ref": "origin/main",
            "sha": "a" * 40, "detail": "",
        }
    )
    monkeypatch.setattr(lane_setup, "branch_occupancy", lambda *a, **k: (False, False))
    monkeypatch.setattr(lane_setup, "read_board", lambda repo: {"state": "ok", "lines": [], "detail": ""})

    real_load = lane_setup.oss_config.load

    def fake_load(path):
        cfg, problems = real_load(path)
        if cfg is not None:
            cfg = dict(cfg)
            cfg["worktree_root"] = str(worktree_root)
        return cfg, problems

    monkeypatch.setattr(lane_setup.oss_config, "load", fake_load)

    payload = lane_setup.compute(str(repo), 385, "origin", claim=True)

    assert payload["lanes"]["record"]["state"] == "recorded"
    assert payload["lanes"]["count"]["state"] == "resolved"
    assert payload["lanes"]["count"]["count"] == 1

    rendered = lane_setup.receipt(payload)
    assert "lanes" in rendered


def test_a_record_vanishing_between_listdir_and_open_is_not_unreadable(tmp_path, monkeypatch):
    """The reviewer's TOCTOU finding: a sibling `lane_count()` call can prune a stale
    record between our `listdir` and our `open` -- that is not corruption, and must
    not fold the whole call to `could-not-run` for a record nothing was wrong with.
    """
    root = str(tmp_path / "worktrees")
    live_path = _write_record(root, 111, age_seconds=60)
    vanishing_path = _write_record(root, 222, age_seconds=60)

    real_open = builtins.open

    def racing_open(path, *a, **k):
        if os.path.abspath(path) == os.path.abspath(vanishing_path):
            os.remove(vanishing_path)
        return real_open(path, *a, **k)

    monkeypatch.setattr(lane_setup, "open", racing_open, raising=False)

    result = lane_setup.lane_count(root)

    assert result["state"] == "resolved"
    assert result["count"] == 1
    assert os.path.exists(live_path)


def test_a_future_recorded_at_is_counted_live_not_pruned(tmp_path):
    """The reviewer's clock-skew finding: a `recorded_at` in the future (writer/reader
    clock skew, or a read racing a write) reads as "just written", not "abandoned" --
    it must not be silently deleted, which would undercount a genuinely live lane.
    """
    root = str(tmp_path / "worktrees")
    future_path = _write_record(root, 111, age_seconds=-3600)

    result = lane_setup.lane_count(root)

    assert result["state"] == "resolved"
    assert result["count"] == 1
    assert os.path.exists(future_path), "a future timestamp must not be pruned"

