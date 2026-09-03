"""#939: `agents/developer.md` is re-sent on every turn of every developer lane,
and measured on one live tick it was 84-96% of what each lane read. The three
late phases -- self-review, review returns, the report -- now live in
`agents/developer/*.md`, read when a lane reaches them.

What this file holds, on the same terms `tests/test_skill_phase_split.py`
holds for the manager's split:

- every declared phase file is on disk and under its budget, and a phase file
  on disk that nothing declares is reported rather than passed over;
- the spine names every phase file -- an unnamed one is unreachable;
- the phase files carry no frontmatter, so Claude Code's recursive scan of
  `agents/` treats them as documentation rather than registering three more
  agents;
- `developer_docs.DeveloperBrief` reads the whole set, and refuses to narrow
  it silently when the phases directory cannot be listed;
- the spine actually shrank: the split is measured against the number it was
  argued from, not assumed.

Not asserted: whether a lane opens the files. The spine asks for an unread one
to be named under `compliance`; that is the half only the lane can report.
"""

import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_budgets  # noqa: E402
import developer_docs  # noqa: E402
import developer_phases  # noqa: E402

SPINE = ROOT / "agents" / "developer.md"
PHASES_DIR = ROOT / "agents" / "developer"


def test_every_declared_phase_file_is_ok_and_referenced():
    rows = {r["path"]: r for r in developer_phases.check()}
    for rel in developer_phases.DOCUMENTS:
        row = rows[rel]
        assert row["state"] == "ok", "{}: {} ({}B against {}B)".format(
            rel, row["state"], row["size"], row["budget"]
        )
        assert row["referenced"] is True, (
            "{} is not named by agents/developer.md -- a phase file the spine "
            "never names is one no lane can reach".format(rel)
        )


def test_no_phase_file_on_disk_is_undeclared():
    undeclared = [r for r in developer_phases.check() if r["state"] == "undeclared"]
    assert not undeclared, "phase file(s) with no budget: " + ", ".join(
        r["path"] for r in undeclared
    )


def test_check_reports_over_when_a_budget_is_crossed():
    # Positive control: the check must fire, not merely refrain from firing.
    orig = developer_phases.DOCUMENTS
    developer_phases.DOCUMENTS = {"agents/developer/report.md": (1, 2, "control")}
    try:
        rows = {r["path"]: r for r in developer_phases.check()}
    finally:
        developer_phases.DOCUMENTS = orig
    assert rows["agents/developer/report.md"]["state"] == "over"


def test_check_reports_missing_rather_than_ok():
    orig = developer_phases.DOCUMENTS
    developer_phases.DOCUMENTS = {"agents/developer/does-not-exist-939.md": (1, 2, "control")}
    try:
        rows = {r["path"]: r for r in developer_phases.check()}
    finally:
        developer_phases.DOCUMENTS = orig
    row = rows["agents/developer/does-not-exist-939.md"]
    assert row["state"] == "missing"
    assert row["referenced"] is False


def test_check_reports_an_undeclared_file_on_disk():
    # Positive control for the undeclared arm: drop one declared file from the
    # dict and it must come back as `undeclared`, not vanish.
    orig = developer_phases.DOCUMENTS
    developer_phases.DOCUMENTS = {
        k: v for k, v in orig.items() if k != "agents/developer/review.md"
    }
    try:
        rows = {r["path"]: r for r in developer_phases.check()}
    finally:
        developer_phases.DOCUMENTS = orig
    assert rows["agents/developer/review.md"]["state"] == "undeclared"


def test_phase_files_carry_no_frontmatter_so_they_are_not_agents():
    # Claude Code scans a plugin's agents/ recursively; a file opening with a
    # frontmatter block carrying `name:` would register as a fourth, fifth and
    # sixth agent. Documentation is what a file with no frontmatter is read as.
    for rel in developer_phases.DOCUMENTS:
        first = (ROOT / rel).read_text(encoding="utf-8").lstrip().splitlines()[0]
        assert not first.startswith("---"), "{} opens with a frontmatter fence".format(rel)
        assert first.startswith("# "), "{} should open with its title".format(rel)


def test_spine_is_still_the_only_budgeted_agent_definition_at_that_path():
    # The spine's budget lives in agent_budgets, not here -- one number per file.
    assert developer_phases.SPINE in agent_budgets.BUDGETS
    assert developer_phases.SPINE not in developer_phases.DOCUMENTS


def test_spine_shrank_below_the_size_it_was_argued_from():
    # 89,714 B measured 2026-09-03 before the split; a spine back at that size
    # would mean the phase files were duplicated rather than moved.
    size = len(SPINE.read_bytes())
    assert size < 60000, "agents/developer.md is {}B -- the split did not take".format(size)


def test_developer_brief_reads_the_whole_set():
    brief = developer_docs.DeveloperBrief()
    paths = brief.paths
    assert paths[0] == SPINE
    assert {p.relative_to(ROOT).as_posix() for p in paths[1:]} == set(developer_phases.DOCUMENTS)
    text = brief.read_text()
    # One phrase from each phase file, so a narrowed read fails on the file it dropped.
    assert "tree_snapshot.py" in text
    assert "review_return.py" in text
    assert "report_schema.py" in text
    assert brief.is_file()


def test_documents_raises_on_a_missing_spine(tmp_path):
    with pytest.raises(RuntimeError):
        developer_docs.documents(tmp_path)


def test_documents_reports_an_unreadable_phases_directory(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "developer.md").write_text("spine\n", encoding="utf-8")
    phases = tmp_path / "agents" / "developer"
    phases.mkdir()
    (phases / "x.md").write_text("x\n", encoding="utf-8")
    # Control first: readable, one phase file listed.
    paths, unreadable = developer_docs.documents(tmp_path)
    assert [p.name for p in paths] == ["developer.md", "x.md"] and unreadable == []
    phases.chmod(0)
    try:
        try:
            list(phases.iterdir())
        except PermissionError:
            pass
        else:
            pytest.skip("this platform or user lists a mode-0 directory; the deny could not be established")
        paths, unreadable = developer_docs.documents(tmp_path)
        assert [p.name for p in paths] == ["developer.md"]
        assert unreadable, "a denied phases directory must be reported, not read as empty"
        with pytest.raises(RuntimeError):
            developer_docs.text(tmp_path)
    finally:
        phases.chmod(stat.S_IRWXU)


# --- CLAUDE.md's developer phase table, held against developer_phases.DOCUMENTS ---
# The same comparison tests/test_claude_md_phase_budget_table_725.py makes for the
# manager table, one section over: two hand-copied numbers and nothing comparing them
# is how the agent table's own baseline column went stale by 6,700 B unnoticed.

import re  # noqa: E402

CLAUDE_MD = ROOT / "CLAUDE.md"
SECTION_HEADING = "## The developer brief is a spine plus three phase files"
ROW = re.compile(
    r"^\| `(agents/developer/[\w./-]+\.md)` \| ([\d,]+) B \| ([\d,]+) B \|\s*$",
    re.MULTILINE,
)


def _table_rows():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    section_start = text.index(SECTION_HEADING)
    start = text.index("| file | measured (baseline) | budget |", section_start)
    end = text.index("\n\n", start)
    return [
        (path, int(b.replace(",", "")), int(g.replace(",", "")))
        for path, b, g in ROW.findall(text[start:end])
    ]


def test_claude_md_developer_phase_table_matches_developer_phases():
    rows = _table_rows()
    assert rows, "no rows under the developer phase table header"
    table = {path: (baseline, budget) for path, baseline, budget in rows}
    module = {
        path: (baseline, budget)
        for path, (baseline, budget, _governs) in developer_phases.DOCUMENTS.items()
    }
    assert table == module, "CLAUDE.md table {} != developer_phases.DOCUMENTS {}".format(table, module)


def test_claude_md_agent_table_carries_the_spine_new_number():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    baseline, budget = agent_budgets.BUDGETS["agents/developer.md"]
    row = "| `agents/developer.md` | {:,} B | {:,} B |".format(baseline, budget)
    assert row in text, "CLAUDE.md's agent table does not carry {!r}".format(row)
