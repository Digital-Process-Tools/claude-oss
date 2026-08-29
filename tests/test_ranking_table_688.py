"""#688: the release-audit payload requires the ranking table pasted into it
verbatim (`commands/release.md` gate 3), and a human transcription of it silently
dropped the embargo prose on two rows -- bare "yes" / "no" instead of the reasons
the table carries. This pins `scripts/ranking_table.py`, an extractor that reads
the table straight out of the installed `skills/manager/SKILL.md` rather than
having a human retype it.

Every negative case here is paired with the positive it is not: a fixture with a
well-formed table must extract, and the same fixture broken one way at a time
must refuse rather than emit a partial table.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ranking_table.py"

FOUND = "found"
NOT_FOUND = "not-found"
COULD_NOT_READ = "could-not-read"


def _module():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import ranking_table

    return ranking_table


WELL_FORMED = """- **Rank by what cannot be undone**, then by who is walking away:

  | Class | Blocks a release? | Embargo when reported upstream? |
  | --- | --- | --- |
  | `destroys` -- data gone, no copy anywhere | yes, unconditionally | yes |
  | `misreports` | can ship behind a filed issue | no |

  **This table is the only place the rows are written down.**
"""


def test_script_exists():
    assert SCRIPT.is_file(), "scripts/ranking_table.py is missing"


# --------------------------------------------------------------------- found


def test_extracts_well_formed_table():
    mod = _module()
    state, table, reason = mod.extract_ranking_table(WELL_FORMED)
    assert state == FOUND
    assert reason is None
    assert "| Class | Blocks a release? | Embargo when reported upstream? |" in table
    assert "`destroys`" in table
    assert "`misreports`" in table
    # nothing past the table's own blank line leaked in
    assert "only place the rows are written down" not in table


def test_extracts_the_real_table_from_this_repos_own_skill_md():
    """Positive control against the real file, not a fixture -- if the table
    in `skills/manager/SKILL.md` is ever reshaped, this is the test that
    should be the first to notice."""
    mod = _module()
    real_text = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    state, table, reason = mod.extract_ranking_table(real_text)
    assert state == FOUND, reason
    for row in ("destroys", "discloses", "forges", "ships-local-state", "misreports"):
        assert "`{0}`".format(row) in table


# ----------------------------------------------------------------- not-found


def test_must_fire_when_header_absent():
    mod = _module()
    state, table, reason = mod.extract_ranking_table("nothing here about a table\n")
    assert state == NOT_FOUND
    assert table is None
    assert reason


def test_must_fire_when_divider_row_missing():
    """Header present, but the next line is not a markdown divider -- the
    table was reshaped. Must refuse, not print a truncated table."""
    mod = _module()
    broken = """  | Class | Blocks a release? | Embargo when reported upstream? |
  | `destroys` -- data gone | yes | yes |
"""
    state, table, reason = mod.extract_ranking_table(broken)
    assert state == NOT_FOUND
    assert table is None
    assert reason


def test_must_fire_when_row_column_count_disagrees_with_header():
    """A row with a different number of columns than the header is a reshape
    the extractor cannot safely paste around -- refuse rather than guess."""
    mod = _module()
    broken = """  | Class | Blocks a release? | Embargo when reported upstream? |
  | --- | --- | --- |
  | `destroys` -- data gone | yes, unconditionally | yes | extra |
"""
    state, table, reason = mod.extract_ranking_table(broken)
    assert state == NOT_FOUND
    assert table is None
    assert reason


def test_must_fire_when_zero_data_rows():
    mod = _module()
    broken = """  | Class | Blocks a release? | Embargo when reported upstream? |
  | --- | --- | --- |

  some other text
"""
    state, table, reason = mod.extract_ranking_table(broken)
    assert state == NOT_FOUND
    assert table is None
    assert reason


# ------------------------------------------------------------- could-not-read


def test_could_not_read_when_skill_md_missing(tmp_path):
    mod = _module()
    state, table, reason = mod.load_table(str(tmp_path))
    assert state == COULD_NOT_READ
    assert table is None
    assert reason


def test_found_when_skill_md_present(tmp_path):
    """Positive control paired with the missing-file case above."""
    mod = _module()
    skill_dir = tmp_path / "skills" / "manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")
    state, table, reason = mod.load_table(str(tmp_path))
    assert state == FOUND, reason
    assert "`destroys`" in table


# --------------------------------------------------------------------- CLI


def test_cli_prints_table_verbatim_and_exits_zero(tmp_path):
    skill_dir = tmp_path / "skills" / "manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--plugin-root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "| Class | Blocks a release? | Embargo when reported upstream? |" in result.stdout
    assert "`destroys`" in result.stdout


def test_cli_prints_nothing_on_stdout_when_not_found(tmp_path):
    """The failure state must never print a partial table on stdout."""
    skill_dir = tmp_path / "skills" / "manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("no table here\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--plugin-root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip()


def test_cli_could_not_read_when_no_plugin_root(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip()
