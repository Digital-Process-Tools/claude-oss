"""#469: `_rglob_md` matched `.md` case-sensitively (`name.endswith(".md")`), where
the two `Path.rglob("*.md")` walks it replaced (#463, for the swallow #383 fixed) were
case-insensitive on Windows -- a jit rules directory holding only `.MD` files would
newly report *holds no rules* there.

Graded reasoned, not observed, by the auditor who filed it: Darwin agrees with the old
and the new behaviour, so the divergence is Windows-only and could not be run here
either. What settles it without needing a Windows machine is that the fix does not lean
on the *filesystem's* case-folding at all -- `os.walk` returns directory entries exactly
as stored on every platform; only the matching decision differed. Folding the case in
Python, once, before comparing to `.md`, is deterministic in exactly the same way on
every OS this repo supports, so the assertion below needs no platform skip and no
control fixture the way a filesystem case-behaviour question would (CLAUDE.md's
permission-fixture bullet, one axis over): it is not measuring what NTFS or APFS does,
it is measuring what this function's own string comparison does, which does not vary.

The direction chosen is cross-platform *consistency with the walk this replaced* --
restoring what `Path.rglob("*.md")` already did on Windows -- documented as a decision
rather than left implicit, per the issue's own "what would settle it".
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def test_uppercase_extension_is_found(tmp_path):
    """The must-fire half: a `.MD` file, alone, must not read as an empty directory."""
    (tmp_path / "RULES.MD").write_text("# rules\n", encoding="utf-8")

    files, unreadable = doctor._rglob_md(tmp_path)

    assert not unreadable
    names = sorted(p.name for p in files)
    assert "RULES.MD" in names, names


def test_lowercase_extension_still_found(tmp_path):
    """Must-not-fire control: the ordinary case this function already handled must
    keep working once the match is folded."""
    (tmp_path / "rules.md" ).write_text("# rules\n", encoding="utf-8")

    files, unreadable = doctor._rglob_md(tmp_path)

    assert not unreadable
    names = sorted(p.name for p in files)
    assert "rules.md" in names, names


def test_mixed_case_extension_is_found(tmp_path):
    (tmp_path / "Notes.Md").write_text("# notes\n", encoding="utf-8")

    files, unreadable = doctor._rglob_md(tmp_path)

    names = sorted(p.name for p in files)
    assert "Notes.Md" in names, names


def test_a_non_markdown_extension_is_still_excluded():
    """Must-not-fire control on the other axis: folding case must not widen the
    match to files that are not markdown at all -- ".mdx" must stay excluded, the
    same as it was before this fix."""
    assert not "readme.mdx".lower().endswith(".md")


def test_both_cases_are_found_together(tmp_path):
    """Every file present is reported, not just the first case encountered."""
    (tmp_path / "one.md").write_text("a\n", encoding="utf-8")
    (tmp_path / "TWO.MD").write_text("b\n", encoding="utf-8")

    files, unreadable = doctor._rglob_md(tmp_path)

    assert not unreadable
    names = sorted(p.name for p in files)
    assert names == ["TWO.MD", "one.md"] or names == ["one.md", "TWO.MD"], names
    assert len(files) == 2, names
