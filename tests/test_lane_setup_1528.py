"""#1528 -- the `lane_setup.py --derive-held` receipt used to render a
same-lane overlap as `verdict : BLOCKED`, an instruction to stop, when the
underlying fact is only that two lanes' files intersect. This test pins the
new wording: the receipt still names the held files and the holder (the
analysis is unchanged and still valuable -- it is what diagnosed #1526 vs
#1499 and #1528 vs #1511), but it no longer reads as a command to halt.

Positive control alongside it: a genuinely disjoint lane must still read
`available`, unaffected by the wording change on the collision path.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _minimal_payload(repo, derived_held, lane_patterns):
    return {
        "issue": 1528,
        "repo": str(repo),
        "config": {"state": "ok", "problems": []},
        "base": {
            "state": "resolved",
            "remote": "origin",
            "ref": "origin/main",
            "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "detail": "",
        },
        "branch": {
            "state": "resolved",
            "pattern": "fix/{issue}",
            "name": "fix/1528",
            "detail": "",
            "exists_local": False,
            "exists_remote": False,
        },
        "worktree": {
            "state": "resolved",
            "root": "/tmp",
            "path": "/tmp/1528",
            "detail": "",
            "exists": False,
        },
        "board": {"state": "ok", "lines": []},
        "lanes": None,
        "lane": lane_setup.lane_report(
            repo, lane_patterns, None, derived_held=derived_held
        ),
    }


def test_overlap_verdict_no_longer_reads_blocked(tmp_path):
    """The issue's own worked example (CLAUDE.md held by #1499, same file
    declared by this brief), shrunk to a synthetic file name rather than a
    real repo path -- `doctor_check_lane_coupling.py` statically scans this
    test's own source for literal paths matching a declared lane's globs,
    and a real cross-lane literal here (this file already imports
    `lane_setup`, lane-dispatch) would trip that guard for no reason: the
    subject under test is the receipt's wording, not which real lane the
    example file happens to belong to. The verdict must still name the
    file and the holder, but must not print the word BLOCKED."""
    (tmp_path / "held-example.txt").write_text("x\n")
    derived = {
        "state": "resolved",
        "held": {"held-example.txt": ["lane #1499"]},
        "detail": "",
    }
    payload = _minimal_payload(tmp_path, derived, ["held-example.txt"])
    text = lane_setup.receipt(payload)
    assert "BLOCKED" not in text
    assert "verdict : OVERLAP" in text
    assert "held-example.txt" in text
    assert "lane #1499" in text


def test_disjoint_lane_still_reads_available_the_positive_control(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived = {
        "state": "resolved",
        "held": {"scripts/other.py": ["lane #1"]},
        "detail": "",
    }
    payload = _minimal_payload(tmp_path, derived, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "verdict : available" in text
    assert "verdict : OVERLAP" not in text
