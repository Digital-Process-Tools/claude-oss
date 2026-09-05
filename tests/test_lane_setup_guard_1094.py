"""#1094: `lane_setup.py`'s derived guard set for `skills/manager/SKILL.md` and
`skills/manager/phases/*.md` never named `tests/test_command_references.py`, so
a real cross-file collision (PR #1091) reached CI before it reached a lane's own
narrowed local run.

`tests/test_command_references.py`'s `_enumerates_both_sides_of_the_boundary`
check runs over the *concatenated* text of `skills/manager/SKILL.md` plus every
`skills/manager/phases/*.md` file -- a check spanning several files at once, not
one keyed to a single module. `SKILL.md` itself can be byte-identical between two
branches while a phases file alone breaks the check, so #432's own scan (grep the
touched file's own content for known trigger substrings) cannot discover this
guard from the diff -- it has to be declared, the same way #432 itself was.

Every "must fire" case here has a "must not fire" sibling, this repository's own
convention: a lane touching a phases file must trip this guard, and a lane
touching an unrelated file under `skills/` must not additionally trip it.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def test_skill_md_change_trips_command_references_guard():
    hits = lane_setup.guards_for_files(["skills/manager/SKILL.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_command_references.py" in tests_hit


def test_a_phases_file_change_trips_command_references_guard():
    hits = lane_setup.guards_for_files(["skills/manager/phases/merge.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_command_references.py" in tests_hit


def test_a_different_phases_file_also_trips_the_guard():
    """The positive control is not a fluke of one filename: every file under
    `skills/manager/phases/` shares the same trigger, because the check that
    guard exists to catch concatenates all of them, not just one."""
    hits = lane_setup.guards_for_files(["skills/manager/phases/dispatch.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_command_references.py" in tests_hit


def test_an_unrelated_skills_file_does_not_trip_it():
    """The must-not-fire sibling: this guard is scoped to the two paths whose
    concatenation the real check reads, not to all of `skills/` -- widening it
    to everything under `skills/` would report every skills-touching lane as
    universally guarded by this test, which is not true (`test_command_references.py`
    never reads e.g. a hypothetical `skills/other-skill/SKILL.md`)."""
    hits = lane_setup.guards_for_files(["skills/other-skill/SKILL.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_command_references.py" not in tests_hit


def test_known_guards_now_carries_six_distinct_test_files():
    """#432's own sizing test pinned five; this issue adds a sixth guard test to
    the enumeration, so the count moves with it rather than silently drifting."""
    known = lane_setup.known_guards()
    test_paths = [entry["test"] for entry in known]
    assert len(test_paths) == 6
    assert "tests/test_command_references.py" in test_paths
