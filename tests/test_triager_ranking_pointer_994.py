"""#994: `agents/triager.md` pointed the ranking table at `skills/manager/SKILL.md`,
which `#958` moved out to `skills/manager/phases/findings.md` and `#960` moved the
`Deciding what to build` section it navigated by out to `phases/dispatch.md`. Both
halves of the pointer went stale, in the same file that names why a stale copy is
worse than an absent one.

The fix names `scripts/ranking_table.py` -- which already searches both locations in
order, precisely so a future move cannot silently break a caller again -- rather than
a bare path, so this cannot recur the same way twice.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGER = REPO_ROOT / "agents" / "triager.md"


def _text():
    return TRIAGER.read_text(encoding="utf-8")


def test_the_pointer_names_the_script_not_a_bare_path():
    text = _text()
    assert "scripts/ranking_table.py" in text, (
        "agents/triager.md does not name scripts/ranking_table.py -- a bare path "
        "pointer is exactly what broke twice already (#958, #960)"
    )


def test_the_stale_skill_md_pointer_is_gone():
    text = _text()
    assert "skills/manager/SKILL.md" not in text, (
        "agents/triager.md still points at skills/manager/SKILL.md for the ranking "
        "table, which #958 moved to skills/manager/phases/findings.md"
    )
