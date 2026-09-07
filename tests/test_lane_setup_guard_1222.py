"""#1222: `lane_setup.py`'s cross-cutting-guard derivation for a NEW
`scripts/*.py` file never named `tests/test_bare_gh_git_spawn_sweep_1165.py`
-- the repo-wide sweep for exactly this class of defect (a bare, unrouted
`gh`/`git` subprocess spawn under `scripts/`), which this repo has already
paid for five times over (#1157, #1163, #1168, #1172, #1173). Its own
docstring says it "scans every `scripts/*.py` file" -- the same shape
#1094 (test_command_references.py) and #328 (test_gate_state_consumers_328.py)
already used to justify a directory-prefix trigger rather than an
enumeration of today's call sites, and `CROSS_CUTTING_GUARDS` never
declared it.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def test_a_new_scripts_file_trips_the_bare_spawn_sweep_guard():
    hits = lane_setup.guards_for_files(["scripts/some_brand_new_script.py"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_bare_gh_git_spawn_sweep_1165.py" in tests_hit


def test_a_touched_existing_scripts_file_also_trips_it():
    hits = lane_setup.guards_for_files(["scripts/lane_setup.py"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_bare_gh_git_spawn_sweep_1165.py" in tests_hit


def test_an_unrelated_top_level_file_does_not_trip_it():
    hits = lane_setup.guards_for_files(["README.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_bare_gh_git_spawn_sweep_1165.py" not in tests_hit
