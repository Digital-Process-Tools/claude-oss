"""#1348: CLAUDE.md's ownership table and scripts/scaffold.OWNED are two
machine-readable statements of what this plugin owns in a managed repository, and
nothing compared them -- which is how the table went on omitting `trap.d/README.md`
for a full release cycle after #1302 added it to `OWNED`.

Same shape as tests/test_claude_md_budget_table_709.py: parse the table row, derive
the expected set from the module, compare. `scaffold.OWNED`'s three `.oss/*` entries
collapse to one directory-level `.oss/` in the table (the table already renders it
that way, since `.oss/` is owned outright and every file inside it is OURS) -- so the
derivation groups any `OWNED` key under `OWNED_DIR` into that one directory entry, and
keeps every other `OWNED` key (the workflow file, `trap.d/README.md`) as an exact
path, matching how the table already renders them. The `.claude/jit-context/*/01-oss/`
entry is not in `OWNED` at all -- it comes from `scaffold.RULES_LAYER_DIR`, a separate
mechanism (`rule_layer_paths()`) -- so it is added to the derived set by name rather
than discovered from `OWNED`, the one piece this comparison cannot get from `OWNED`
alone.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scaffold  # noqa: E402

CLAUDE_MD = ROOT / "CLAUDE.md"


def _ours_row_paths():
    """Every backtick-quoted path in the ownership table's `ours` row, read from
    CLAUDE.md rather than assumed.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    header = "## Three ownership contracts"
    assert header in text, "CLAUDE.md's ownership section header moved or was renamed"
    section_start = text.index(header)
    row_start = text.index("| **ours**", section_start)
    row_end = text.index("\n", row_start)
    row = text[row_start:row_end]
    return re.findall(r"`([^`]+)`", row)


def _expected_ours_paths():
    """Derive what the `ours` row must name, from scaffold.py's own OWNED dict (the
    real, executable statement of what this plugin writes into a managed repo) plus
    the one owned surface OWNED does not cover, the jit-context rule layer.
    """
    expected = set()
    for path in scaffold.OWNED:
        if path.startswith(scaffold.OWNED_DIR + "/"):
            expected.add(scaffold.OWNED_DIR + "/")
        else:
            expected.add(path)
    expected.add(scaffold.RULES_LAYER_DIR + "/*/01-oss/")
    return expected


def test_ownership_table_names_every_owned_path():
    table_paths = set(_ours_row_paths())
    assert table_paths, "no backtick paths found in the ownership table's ours row"
    expected = _expected_ours_paths()
    assert table_paths == expected, (
        "CLAUDE.md's ownership table 'ours' row and scaffold.py's OWNED set disagree "
        "(table vs. derived): table only: {}, derived only: {}".format(
            sorted(table_paths - expected), sorted(expected - table_paths)
        )
    )
