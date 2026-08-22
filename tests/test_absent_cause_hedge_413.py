"""Two receipts narrated an uncommitted delete as the *cause* of a bare
`FileNotFoundError`, and CI has measured that Windows returns the identical
exception -- errno 2, no distinguishing winerror -- for a path it could not even
look up (`CLAUDE.md`, the `_read_config`/`lane_setup` measurements; #380). The
bucket ('absent') is correct and not in question; the sentence claiming *why* is
not something the signal can support (#413).

Two sites, one shared hedge, both asserted here so a fix touching only one of them
still fails: `gather()`'s `notes.append()` for `absent_workflows`, and the
`version_evidence` sentence for the `absent` state in `_report_probe_notes`.

Each is paired with its own positive control -- a genuinely unreadable file, whose
receipt must keep naming the read failure specifically -- so a fix that makes every
sentence vague, absent or not, still fails here.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(
    GIT is None, reason="git is not on PATH, so there is no repo to probe"
)

WORKFLOW_A = "name: a\non: push\njobs:\n  unit:\n    runs-on: ubuntu-latest\n"

# The bare claim #413 is about -- must not appear standing alone, unhedged.
BARE_CAUSE_CLAIM = "This is what an uncommitted delete looks like"


def _git_repo(root, files):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run([GIT, "-C", str(root), "add", "-A"], check=True)


def _fake_gh(root, args):
    if args[0] == "repo":
        return (
            True,
            {
                "nameWithOwner": "owner/name",
                "defaultBranchRef": {"name": "main"},
                "squashMergeAllowed": True,
                "mergeCommitAllowed": False,
                "rebaseMergeAllowed": False,
            },
            "",
        )
    if args[0] == "label":
        return True, [{"name": "priority/high"}], ""
    return True, [{"title": "v1.0"}], ""


@needs_git
def test_the_absent_workflow_note_offers_the_delete_as_likely_not_as_fact(
    tmp_path, monkeypatch
):
    """`gather()`'s NOTE for `absent_workflows`. Paired in the same fixture with a
    workflow that is on disk and will not read -- a directory substitution, which
    never skips -- so a fix that vagues out both sentences still fails on the
    control.
    """
    directory = tmp_path / ".github" / "workflows"
    _git_repo(
        tmp_path,
        {
            "README.md": "# thing\n",
            ".github/workflows/a.yml": WORKFLOW_A,
            ".github/workflows/gone.yml": WORKFLOW_A,
            ".github/workflows/broken.yml": WORKFLOW_A,
        },
    )
    # Broken and deleted after the commit, and never re-staged: `git ls-files`
    # answers about the index, not the working tree, so both paths stay listed.
    (directory / "gone.yml").unlink()
    (directory / "broken.yml").unlink()
    (directory / "broken.yml").mkdir()
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)

    probe, problems, notes = oss_config.gather(tmp_path)

    absent_notes = [n for n in notes if "gone.yml" in n]
    assert absent_notes, notes
    note = absent_notes[0]
    assert BARE_CAUSE_CLAIM not in note, (
        "the absent NOTE still asserts an uncommitted delete as the fact rather "
        "than the likely cause -- exactly what Windows' folded FileNotFoundError "
        "cannot support: {!r}".format(note)
    )
    assert "not on disk" in note, note
    assert "usual" in note.lower(), (
        "the note should hedge the cause rather than dropping it, or the fix is "
        "indistinguishable from deleting information: {!r}".format(note)
    )

    # The control: a workflow that IS there and will not read is a different bucket
    # and must still say so specifically, not with the same hedge.
    broken_problems = [p for p in problems if "broken.yml" in p]
    assert broken_problems, problems
    assert "could not read" in broken_problems[0], broken_problems[0]


def test_the_version_evidence_absent_note_offers_the_delete_as_likely_not_as_fact(
    capsys,
):
    """The sibling site: the `version_evidence` sentence `_report_probe_notes`
    prints for the `absent` state, shipped by #408. Same claim, same signal, and
    #413 is the class of both rather than a fix to one.

    Paired with the existing unreadable control in the same probe: it must keep
    naming a real read failure, not adopt the same hedge.
    """
    probe = {
        "labels": [],
        "version_evidence": {
            "CHANGELOG.md": "absent",
            "package.json": "unreadable",
        },
    }
    oss_config._report_probe_notes(probe, {})
    printed = capsys.readouterr().err

    absent_line = [line for line in printed.splitlines() if "CHANGELOG.md" in line]
    assert absent_line, printed
    assert BARE_CAUSE_CLAIM not in absent_line[0], (
        "the version_evidence NOTE for `absent` still asserts the cause rather "
        "than hedging it: {!r}".format(absent_line[0])
    )
    assert "usual" in absent_line[0].lower(), absent_line[0]

    unreadable_line = [line for line in printed.splitlines() if "package.json" in line]
    assert unreadable_line, printed
    assert "could not read" in unreadable_line[0], (
        "the control: the unreadable sentence must keep naming a real read "
        "failure, or the fix made every sentence vague: {!r}".format(unreadable_line[0])
    )
