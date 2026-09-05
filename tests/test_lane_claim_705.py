"""#705: `lane_setup.py` used to write a lane record on every call, whether or not
the caller was ever going to dispatch that lane. A maintainer probing three
candidate lanes for disjointness (`--lane`/`--derive-held`, both legitimately used
by a call that decides nothing) left two phantom records behind, each carrying
`files=None` -- exactly the shape `held_from_live_lanes` (#558) refuses to trust as
complete -- so the next `--derive-held` call for an entirely different, real lane
came back `could-not-derive` because of a probe that never claimed anything.

`claim` is now the explicit signal: default False writes nothing, `claim=True`
writes exactly the record #385/#558 always wrote. This file tests the read/write
split described in the issue's first proposed fix ("a read that does not write");
the issue's second half -- reaping a record when its lane actually ends -- is a
separate mechanism and is not touched here.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _configured_repo(tmp_path, worktree_root):
    repo = tmp_path / "repo"
    repo.mkdir()
    # #865 review round: `compute(..., claim=True)` now checks
    # `linked_worktree_state(repo)` before trusting a claim, and a bare
    # directory with no `.git` at all answers `could-not-tell` -- measured
    # directly, not a real linked worktree, and refused for the identical
    # reason a genuine one is (git could not vouch for it). This fixture is
    # meant to stand in for an ordinary clone (every other git-dependent
    # call here -- resolve_base, branch_occupancy, read_board -- is
    # monkeypatched below specifically so the test does not need a real
    # remote or history), so it needs a real, ordinary -- non-worktree --
    # git identity for that one check to answer truthfully. `git init` alone
    # is sufficient: `git rev-parse --git-common-dir`/`--git-dir` answer
    # without any commit.
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    config = {
        "repo": "example/example",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "true",
        "docs_targets": [],
        "changelog_dir": "changelog.d",
    }
    (repo / lane_setup.CONFIG_NAME).write_text(json.dumps(config))
    return repo


def _patch_reads(monkeypatch, worktree_root):
    monkeypatch.setattr(
        lane_setup,
        "resolve_base",
        lambda *a, **k: {
            "state": "resolved",
            "remote": "origin",
            "ref": "origin/main",
            "sha": "a" * 40,
            "detail": "",
        },
    )
    monkeypatch.setattr(lane_setup, "branch_occupancy", lambda *a, **k: (False, False))
    monkeypatch.setattr(
        lane_setup,
        "read_board",
        lambda repo: {"state": "ok", "lines": [], "detail": ""},
    )

    real_load = lane_setup.oss_config.load

    def fake_load(path):
        cfg, problems = real_load(path)
        if cfg is not None:
            cfg = dict(cfg)
            cfg["worktree_root"] = str(worktree_root)
        return cfg, problems

    monkeypatch.setattr(lane_setup.oss_config, "load", fake_load)


def test_bare_probe_call_does_not_write_a_lane_record(tmp_path, monkeypatch):
    """The bug as filed: a plain `lane_setup.py <issue>` call, with no --claim,
    must not write anything to the registry at all.
    """
    worktree_root = tmp_path / "worktrees"
    repo = _configured_repo(tmp_path, worktree_root)
    _patch_reads(monkeypatch, worktree_root)

    payload = lane_setup.compute(str(repo), 705, "origin")

    assert payload["lanes"]["record"]["state"] == "not-claimed"
    registry_dir = lane_setup.lane_registry_dir(str(worktree_root))
    assert not os.path.exists(os.path.join(registry_dir, "705.json"))


def test_derive_held_probe_without_claim_also_writes_nothing(tmp_path, monkeypatch):
    """The exact shape reported: a --derive-held probe (no --lane) used to write a
    files=None record, which is the one shape `held_from_live_lanes` refuses to
    trust as complete. Without --claim, no record should exist for it to trip over.
    """
    worktree_root = tmp_path / "worktrees"
    repo = _configured_repo(tmp_path, worktree_root)
    _patch_reads(monkeypatch, worktree_root)
    monkeypatch.setattr(
        lane_setup,
        "derive_held_set",
        lambda *a, **k: {
            "state": "unknown",
            "held": {},
            "prs": {},
            "lanes": {},
            "detail": "",
        },
    )

    payload = lane_setup.compute(str(repo), 222, "origin", derive_held=True)

    assert payload["lanes"]["record"]["state"] == "not-claimed"
    registry_dir = lane_setup.lane_registry_dir(str(worktree_root))
    assert not os.path.exists(os.path.join(registry_dir, "222.json"))


def test_claim_true_still_writes_exactly_as_before(tmp_path, monkeypatch):
    """Positive control: the write path must still work when a caller actually
    asks for it -- this is what a real dispatch is supposed to do.
    """
    worktree_root = tmp_path / "worktrees"
    repo = _configured_repo(tmp_path, worktree_root)
    _patch_reads(monkeypatch, worktree_root)

    payload = lane_setup.compute(str(repo), 705, "origin", claim=True)

    assert payload["lanes"]["record"]["state"] == "recorded"
    registry_dir = lane_setup.lane_registry_dir(str(worktree_root))
    assert os.path.exists(os.path.join(registry_dir, "705.json"))


def test_probing_three_candidates_leaves_no_phantom_records_for_a_real_lane(
    tmp_path, monkeypatch
):
    """End-to-end reproduction of the issue's own scenario: probe three candidate
    lanes (none claimed), dispatch a fourth. `held_from_live_lanes` must see zero
    live records left by the probes -- not the #558 could-not-derive refusal a
    files=None phantom record would have produced.
    """
    worktree_root = tmp_path / "worktrees"
    repo = _configured_repo(tmp_path, worktree_root)
    _patch_reads(monkeypatch, worktree_root)

    lane_setup.compute(str(repo), 111, "origin")
    lane_setup.compute(str(repo), 222, "origin", lane_patterns=["a.py"])
    lane_setup.compute(str(repo), 333, "origin", derive_held=True)

    result = lane_setup.held_from_live_lanes(str(worktree_root), exclude_issue=444)

    assert result["state"] == "unknown", (
        "three unclaimed probes must leave no live lane records behind -- "
        "a could-not-derive here means a phantom record survived (#705)"
    )
    assert result["held"] == {}


def test_a_genuine_claim_with_no_lane_files_still_blocks_derive_held_as_designed(
    tmp_path, monkeypatch
):
    """#558 must still hold once a lane genuinely claims itself without --lane:
    that live record legitimately carries files=None, and a sibling's
    --derive-held call must still refuse to trust the held set as complete.
    This is the case #705's fix must not silently remove.
    """
    worktree_root = tmp_path / "worktrees"
    repo = _configured_repo(tmp_path, worktree_root)
    _patch_reads(monkeypatch, worktree_root)

    lane_setup.compute(str(repo), 111, "origin", claim=True)

    result = lane_setup.held_from_live_lanes(str(worktree_root), exclude_issue=222)

    assert result["state"] == "could-not-derive"
