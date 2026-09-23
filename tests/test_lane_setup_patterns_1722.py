"""#1722: `CROSS_CUTTING_GUARDS` has no extension point for a managed repo's own
guards. Every entry in the built-in table names a claude-oss path -- its own
docstring says so -- so a repo this loop merely operates on (claude-supertool,
concretely, per the issue's own #2658 measurement) had no way to register a
cross-cutting guard test of its own that a lane's file-set search should have
anticipated before dispatch.

The fix: `.oss.json` may carry an optional `lane_guards` key, a list of
`{prefix, test, why}` objects in the same shape `CROSS_CUTTING_GUARDS` already
uses, that `lane_setup_patterns.known_guards`/`guards_for_files` merge in
whenever a caller passes `repo`.

Every "must fire" case here has a "must not fire" sibling, per CLAUDE.md's own
rule: a repo that declares a guard must have it show up, and a repo that
declares nothing (or something malformed) must see only the built-in table,
never a spurious extra entry and never a crash.
"""

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402
import oss_config  # noqa: E402


def _repo_with_declared_guard(tmp_path, lane_guards):
    """A minimal managed repo carrying a tracked `.oss.json` declaring
    `lane_guards`, plus the one file a lane's resolved-files list would name."""
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "watch.json").write_text("{}\n")
    config = {"lane_guards": lane_guards} if lane_guards is not None else {}
    (tmp_path / ".oss.json").write_text(json.dumps(config))
    return tmp_path


# --- must fire: a declared guard shows up, merged with the built-in table ------


def test_guards_for_files_includes_a_repo_declared_guard():
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        repo = _repo_with_declared_guard(
            tmp_path,
            [
                {
                    "prefix": "presets/",
                    "test": "tests/test_render_size_claims_1877.py",
                    "why": "a preset op description changing size may cross a "
                    "docs figure this test pins",
                }
            ],
        )
        hits = lane_setup.guards_for_files(["presets/watch.json"], repo=repo)
        entry = next(
            e for e in hits if e["test"] == "tests/test_render_size_claims_1877.py"
        )
        assert entry["why"] == [
            "a preset op description changing size may cross a docs figure "
            "this test pins"
        ]


def test_known_guards_includes_a_repo_declared_guard():
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        repo = _repo_with_declared_guard(
            tmp_path,
            [
                {
                    "prefix": "presets/",
                    "test": "tests/test_render_size_claims_1877.py",
                    "why": "a preset op description changing size may cross a "
                    "docs figure this test pins",
                }
            ],
        )
        known = lane_setup.known_guards(repo=repo)
        assert any(e["test"] == "tests/test_render_size_claims_1877.py" for e in known)


# --- must not fire: no lane_guards declared, only the built-in table applies ---


def test_guards_for_files_adds_nothing_when_the_repo_declares_no_guards():
    """Positive control for the case above: a repo carrying an `.oss.json` with
    no `lane_guards` key at all must see exactly the built-in table's own
    entries, never a phantom extra one."""
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        repo = _repo_with_declared_guard(tmp_path, None)
        hits = lane_setup.guards_for_files(["presets/watch.json"], repo=repo)
        assert hits == []


def test_guards_for_files_ignores_a_repo_with_no_config_at_all():
    """A managed repo with no `.oss.json` whatsoever (the ordinary state before
    /oss:setup has run) must not crash and must add nothing."""
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        (tmp_path / "presets").mkdir()
        hits = lane_setup.guards_for_files(["presets/watch.json"], repo=tmp_path)
        assert hits == []


def test_guards_for_files_ignores_a_malformed_oss_json():
    """A syntactically broken `.oss.json` (config validation reports this
    separately, in the lane's own `config` payload section) must not crash the
    guard merge or silently invent guards -- it degrades to the built-in
    table only."""
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        (tmp_path / "presets").mkdir()
        (tmp_path / ".oss.json").write_text("{not json")
        hits = lane_setup.guards_for_files(["presets/watch.json"], repo=tmp_path)
        assert hits == []


def test_guards_for_files_skips_a_malformed_entry_but_keeps_the_rest():
    """One bad sibling in an otherwise-valid `lane_guards` list must not
    discard the whole declared list -- the same partial-coverage shape
    `guards_for_files` already gives a partially-covered file set."""
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        repo = _repo_with_declared_guard(
            tmp_path,
            [
                {"prefix": "presets/", "test": "", "why": "missing test path"},
                {
                    "prefix": "presets/",
                    "test": "tests/test_render_size_claims_1877.py",
                    "why": "a real guard",
                },
            ],
        )
        hits = lane_setup.guards_for_files(["presets/watch.json"], repo=repo)
        tests = {e["test"] for e in hits}
        assert "tests/test_render_size_claims_1877.py" in tests
        assert "" not in tests


def test_repo_none_never_reads_lane_guards_at_all():
    """`repo=None` -- claude-oss's own sizing test's own shape -- must keep the
    declared enumeration exactly as before this key existed; no filesystem
    read is even attempted."""
    known = lane_setup.known_guards()
    assert known and "status" not in known[0]


# --- .oss.json's own validator, the other half of the extension point ----------


def test_lane_guards_problem_accepts_none():
    assert oss_config.lane_guards_problem(None) is None


def test_lane_guards_problem_accepts_a_well_formed_list():
    assert (
        oss_config.lane_guards_problem(
            [{"prefix": "presets/", "test": "tests/x.py", "why": "because"}]
        )
        is None
    )


def test_lane_guards_problem_refuses_an_empty_list():
    problem = oss_config.lane_guards_problem([])
    assert problem is not None
    assert "lane_guards" in problem


def test_lane_guards_problem_refuses_a_missing_field():
    problem = oss_config.lane_guards_problem(
        [{"prefix": "presets/", "test": "tests/x.py"}]
    )
    assert problem is not None
    assert "why" in problem


def test_lane_guards_problem_refuses_a_non_string_field():
    problem = oss_config.lane_guards_problem(
        [{"prefix": "presets/", "test": "tests/x.py", "why": 5}]
    )
    assert problem is not None
