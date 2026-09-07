"""#1181: `labels.lane_other` is a completed triage decision -- "this issue was
examined and no real lane owns its files" -- not the absence of one. Before this
fix, `refresh()` built its `lane_set` from `labels.lanes` alone, so a
correctly-triaged `lane-other` issue counted toward `issues_no_lane` exactly like
an issue nobody has looked at yet: triaging an issue *correctly* as `lane-other`
made the number go up, and it could never be driven to zero.

Exercised through the real `refresh()` (not `_gh_unlabelled_issue_counts` directly,
which already accepted an arbitrary `lane_labels` list correctly) -- the bug was in
how `refresh()` derived that list from config, so the fix has to be proven there.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _refresh_with_labels(tmp_path, monkeypatch, labels, gh_labels_line):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline, "repo_config", lambda root: {"repo": "owner/repo", "labels": labels}
    )
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 1)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "_gh_default_branch_state", lambda repo, br: None)
    monkeypatch.setattr(
        statusline, "installed_plugins", lambda project_root, plugins_root=None: {}
    )
    monkeypatch.setattr(statusline, "_latest_release", lambda slug: None)
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: gh_labels_line)
    return statusline.refresh(".", now=1_000.0)


def test_a_lane_other_tagged_issue_no_longer_counts_as_no_lane(tmp_path, monkeypatch):
    """Must-fire half: the one open issue carries only `lane-other` -- a completed
    triage decision -- and must stop being counted as untriaged."""
    labels = {
        "priority": ["priority-high"],
        "lanes": ["lane-a", "lane-b"],
        "lane_other": "lane-other",
    }
    document = _refresh_with_labels(tmp_path, monkeypatch, labels, '["lane-other"]')
    assert document["issues_no_lane"] == 0


def test_an_actually_unlabelled_issue_still_counts_the_positive_control(
    tmp_path, monkeypatch
):
    """Must-not-fire half: an issue carrying no lane label of any kind (not even
    `lane-other`) must still count -- the fix must not stop counting altogether."""
    labels = {
        "priority": ["priority-high"],
        "lanes": ["lane-a", "lane-b"],
        "lane_other": "lane-other",
    }
    document = _refresh_with_labels(tmp_path, monkeypatch, labels, '["priority-high"]')
    assert document["issues_no_lane"] == 1


def test_undeclared_lane_other_behaves_exactly_as_before(tmp_path, monkeypatch):
    """A repo that has not declared `labels.lane_other` at all must see no change
    -- an issue with none of the declared lanes still counts as no-lane."""
    labels = {"priority": ["priority-high"], "lanes": ["lane-a", "lane-b"]}
    document = _refresh_with_labels(tmp_path, monkeypatch, labels, '["lane-other"]')
    assert document["issues_no_lane"] == 1
