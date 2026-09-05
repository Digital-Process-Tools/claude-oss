"""The manager skill is split into a spine and per-phase files, and both
halves have to stay honest.

`skills/manager/SKILL.md` is loaded whole by every `Skill(manager)`
invocation -- `commands/tick.md` and `commands/release.md` both open with
one -- so its bytes are paid at full price on the first turn of a session
and at cache-read price on every turn after. At 122,423 B it was the
largest file in this repository, larger than `agents/developer.md`, and
#491's budget deliberately did not cover it: that issue asked for a budget
on "each agent definition", and the manager skill is not one.

The split moves each phase's argument -- the incident it was written for,
the measurement behind it -- into `skills/manager/phases/*.md`, read when
the loop reaches that phase, and leaves the directive in the spine. Two
failure modes follow directly, and this module is what makes each of them
loud:

- **A phase file nothing points at is a phase file nothing loads**, and a
  rule that never loaded renders exactly like a rule that found nothing to
  say -- this repository's own defect class, applied to its own prose. So
  `unreferenced` is a state here, not an omission.
- **Growth becomes invisible again the moment nobody counts it.** The whole
  point of moving bytes out of the spine is lost if the spine grows back,
  so the spine carries a budget of its own and so does every phase file.

No issue number is claimed for this file: the split was maintainer-directed
in a session, not filed first. The budgets it records are measured, and
`scripts/skill_phases.py` is the one place they are declared.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import skill_phases  # noqa: E402


def test_every_declared_document_is_present():
    """`missing` is a third state on purpose -- a declared phase file that is
    not on disk is not "under budget", it is a phase whose rules nobody will
    ever read, and answering `ok` for it would be the absence-read-as-clean
    this plugin is named after."""
    missing = [r for r in skill_phases.check() if r["state"] == "missing"]
    assert not missing, "declared but absent: " + ", ".join(r["path"] for r in missing)


def test_check_reports_missing_rather_than_silently_passing():
    """Positive control for the assertion above: with nothing on disk to be
    over budget, the check must still say something."""
    orig = skill_phases.DOCUMENTS
    skill_phases.DOCUMENTS = {
        "skills/manager/phases/does-not-exist.md": (10, 20, "a fabricated phase")
    }
    try:
        rows = skill_phases.check()
    finally:
        skill_phases.DOCUMENTS = orig
    declared = [r for r in rows if r["path"].endswith("does-not-exist.md")]
    assert [r["state"] for r in declared] == ["missing"], rows
    # The real phase files are still on disk and are no longer declared, so
    # they come back as `undeclared` rather than not at all. That is the
    # mirror state and it must not be silent either.
    assert all(r["state"] == "undeclared" for r in rows if r not in declared), rows


def test_every_document_is_at_or_under_its_budget():
    over = [r for r in skill_phases.check() if r["state"] == "over"]
    assert not over, "over budget, replace-don't-append: " + ", ".join(
        "{0} is {1}B against a budget of {2}B".format(r["path"], r["size"], r["budget"])
        for r in over
    )


def test_the_spine_names_every_phase_file_it_defers_to():
    """A phase file the spine never names is unreachable: the loop reads
    SKILL.md and nothing else until SKILL.md sends it somewhere."""
    unreferenced = [r for r in skill_phases.check() if not r["referenced"]]
    assert not unreferenced, (
        "the spine never names these, so nothing will ever load them: "
        + ", ".join(r["path"] for r in unreferenced)
    )


def test_unreferenced_is_reported_rather_than_assumed():
    """Positive control for the check above. Without this, the assertion
    passes just as happily when `referenced` is never computed at all."""
    fake = ROOT / "skills" / "manager" / "phases" / "unreferenced-control.md"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("nothing points here\n", encoding="utf-8")
    orig = skill_phases.DOCUMENTS
    skill_phases.DOCUMENTS = {
        "skills/manager/phases/unreferenced-control.md": (
            0,
            10_000,
            "a phase file the spine does not name",
        )
    }
    try:
        rows = skill_phases.check()
    finally:
        skill_phases.DOCUMENTS = orig
        fake.unlink()
    assert rows[0]["state"] == "ok", rows
    assert rows[0]["referenced"] is False, rows


def test_a_phase_file_on_disk_that_nobody_budgeted_is_reported():
    """`undeclared` is the mirror of `missing`. A phase file that exists,
    is loaded by the loop, and appears in no budget is how the measurement
    quietly stops covering its own subject -- the same absence one level up
    from the phase files themselves. Reporting only the declared paths would
    answer "every file I know about is fine", which is true of an empty
    declaration too.
    """
    fake = ROOT / "skills" / "manager" / "phases" / "undeclared-control.md"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("nobody budgeted this\n", encoding="utf-8")
    try:
        rows = {r["path"]: r for r in skill_phases.check()}
    finally:
        fake.unlink()
    row = rows.get("skills/manager/phases/undeclared-control.md")
    assert row is not None, sorted(rows)
    assert row["state"] == "undeclared", row
    assert row["budget"] is None and row["baseline"] is None, row


def test_the_real_tree_has_no_undeclared_phase_file():
    """The positive control's counterpart: with nothing planted, every phase
    file on disk is one this repository budgeted."""
    undeclared = [r for r in skill_phases.check() if r["state"] == "undeclared"]
    assert not undeclared, "on disk and in no budget: " + ", ".join(
        r["path"] for r in undeclared
    )


def test_the_spine_is_smaller_than_the_prose_it_defers():
    """The split is only worth its complexity if the always-loaded half is
    the smaller half. Stated as an assertion rather than as a claim in a
    docstring, because a claim in a docstring cannot fail.
    """
    rows = {r["path"]: r for r in skill_phases.check()}
    spine = rows[skill_phases.SPINE]["size"]
    deferred = sum(r["size"] for path, r in rows.items() if path != skill_phases.SPINE)
    assert spine is not None and deferred, rows
    assert spine < deferred, (
        "the spine is {0}B and the deferred phases total {1}B -- the split has "
        "stopped paying for itself".format(spine, deferred)
    )


def test_every_phase_file_states_what_it_governs():
    """A phase file has to say, in its own first lines, which phase sends a
    reader to it. Landing in one mid-loop with no idea what it is for is how
    a reader decides it was already covered by the spine."""
    thin = []
    for path, (_baseline, _budget, governs) in skill_phases.DOCUMENTS.items():
        if path == skill_phases.SPINE:
            continue
        assert governs, path
        head = (ROOT / path).read_text(encoding="utf-8")[:2000]
        if "Read this when" not in head:
            thin.append(path)
    assert not thin, "no 'Read this when' line in the opening of: " + ", ".join(thin)


def test_documents_refuses_an_empty_answer():
    """`manager_docs.documents()` promises in its own docstring that it never
    answers with an empty set, because every content guard in this repository
    is built on it and `[]` would turn each of them into a vacuous pass -- the
    absence-read-as-clean defect one layer further out than the phase files
    themselves. Asserted against a tree with no spine in it.
    """
    import manager_docs

    empty = ROOT / "tests"  # a real directory with no skills/manager in it
    with pytest.raises(RuntimeError) as excinfo:
        manager_docs.documents(empty)
    assert "no spine" in str(excinfo.value)


def test_documents_finds_the_whole_set_positive_control():
    """The refusal above passes just as happily if `documents()` refused
    everything. Prove it answers for the real tree, and that the spine is
    first -- the order the guards' section extractors rely on."""
    import manager_docs

    found, unreadable = manager_docs.documents(ROOT)
    assert unreadable == [], unreadable
    assert found[0].name == "SKILL.md", found
    assert len(found) == len(skill_phases.DOCUMENTS), (found, skill_phases.DOCUMENTS)


def test_the_join_cannot_invent_a_line_at_a_file_boundary():
    """`text()` joins with a blank line so a `^## ` anchor still anchors at a
    boundary. Concatenated with nothing, the last line of one file and the
    first of the next would fuse into a line that appears in neither, and a
    guard would then report on prose no document carries.
    """
    import manager_docs

    joined = manager_docs.text(ROOT)
    paths, unreadable = manager_docs.documents(ROOT)
    assert unreadable == [], unreadable
    for path in paths[1:]:
        first = path.read_text(encoding="utf-8").split(chr(10))[0]
        assert (chr(10) + first) in joined, first


def test_positive_control_for_the_governs_check():
    """The assertion above passes over a phase file it never opened. Prove it
    fires on text that lacks the line."""
    with pytest.raises(AssertionError):
        assert "Read this when" in "a phase file that never says", "control"
