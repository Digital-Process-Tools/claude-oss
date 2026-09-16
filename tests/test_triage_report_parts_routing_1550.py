"""#1550: parts 2-5 of a triage sweep's report had no persistence path. Only
part 1 (labels applied) writes anything, via `oss_state.py --decision
--triage-recorded`. Parts 2 (refusals), 3 (board findings), 4 (clusters) and 5
(cohort burn-down) were handed to an `oss:scheduler-step` spawn that reads one
procedure, acts, and dies with its context (#1414) -- so the report died with
it.

The fix:

- points part 3 (board findings) and part 4 (clusters) at the existing
  findings-routing rule (`skills/manager/phases/findings.md`'s "Routing a
  finding is the same read as ranking it", #1275) that already reaches
  `agents/auditor.md`, `agents/developer.md`, `agents/developer/review.md`
  and `agents/sub-manager.md`, but had not reached `commands/run/triage.md`;
- gives part 5 (cohort burn-down) a persistence path by folding it into the
  same `--decision --triage-recorded` call's `--detail` JSON, which
  `oss_state.py` already accepts as an arbitrary object and only refuses on
  a key collision with `triage`/`tick_cost` -- `cohort_burndown` collides
  with neither, so no code change to `oss_state.py` was needed.

Content-invariant checks over `commands/run/triage.md`'s own prose, plus one
real run of the documented `--detail` call against a scratch state file to
prove the mechanism actually works rather than only reading as plausible
prose.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

TRIAGE_MD = (REPO_ROOT / "commands" / "run" / "triage.md").read_text(encoding="utf-8")
TICK_MD = (REPO_ROOT / "commands" / "tick.md").read_text(encoding="utf-8")


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _oss_state(*args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


# --------------------------------------------------------- positive controls


def test_triage_md_points_board_findings_at_the_routing_rule():
    collapsed = _collapse(TRIAGE_MD)
    assert "skills/manager/phases/findings.md" in collapsed, (
        "triage.md never points board findings (part 3) at the existing "
        "findings-routing rule -- the rule that already reaches auditor.md, "
        "developer.md and sub-manager.md did not reach this file"
    )
    assert "#1275" in collapsed, (
        "triage.md's routing pointer does not cite #1275, the routing rule's own issue"
    )


def test_triage_md_says_clusters_are_not_trap_d_shaped():
    collapsed = _collapse(TRIAGE_MD)
    assert re.search(
        r"clusters?.{0,200}?(proposal|not.{0,40}(lesson|shape)).{0,200}?trap\.d",
        collapsed,
        re.IGNORECASE,
    ), (
        "triage.md does not say clusters (part 4) are a proposal about issue "
        "structure rather than a lesson about code, so it is silent on why "
        "they are not routed through trap.d/ the same way board findings are"
    )


def test_triage_md_folds_cohort_burndown_into_the_detail_call():
    assert "--detail" in TRIAGE_MD, (
        "triage.md never mentions --detail -- part 5's cohort burn-down has "
        "no persistence path without it"
    )
    idx = TRIAGE_MD.find("--detail")
    assert idx != -1
    window = TRIAGE_MD[max(0, idx - 400) : idx + 400]
    assert "cohort_burndown" in window, (
        "the --detail call in triage.md does not carry a cohort_burndown key"
    )
    assert "--triage-recorded" in window, (
        "the --detail call is not attached to the same --decision "
        "--triage-recorded call part 1 already makes -- a second, separate "
        "write is not what #1550 asked for"
    )


# --------------------------------------------------------- real mechanism


def test_tick_md_post_release_dispatch_also_folds_in_burndown_and_routing():
    """`commands/tick.md`'s own post-release triage step dispatches the same
    `oss:triager` agent as `commands/run/triage.md`, producing the identical
    five-part report -- so it carried the identical gap and needs the
    identical fix, not just the manually-typed `/oss:triage` command."""
    assert "--detail" in TICK_MD, (
        "commands/tick.md's post-release triage step never mentions --detail "
        "-- it dispatches the same agent as triage.md and has the same "
        "cohort-burndown persistence gap"
    )
    idx = TICK_MD.find("--detail")
    assert idx != -1
    window = TICK_MD[max(0, idx - 400) : idx + 400]
    assert "cohort_burndown" in window
    assert "--triage-recorded" in window
    collapsed = _collapse(TICK_MD)
    assert "skills/manager/phases/findings.md" in collapsed and "#1275" in collapsed, (
        "commands/tick.md's post-release triage step does not point board "
        "findings/clusters at the findings-routing rule either"
    )


def test_detail_cohort_burndown_actually_persists(tmp_path):
    """Positive: run the documented shape for real. The entry on disk must
    carry both the triage timestamp and the cohort burn-down detail, proving
    the --detail key does not collide with the auto-attached 'triage' key."""
    state_path = tmp_path / "state.json"
    result = _oss_state(
        str(state_path),
        "--decision",
        "triage sweep recorded",
        "--at",
        "2026-09-16T00:00:00Z",
        "--triage-recorded",
        "2026-09-16T00:00:00Z",
        "--detail",
        json.dumps({"cohort_burndown": {"open": 5, "limit": 20}}),
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads(state_path.read_text(encoding="utf-8"))
    entry = entries[-1] if isinstance(entries, list) else entries
    detail = entry.get("detail") or entry
    assert detail["cohort_burndown"] == {"open": 5, "limit": 20}
    assert "triage" in detail
