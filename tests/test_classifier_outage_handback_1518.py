"""#1518: a dispatched lane must retry then hand back on an auto-mode
classifier outage, never end its turn on "waiting" -- and the sub-manager
side must read the task's output file rather than treat that sentence as
`agent-unreachable` on sight.

Two anchors, one per side of the fix, each checked two ways: present now,
and absent from the pre-fix blob at this branch's own merge base -- so an
anchor that happened to already match the old wording (a guard with no
teeth) is caught rather than silently passing. Matched against a flattened
copy of the document (lowercased, whitespace collapsed to one space) for the
same reason `test_developer_brief_duties.py` does: these files wrap at 100
columns and a multi-word anchor can land across a reflow.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402

MERGE_BASE = "5aa0534574b9b1ed5a781e5a030bc92f97f1d33a"

DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
DISPATCH_MD = REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md"

LANE_ANCHOR = "auto-mode bash classifier can go down mid-call"
SUB_MANAGER_ANCHOR = "a lane that stopped, not one that finished (#1518)"

# CI's checkout (actions/checkout@v7, no fetch-depth override) is shallow: it fetches
# only the tip commit, no ancestors. `git show <ancestor-sha>:path` then fails with
# this exact wording even though the commit is a real ancestor with the real content
# on the remote -- #1563, reproduced directly with `git clone --depth=1`. That failure
# renders identically to "the historical blob genuinely lacks the path", which is the
# absence-read-as-absence defect class this repo refuses to let a checker paper over.
_SHALLOW_HISTORY_MARKER = "exists on disk, but not in"


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _blob_at(rev: str, path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).as_posix()
    result = spawn_guard.run(
        ["git", "show", "{0}:{1}".format(rev, rel)],
        subject="reading the pre-fix blob for the positive control",
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 and _SHALLOW_HISTORY_MARKER in result.stderr:
        # Deepen the checkout for this one historical commit and retry once, rather
        # than either failing on a checkout artifact or silently skipping without
        # having tried to actually answer the question.
        fetch = spawn_guard.run(
            ["git", "fetch", "--depth=1", "origin", rev],
            subject="deepening a shallow checkout to reach the pre-fix commit (#1563)",
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if fetch.returncode == 0:
            result = spawn_guard.run(
                ["git", "show", "{0}:{1}".format(rev, rel)],
                subject="reading the pre-fix blob for the positive control (post-deepen)",
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
    if result.returncode != 0:
        pytest.skip(
            "could not read {0} at {1} even after a deepen retry -- {2}".format(
                rel, rev, result.stderr.strip()
            )
        )
    return result.stdout


def test_developer_md_carries_the_retry_then_handback_rule():
    body = _flatten(DEVELOPER_MD.read_text(encoding="utf-8"))
    assert LANE_ANCHOR in body
    assert "never end a turn on" in body
    assert "#1518" in DEVELOPER_MD.read_text(encoding="utf-8")


def test_developer_md_anchor_is_absent_from_the_pre_fix_blob():
    """Positive control: the anchor must not already have matched the old
    wording, or this guard has no teeth."""
    prior = _flatten(_blob_at(MERGE_BASE, DEVELOPER_MD))
    assert LANE_ANCHOR not in prior


def test_dispatch_md_carries_the_read_the_output_file_rule():
    body = _flatten(DISPATCH_MD.read_text(encoding="utf-8"))
    assert SUB_MANAGER_ANCHOR in body
    assert "output-file" in body
    assert "do not open that file whole" in body
    assert "grep:auto mode cannot determine the safety" in body


def test_dispatch_md_anchor_is_absent_from_the_pre_fix_blob():
    prior = _flatten(_blob_at(MERGE_BASE, DISPATCH_MD))
    assert SUB_MANAGER_ANCHOR not in prior


def test_developer_md_still_under_its_budget():
    import agent_budgets  # noqa: E402

    result = agent_budgets.check()
    row = next(r for r in result if r["path"] == "agents/developer.md")
    assert row["state"] == "ok", row
