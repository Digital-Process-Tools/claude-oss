"""#1014: the "measured (baseline)" column three modules declare --
`agent_budgets.BUDGETS`, `skill_phases.DOCUMENTS`, `command_budgets.BUDGETS` --
and the CLAUDE.md tables built on top of it (held against these same dicts by
#709/#725) can all drift from the file's actual size on disk without any test
noticing, because `check()` in every one of those modules only ever compares
the measured size against `budget` (the ceiling). A baseline can go stale
indefinitely and nothing reports it: #709's own test, `test_claude_md_budget_
table_709.py`, holds CLAUDE.md against `agent_budgets.BUDGETS` -- and both
sides can quote the identical *wrong* number forever, because neither is ever
checked against the file the number is supposed to describe.

Mechanism, demonstrated at filing time: `agents/sub-manager.md` measured
16,341 B on disk while `agent_budgets.BUDGETS["agents/sub-manager.md"]`
still declared a baseline of 15,501 -- under budget (17,000), so `check()`
reported `ok`, and #709's test passed too, because CLAUDE.md's own table
quoted that same stale 15,501.

This closes the gap the dedicated way #725's own docstring already points
at ("similar in spirit ... but for the *measured* column rather than the
*budget* column") rather than by adding a new `check()` state: a fourth
module (`command_budgets.py`) already exists with the identical shape, and a
single comparison here covers all three without touching any of their
`check()` return shapes, which other callers (`doctor.py`) already consume.

Two directions, in the same fixture per this repo's own rule that a negative
assertion needs a positive control: `test_stale_baseline_is_detected` proves
the comparison actually fires on a real mismatch (using a synthetic pair
pointed at this very test file, whose size does not match a made-up
baseline) -- the "must fire" case that a vacuously-true comparison would
silently drop. `test_matching_baseline_is_not_flagged` is its sibling: a
synthetic pair whose baseline is the file's own actual size must report
nothing.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_budgets  # noqa: E402
import command_budgets  # noqa: E402
import skill_phases  # noqa: E402


def _stale_baselines(pairs, root):
    """`[(path, declared_baseline, actual_size)]` for every pair whose declared
    baseline does not match the file's current size on disk. `pairs` is
    `{repo-relative path: declared baseline}` -- deliberately just the two
    numbers this needs, so the same helper serves all three modules and the
    synthetic fixtures below without caring about each module's own tuple
    shape (`skill_phases.DOCUMENTS` carries a third `governs` element the
    other two do not).

    A file that does not exist on disk is not this function's finding to
    make -- that is `missing`, already reported by each module's own
    `check()` -- so it is skipped here rather than raised or silently
    treated as a size-zero mismatch.
    """
    mismatches = []
    for rel, declared_baseline in pairs.items():
        path = root.joinpath(*rel.split("/"))
        try:
            actual = len(path.read_bytes())
        except FileNotFoundError:
            continue
        if actual != declared_baseline:
            mismatches.append((rel, declared_baseline, actual))
    return mismatches


def _declared_pairs():
    pairs = {rel: baseline for rel, (baseline, _budget) in agent_budgets.BUDGETS.items()}
    pairs.update(
        {rel: baseline for rel, (baseline, _budget) in command_budgets.BUDGETS.items()}
    )
    pairs.update(
        {rel: baseline for rel, (baseline, _budget, _governs) in skill_phases.DOCUMENTS.items()}
    )
    return pairs


def test_declared_baselines_match_disk():
    root = agent_budgets.repo_root()
    mismatches = _stale_baselines(_declared_pairs(), root)
    assert not mismatches, (
        "declared baseline disagrees with the file's actual size on disk "
        "(path, declared baseline, actual size): "
        + ", ".join(f"{p}: declared {b}, actual {a}" for p, b, a in mismatches)
    )


def test_stale_baseline_is_detected():
    """Must-fire control: a baseline that does not match reality is reported,
    not silently accepted -- the failure mode #1014 was filed against.
    """
    root = ROOT
    this_file = "tests/test_baseline_matches_disk_1014.py"
    real_size = len((root / this_file).read_bytes())
    fake_pairs = {this_file: real_size + 1}
    mismatches = _stale_baselines(fake_pairs, root)
    assert mismatches == [(this_file, real_size + 1, real_size)]


def test_matching_baseline_is_not_flagged():
    """Must-not-fire control, paired with the one above in the same fixture:
    a baseline that does match reality reports nothing.
    """
    root = ROOT
    this_file = "tests/test_baseline_matches_disk_1014.py"
    real_size = len((root / this_file).read_bytes())
    fake_pairs = {this_file: real_size}
    assert _stale_baselines(fake_pairs, root) == []


def test_missing_file_is_skipped_not_raised():
    """A declared path with no file on disk is `missing`'s finding to make
    (each module's own `check()` already reports it), not this comparison's
    -- so it must not raise and must not appear as a mismatch.
    """
    root = ROOT
    fake_pairs = {"scripts/does-not-exist-1014.py": 12345}
    assert _stale_baselines(fake_pairs, root) == []
