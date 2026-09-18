"""#1676: `oss_config.build()` writes `triage_route_threshold`, so a scaffolded repo's
label-coverage triage route is on by default rather than off-and-reporting-clean.

The scaffold half of #1651. `curate_route_threshold` got exactly this treatment in #1616
(`test_trap_write_only_1616.py`); this file is the triage twin, test for test. The one
difference is the number, and the reason for it is in `oss_config.build()`'s own note.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import workspace_routes  # noqa: E402


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": [],
        "milestones": [],
        "workflow_jobs": [],
        "files": [],
        "tags": [],
        "merge_method": "squash",
        "version_evidence": {},
    }
    probe.update(overrides)
    return probe


def _curate_under(monkeypatch):
    """Pin the sibling route UNDER so nothing here depends on a real trap.d/ read,
    and so `decide()`'s armed answer is about triage alone."""
    monkeypatch.setattr(
        workspace_routes,
        "curate_count",
        lambda repo_root, config=None, run=None, git_bin=None: (
            0,
            "fixture: curate pinned under",
        ),
    )


def test_build_writes_triage_route_threshold():
    """A freshly derived config must carry the key. Absent means the #1155 label-coverage
    triage route is never armed for a repo this plugin onboards, and every issue filed
    there without a priority label stays unrankable by select_issues_rank until a
    release happens to trigger a sweep (#1676)."""
    config = oss_config.build(_probe())
    assert "triage_route_threshold" in config, (
        "oss_config.build() does not write triage_route_threshold -- a repo scaffolded "
        "through /oss:run:setup gets the label-coverage triage route silently off by "
        "default, forever (#1676)"
    )
    assert workspace_routes._valid_threshold(config["triage_route_threshold"]), (
        "triage_route_threshold={!r} is not a usable non-negative integer -- "
        "workspace_routes.decide() would report could-not-count rather than a real "
        "comparison".format(config["triage_route_threshold"])
    )


def test_written_threshold_validates_and_is_project_scoped():
    """Round-trips through validate() and split() like every other judgement-call
    default -- never machine-scoped, never rejected as unknown."""
    config = oss_config.build(_probe())
    assert oss_config.validate(config) == []
    assert "triage_route_threshold" in oss_config.PROJECT_KEYS
    assert "triage_route_threshold" not in oss_config.LOCAL_KEYS


def test_written_threshold_actually_arms_the_triage_route(monkeypatch):
    """Wiring check, not just presence: an unlabelled count one over the written
    threshold must arm the route (OVER), and a count at the threshold must not
    (UNDER). The negative half is the positive control's partner, per CLAUDE.md."""
    config = oss_config.build(_probe())
    threshold = config["triage_route_threshold"]
    _curate_under(monkeypatch)

    monkeypatch.setattr(
        workspace_routes,
        "triage_count",
        lambda repo, gh, run, timeout=25: (
            threshold + 1,
            "fixture: one over the written threshold",
        ),
    )
    armed_route, results = workspace_routes.decide(Path("."), config=config)
    assert results["triage"]["state"] == workspace_routes.OVER, (
        "an unlabelled count over the written threshold did not arm the triage route: "
        "{!r}".format(results["triage"])
    )
    assert armed_route == "triage"

    monkeypatch.setattr(
        workspace_routes,
        "triage_count",
        lambda repo, gh, run, timeout=25: (
            threshold,
            "fixture: at the written threshold",
        ),
    )
    armed_route, results = workspace_routes.decide(Path("."), config=config)
    assert results["triage"]["state"] == workspace_routes.UNDER, (
        "an unlabelled count at the written threshold armed the triage route early: "
        "{!r}".format(results["triage"])
    )
    assert armed_route is None


def test_first_unlabelled_issue_is_enough():
    """The number itself is load-bearing and pinned on purpose: an unlabelled issue is
    invisible to dispatch for as long as it stays unlabelled, so there is no backlog
    size at which waiting is correct. `_count_state` fires on `count > threshold`, so
    0 is the value under which one unlabelled issue makes a sweep due. A future raise
    has to argue against this docstring, not slip past it."""
    config = oss_config.build(_probe())
    assert config["triage_route_threshold"] == 0
    assert workspace_routes._count_state(1, config["triage_route_threshold"]) == (
        workspace_routes.OVER
    )
    assert workspace_routes._count_state(0, config["triage_route_threshold"]) == (
        workspace_routes.UNDER
    )
