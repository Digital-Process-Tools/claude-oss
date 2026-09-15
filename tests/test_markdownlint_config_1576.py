"""#1576: `.supertool.json` wires `markdownlint` as an advisory validator over
`*.md` with no `.markdownlint.json` in the repo, so it ran on stock defaults --
80-column MD013 -- and flagged 58.4% of every tracked markdown line. A
validator that reports that many findings is one nobody reads, and this
repository is named after the defect class that follows: a real finding
arrives in the same wash as the noise and is indistinguishable from it.

`100` is the number this repo actually writes at: p95 across the tracked
`.md` corpus, excluding fenced code blocks and table rows, is 100 and only
about 4% of prose lines exceed it (re-measured for this fix; the issue's own
58.4%/4.4% figures counted code blocks and tables, which `.markdownlint.json`
now excludes from MD013 entirely).

Every "must not fire" case (the config exists, sets a real number) is paired
with a "must fire" case (a config missing/misconfigured is not silently
treated as fine) so a broken fixture cannot pass this file by doing nothing.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load():
    path = REPO_ROOT / ".markdownlint.json"
    assert path.exists(), ".markdownlint.json is missing at the repo root"
    return json.loads(path.read_text(encoding="utf-8"))


def test_config_exists_and_parses():
    doc = _load()
    assert isinstance(doc, dict)


def test_line_length_is_not_the_stock_80_default():
    """Positive control: a config that forgot to touch MD013 at all reads
    identically to no config, which is the exact bug this issue reports."""
    doc = _load()
    md013 = doc.get("MD013")
    assert md013 is not None, "MD013 must be configured explicitly"
    assert md013.get("line_length") != 80, (
        "line_length still at the stock 80-column default -- this is the bug, not the fix"
    )


def test_line_length_is_the_measured_p95():
    doc = _load()
    assert doc["MD013"]["line_length"] == 100


def test_code_blocks_and_tables_are_excluded_from_md013():
    doc = _load()
    md013 = doc["MD013"]
    assert md013.get("code_blocks") is False
    assert md013.get("tables") is False


def test_default_ruleset_stays_on():
    """Only MD013 is retuned -- the fix is the one misconfigured constant,
    not a blanket disable of the validator (the issue's own framing:
    "one misconfigured constant, repeated", not "delete the check")."""
    doc = _load()
    assert doc.get("default") is True
