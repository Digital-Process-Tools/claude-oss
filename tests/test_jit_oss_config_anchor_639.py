"""#639: the jit-context oss-config.md rule matches `.oss.json` unanchored, so it
fires wherever that name occurs -- `.oss.json.bak`, an inner path segment, anything.
`scripts/oss_rules.py`'s `OSS_CONFIG` is the twin written into every scaffolded
repository (the same shape #577 fixed for TOOLS_SUPERTOOL), so both copies are covered
here rather than just the tracked `.md`.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

RULE_MD = REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "oss-config.md"


def _frontmatter_match(body):
    for line in body.splitlines():
        if line.startswith("match:"):
            return line[len("match:"):].strip()
    raise AssertionError("no match: line found in frontmatter")


def _pattern_from_md():
    return _frontmatter_match(RULE_MD.read_text(encoding="utf-8"))


def _pattern_from_py():
    return _frontmatter_match(oss_rules.OSS_CONFIG)


def test_pattern_matches_oss_json_paths():
    """The must-fire case: a real .oss.json path, at the root or nested."""
    pattern = _pattern_from_md()
    assert re.search(pattern, ".oss.json")
    assert re.search(pattern, "sub/.oss.json")


def test_pattern_does_not_match_backup_or_inner_segment():
    """The must-not-fire case, paired with the must-fire case above so a broken
    pattern (matching nothing) cannot pass this half by accident.
    """
    pattern = _pattern_from_md()
    assert not re.search(pattern, ".oss.json.bak")
    assert not re.search(pattern, ".oss.json.orig")
    assert not re.search(pattern, "sub/.oss.json.bak")


def test_py_and_md_patterns_agree():
    """The two copies must ship the same pattern -- OSS_CONFIG is what actually
    reaches every scaffolded repository; the tracked .md is what this repository's
    own sessions read. A fix applied to only one ships a stale rule to everyone else.
    """
    assert _pattern_from_md() == _pattern_from_py()


def test_index_tsv_agrees_with_the_md_pattern():
    """A third copy: `00-index.tsv` is a build artifact `rebuild-tsv.sh` derives from
    the .md frontmatter, and nothing regenerates it automatically -- an edit to the
    .md's `match:` line that forgets to rebuild the index ships a rule whose live
    pattern (the tsv) disagrees with its documented one (the .md), which is exactly
    the gap #639 was filed over on the .md/OSS_CONFIG pair. jit-dry-run.sh reads the
    tsv, not the .md, so this is the one that actually governs whether the rule
    fires unanchored.
    """
    index = REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "00-index.tsv"
    rows = [
        line.split(chr(9)) for line in index.read_text(encoding="utf-8").splitlines() if line
    ]
    matches = [row[0] for row in rows if len(row) > 1 and row[1] == "oss-config.md"]
    assert matches == [_pattern_from_md()]
