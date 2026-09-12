"""#1431: sweep stale bare `/oss:setup` etc. remedy strings after the picker

demotion (#1389). `setup`, `scaffold`, `triage`, `curate` and `changelog` no
longer resolve as top-level slash commands -- only `/oss:run <step>` (or a
direct file read) reaches them. This pins the two still-top-level command
files this lane owns (`commands/doctor.md`, `commands/tick.md`) so their own
*instructive* remedy strings (telling a reader what to run as the fix) say
`/oss:run <step>` rather than the dead bare form.

This deliberately does not assert commands/doctor.md is free of every bare
`/oss:scaffold` substring: several remaining ones are literal quotes of
scripts/doctor.py's own generated WARN text (out of this lane's scope), and
changing the doc's quote without changing the generator would make the doc
lie about what the generator actually prints.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_tick_md_setup_remedy_uses_run_form():
    text = _text("commands/tick.md")
    assert "Stop and say so. `/oss:run setup` writes it." in text
    assert "Stop and say so. `/oss:setup` writes it." not in text


def test_doctor_md_missing_config_remedy_uses_run_form():
    text = _text("commands/doctor.md")
    assert "the fix is `/oss:run setup`. Offer it" in text
    assert "the fix is `/oss:setup`. Offer it" not in text


def test_doctor_md_next_step_naming_uses_run_form():
    text = _text("commands/doctor.md")
    assert "name **`/oss:run scaffold`** as the next step first" in text
    assert "name **`/oss:scaffold`** as the next step first" not in text


def test_doctor_md_literal_generator_quotes_are_untouched():
    """The remaining bare `/oss:scaffold` mentions in commands/doctor.md are
    literal quotes of scripts/doctor.py's own generated remedy text -- pinned
    here so a future edit does not silently drift the two apart. The
    generator's own second sentence is split across concatenated Python
    string literals in its source, so it is checked as two shorter
    fragments that each land on one source line rather than as one
    contiguous substring."""
    doctor_text = _text("commands/doctor.md")
    generator_text = _text("scripts/doctor.py")
    assert "not in this repo. Run /oss:scaffold." in doctor_text
    assert "not in this repo. Run /oss:scaffold." in generator_text
    assert "Run /oss:scaffold, which reports what it could not read." in doctor_text
    assert "Run /oss:scaffold, which reports what " in generator_text
    assert "it could not read." in generator_text
