"""#1201: this repo's OWN `lane_patterns` in `.oss.json` are checked against
this repo's OWN bookkeeping files -- `CLAUDE.md`'s phase-budget table and
`scripts/skill_phases.py`'s `DOCUMENTS` dict -- which two disjoint lanes
independently touched in one tick because neither lane's declared pattern
named them (issue's own incident: PR #1195 and PR #1194 collided on
adjacent lines of both files).

Every bookkeeping script that shares the identical shape -- one budget
table per phase/spine document, re-baselined by whichever lane happens to
touch the file it tracks -- is checked here too, not only the one the
incident named: `scripts/skill_phases.py`, `scripts/agent_budgets.py`,
`scripts/command_budgets.py` and `scripts/developer_phases.py` (the four
`agent_budgets.BUDGETS`/`skill_phases.DOCUMENTS`/`command_budgets.
BUDGETS`/`developer_phases.DOCUMENTS` tables CLAUDE.md itself documents).
`CLAUDE.md` is already named, whole-file, by `lane-prose`'s own pattern --
the control here, proving the coverage check itself is correct rather than
vacuous -- while the four scripts are not named by any lane's pattern at
all before this issue's fix.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import select_issues_overlap  # noqa: E402


def _lane_patterns():
    config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    return config["labels"]["lane_patterns"]


def _all_declared_files():
    """The union of files resolved from every lane's own declared pattern,
    against this repo's real tree -- the identical mechanism
    `select_issues_overlap.resolve_lane` uses for the collision check
    itself, not a hand-rolled prefix match that could disagree with it.
    """
    files = set()
    for patterns in _lane_patterns().values():
        resolved = select_issues_overlap.resolve_lane(REPO_ROOT, patterns)
        files |= set(resolved["files"])
    return files


def test_claude_md_is_already_covered_by_lane_prose_the_control():
    assert "CLAUDE.md" in _all_declared_files()


def test_skill_phases_documents_dict_is_covered_by_some_lane_pattern():
    assert "scripts/skill_phases.py" in _all_declared_files()


def test_agent_budgets_dict_is_covered_by_some_lane_pattern():
    assert "scripts/agent_budgets.py" in _all_declared_files()


def test_command_budgets_dict_is_covered_by_some_lane_pattern():
    assert "scripts/command_budgets.py" in _all_declared_files()


def test_developer_phases_documents_dict_is_covered_by_some_lane_pattern():
    assert "scripts/developer_phases.py" in _all_declared_files()
