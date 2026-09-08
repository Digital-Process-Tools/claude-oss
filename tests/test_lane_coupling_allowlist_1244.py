"""#1244: `scripts/lane_coupling.py` (#1234, PR #1243) derives which test files
span two or more declared lanes, mechanically -- and a real trial run over this
repo's own suite found 48 of 465 test files (~10%) already span two or more
lanes, mostly *intentionally*: a whole-repo guard test (e.g.
`tests/test_content_invariants.py`, `tests/test_unwired_scripts_253.py`) that
legitimately reads files from several lanes to check a cross-cutting
invariant, not an accidental coupling like #1201's own incident. Wiring the
check live as-is would either warn permanently on this repo -- violating this
repo's own doctor-check-contract rule that "if nothing can clear it, the bug
is in the check" -- or needs a noise-reduction design.

**Design chosen (stated in the PR body too): an allowlist, declared in
`.oss.json` itself** (`labels.lane_coupling_allowlist`), per this repo's own
governing rule that a fact about one repository never lives in shared code --
which test files intentionally span multiple lanes is exactly such a fact,
the same way `labels.lane_patterns` already is. A span whose test file is on
the allowlist is *acknowledged*, not a `finding`; a span whose test file is
NOT on the allowlist still fires -- so a genuinely new #1201-shaped incident
(a fresh, unnoticed pair) still reaches a maintainer, which is the entire
reason this module exists.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_coupling  # noqa: E402


def _scaffold_two_lane_repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "beta.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()


def test_allowlisted_span_is_acknowledged_not_a_finding(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_spans.py").write_text(
        'A = "scripts/alpha.py"\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(
        tmp_path, lane_patterns, allowlist=["tests/test_spans.py"]
    )
    assert result["state"] == "ok", result
    assert result["spans"] == []
    files = [entry[0] for entry in result["acknowledged"]]
    assert "tests/test_spans.py" in files


def test_a_new_unallowlisted_span_still_fires_the_must_fire_case(tmp_path):
    """The must-fire sibling: an allowlist that swallows every span defeats
    the module's entire purpose -- a fresh, unacknowledged coupling must
    still surface."""
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_spans.py").write_text(
        'A = "scripts/alpha.py"\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(
        tmp_path, lane_patterns, allowlist=["tests/test_something_else.py"]
    )
    assert result["state"] == "finding", result
    files = [entry[0] for entry in result["spans"]]
    assert "tests/test_spans.py" in files
    assert result["acknowledged"] == []


def test_omitting_the_allowlist_leaves_old_behaviour_untouched(tmp_path):
    """`allowlist=None` (the default) must behave exactly like #1234's own
    original module -- every span is unacknowledged, the same shape every
    existing caller and test already relies on."""
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_spans.py").write_text(
        'A = "scripts/alpha.py"\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "finding", result
    assert result["acknowledged"] == []


def test_real_repo_is_quiet_once_wired_with_its_own_declared_allowlist(
    lane_coupling_real_repo_report,
):
    """The issue's own verification instruction: running doctor should not
    produce ~48 warnings on this repo's own tree. `.oss.json`'s own
    `labels.lane_coupling_allowlist` (populated by this same fix) must
    acknowledge every span this repo's real suite has today.

    Routed through the shared `lane_coupling_real_repo_report` fixture
    (#1318, `tests/conftest.py`): `test_doctor_check_lane_coupling_1244.
    py::test_real_repo_is_quiet_the_issues_own_verification` walks this
    same real tree with the identical arguments, so the two tests share
    one computed answer rather than each paying for the walk."""
    import json

    config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    lane_patterns = config["labels"]["lane_patterns"]
    allowlist = config["labels"].get("lane_coupling_allowlist") or []
    result = lane_coupling_real_repo_report(
        REPO_ROOT, lane_patterns, allowlist=allowlist
    )
    assert result["spans"] == [], (
        "unacknowledged spans on this repo's own real suite: {}".format(
            [entry[0] for entry in result["spans"]]
        )
    )
    assert result["malformed"] == []
    assert result["unreadable"] == []
    assert result["state"] == "ok", result
