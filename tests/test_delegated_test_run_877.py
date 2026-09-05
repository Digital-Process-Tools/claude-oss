"""A test run's verdict is never delegated -- the rest of the Bash-granted
agents (#877, following #874/#876).

#874 was observed in a developer lane, so `agents/developer.md` got the rule and
`tests/test_delegated_test_run_874.py` guards it. That left every other
`Bash`-granted definition free of it: `agents/auditor.md`,
`agents/release-auditor.md`, `agents/sub-manager.md` and `agents/releaser.md` are
all granted `Bash`, and nothing in any of the four said a suite run is not
theirs to run, nor that a verdict reported by a spawned agent is a claim rather
than a receipt.

Each definition is entitled to something different, so this is not one shared
sentence copy-pasted four times:

- the two auditors may read test files, reason about coverage, and name a test
  that should exist -- never run the suite, never ask a spawned agent for a
  verdict on one, and a load-bearing claim about test behaviour says it is
  reasoned rather than observed;
- the sub-manager reads CI rather than reproducing it;
- the releaser is bound by the release gate's own capped budget, same as the
  auditors.

The set of files this module holds accountable is derived from disk rather
than hand-listed, via `agents/*.md` filtered to a `Bash` grant -- the same
derivation `tests/test_agent_grant_is_total.py` already uses for a different
concern. `agents/developer.md` is excluded because #874's own test already
covers it, and `agents/triager.md` is excluded because it never touches code
and has no test-running concern to state a rule about -- both exclusions are
named and asserted below, so a *third* Bash-granted file added later that
falls into neither bucket fails loudly here instead of being silently outside
every check, which is the failure mode `checklist_skew.py` already records
for a guard pinned to a hand-kept list.

Each assertion carries its own negative-control fixture: the file's text with
the required marker removed, proving the check would fail on a copy that lost
the sentence rather than passing on any input.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

#: #874's own test already guards this file -- do not duplicate its checks here.
ALREADY_COVERED_ELSEWHERE = {"developer.md"}

#: Granted `Bash` but never runs or reasons about a test suite -- it "never
#: touches code" (agents/triager.md's own frontmatter description), so there is
#: no test-behaviour claim for it to make.
NO_TEST_CONCERN = {"triager.md"}

#: filename -> the marker that must survive in the file, verbatim.
REQUIRED_MARKER = {
    "auditor.md": "may not ask a spawned agent for a verdict on one",
    "release-auditor.md": "may not ask a spawned agent for a verdict on one",
    "sub-manager.md": "A tick reads CI; it does not reproduce it.",
    "releaser.md": "may not ask a spawned agent for a verdict\non one.",
}


def _text(name):
    return (AGENTS_DIR / name).read_text(encoding="utf-8")


def _granted_bash(path):
    """True/False, or raises when the frontmatter carries no parseable `tools:`
    line at all. A missing grant and an unparseable one are not the same fact
    (#877 audit round, class A): `tests/test_agent_grant_is_total.py`'s own
    `granted_tools` already keeps a bare `None` for exactly this case rather
    than folding it into "no Bash", so this module does the same rather than
    silently reading a malformed or reformatted frontmatter block as a file
    that plainly declares no Bash grant.
    """
    block = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    line = re.search(r"^tools:\s*(.+)$", block, re.MULTILINE)
    assert line is not None, (
        "{0}: no parseable `tools:` line in its frontmatter -- cannot tell "
        "whether it grants Bash, so it cannot be silently treated as if it "
        "did not (#877)".format(path)
    )
    tools = {t.strip() for t in line.group(1).split(",") if t.strip()}
    return "Bash" in tools


def bash_granted_agent_names():
    return {p.name for p in sorted(AGENTS_DIR.glob("*.md")) if _granted_bash(p)}


def test_a_frontmatter_with_no_tools_line_is_not_read_as_no_bash_grant(tmp_path):
    """Positive control for the fix above: a malformed frontmatter must raise,
    never quietly return False the same as a file that plainly grants no
    tools."""
    malformed = tmp_path / "malformed.md"
    malformed.write_text("---\nname: malformed\n---\n\nbody\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        _granted_bash(malformed)


def test_agents_directory_is_not_empty():
    assert list(AGENTS_DIR.glob("*.md")), (
        "no agents/*.md found -- every check below would vacuously pass"
    )


def test_every_bash_granted_agent_is_accounted_for():
    """A new Bash-granted definition must land in exactly one bucket: covered
    elsewhere, exempt with a reason, or required to carry the marker here --
    never silently outside all three."""
    accounted = ALREADY_COVERED_ELSEWHERE | NO_TEST_CONCERN | set(REQUIRED_MARKER)
    unaccounted = bash_granted_agent_names() - accounted
    assert not unaccounted, (
        "Bash-granted agent definition(s) {0} are not in "
        "ALREADY_COVERED_ELSEWHERE, NO_TEST_CONCERN or REQUIRED_MARKER in this "
        "file -- decide which bucket each belongs in rather than leaving it "
        "unchecked (#877)".format(sorted(unaccounted))
    )


def test_developer_and_triager_are_still_the_named_exceptions():
    """Pin the two exclusions so a future edit that widens either set is a
    deliberate change to this file, not a silent one."""
    granted = bash_granted_agent_names()
    assert "developer.md" in granted, (
        "agents/developer.md no longer grants Bash -- re-check the #874 exclusion"
    )
    assert "triager.md" in granted, (
        "agents/triager.md no longer grants Bash -- re-check the no-test-concern exclusion"
    )


def _assert_marker_with_control(name, marker):
    text = _text(name)
    assert marker in text, (
        "agents/{0} does not state {1!r} -- the delegated-test-run rule "
        "(#877) appears to be missing or reworded".format(name, marker)
    )
    without_it = text.replace(marker, "")
    assert without_it != text, (
        "fixture construction did not remove the marker -- control is void"
    )
    assert marker not in without_it


def test_auditor_bounds_test_behaviour_to_reasoned_not_run():
    _assert_marker_with_control("auditor.md", REQUIRED_MARKER["auditor.md"])
    text = _text("auditor.md")
    assert "may not run the suite" in text
    assert "`reasoned`" in text and "`observed`" in text


def test_release_auditor_bounds_test_behaviour_to_reasoned_not_run():
    _assert_marker_with_control(
        "release-auditor.md", REQUIRED_MARKER["release-auditor.md"]
    )
    text = _text("release-auditor.md")
    assert "may not run the suite" in text
    assert "`reasoned`" in text and "`observed`" in text


def test_sub_manager_reads_ci_rather_than_reproducing_it():
    _assert_marker_with_control("sub-manager.md", REQUIRED_MARKER["sub-manager.md"])
    text = _text("sub-manager.md")
    assert "not a local suite run" in text


def test_releaser_is_bound_by_the_same_rule_as_the_auditors():
    _assert_marker_with_control("releaser.md", REQUIRED_MARKER["releaser.md"])
    text = _text("releaser.md")
    assert "Same as the two auditors" in text
    assert "`reasoned`" in text and "`observed`" in text


def test_required_marker_covers_exactly_the_non_excluded_bash_granted_agents():
    """The registry is not a superset or a subset of the derived set -- both
    directions are checked so a stale entry (file deleted or Bash grant
    removed) is caught, not just a missing one."""
    granted = bash_granted_agent_names()
    expected = granted - ALREADY_COVERED_ELSEWHERE - NO_TEST_CONCERN
    assert set(REQUIRED_MARKER) == expected, (
        "REQUIRED_MARKER {0} does not match the derived set {1} -- a file was "
        "added, removed, or its Bash grant changed without this module being "
        "updated (#877)".format(sorted(REQUIRED_MARKER), sorted(expected))
    )
