"""An uncommitted delete of a tracked workflow is not a workflow that could not be
read -- and it must not abort probe generation for the whole repository (#396).

`git ls-files` answers about the **index**; `_workflow_jobs` reads the **working
tree**. Between an `rm` and its commit the two disagree about exactly those paths.
Until this split every such path was filed as *could not read*, and those problems
feed `gather()`'s unconditional refusal -- so one mid-delete workflow produced no
probe at all for the whole repository, with a sentence that was false about the file.

`#396` was reopened for the consumer question, and these tests are what pin the
answer:

* **absent -> proceed.** A file that is not in the working tree declares no jobs.
  That is a measurement and not a gap, so `gather()`'s "a probe is returned only
  when every field in it was measured" contract is satisfied rather than relaxed,
  and the probe is returned. The absence is loud rather than swallowed: it comes
  back on `gather()`'s third return value and `--probe` prints it as a NOTE.
* **unreadable -> refuse.** A file that is on disk and whose bytes did not come back
  has an unknown number of jobs, and counting it as zero understates the required
  checks -- the direction `_workflow_jobs` documents as the one that lets a red leg
  through. That is a genuine gap, so the refusal stands exactly as it was.

Three states, not the five `_version_state` grew in #408, and the difference is
argued rather than inherited: this is a line scan, not a parser, so it has no
`malformed` to report. It cannot tell "declares no jobs" from "declares jobs in a
shape the scan did not match", and a state the code cannot support is a claim
rather than a fact.

Every "must not fire" below is paired with a "must fire" in the same fixture. The
unreadable arm is built two ways on purpose: a directory where the file goes, which
raises `OSError` -- never `FileNotFoundError` -- on every platform and therefore
never skips, and a real `chmod 000`, which is *measured* by attempting the exact
read the code performs and skips naming what went untested when it did not take.
"""

import json
import os
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
WORKFLOW_B = "name: b\non: push\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"


def _git_repo(root, files):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run([GIT, "-C", str(root), "add", "-A"], check=True)


def _fake_gh(root, args):
    """The same seam `tests/test_oss_config.py` uses: gh is replaced, git is real."""
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


def _two_workflows(root):
    _git_repo(
        root,
        {
            "README.md": "# thing\n",
            ".github/workflows/a.yml": WORKFLOW_A,
            ".github/workflows/b.yml": WORKFLOW_B,
        },
    )


def _workflows_dir(root):
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "a.yml").write_text(WORKFLOW_A, encoding="utf-8")
    return directory


# ------------------------------------------------- the enumeration, on its own


def test_a_workflow_in_the_list_and_not_on_disk_is_absent_rather_than_unreadable(tmp_path):
    """The bucket split. Absence is decided from the exception already in hand --
    no `exists()` follow-up, which swallows a different set of errnos on different
    interpreter versions and is what broke the release gate in #76.
    """
    _workflows_dir(tmp_path)
    files = [".github/workflows/a.yml", ".github/workflows/gone.yml", "README.md"]

    jobs, problems, absent = oss_config._workflow_jobs(tmp_path, files)

    assert absent == [".github/workflows/gone.yml"]
    assert problems == []
    # Must fire in the same fixture: the workflow that IS on disk was still read,
    # so an empty `problems` here is not an enumeration that scanned nothing.
    assert jobs == ["a.yml:unit"]


def test_a_workflow_that_is_there_and_will_not_read_is_still_a_problem(tmp_path):
    """The control the absent arm needs, on every platform.

    A directory where the file goes raises `OSError` -- `IsADirectoryError` on
    POSIX, `PermissionError` on Windows -- and never `FileNotFoundError`, so this
    arm needs no privilege, no mode bit, and never skips.
    """
    directory = _workflows_dir(tmp_path)
    (directory / "broken.yml").mkdir()
    files = [".github/workflows/a.yml", ".github/workflows/broken.yml"]

    jobs, problems, absent = oss_config._workflow_jobs(tmp_path, files)

    assert absent == []
    assert len(problems) == 1, problems
    assert ".github/workflows/broken.yml" in problems[0]
    assert "could not read" in problems[0]
    # Must fire: the readable sibling still produced its job.
    assert jobs == ["a.yml:unit"]


def test_a_chmod_denied_workflow_is_a_problem_and_the_deny_is_measured(tmp_path):
    """The same claim against a real mode bit rather than a type substitution.

    A permission fixture is a measurement, not a given: root ignores the mode bit,
    some filesystems ignore it, and Windows' `os.chmod` toggles a read-only
    attribute that does not stop a read. So the deny is confirmed by attempting the
    exact operation the code under test performs, and this skips naming what went
    untested when it did not take. The directory-substitution test above covers the
    same claim on every platform and never skips, so no leg is left with nothing
    asserted about `unreadable`.
    """
    directory = _workflows_dir(tmp_path)
    denied = directory / "denied.yml"
    denied.write_text(WORKFLOW_B, encoding="utf-8")
    files = [".github/workflows/a.yml", ".github/workflows/denied.yml"]

    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "chmod 000 on {} raised {} (errno {}), so the denied-read arm could not "
            "be set up and went untested".format(denied, type(exc).__name__, exc.errno)
        )
    try:
        try:
            denied.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            pytest.skip(
                "the denied file answered {} (errno {}) rather than a permission "
                "error, so it would be classified `absent` and this arm measures "
                "nothing about `unreadable`".format(type(exc).__name__, exc.errno)
            )
        except OSError:
            pass
        else:
            pytest.skip(
                "chmod 000 on {} still allows reading it -- running as root, or a "
                "filesystem/platform that does not enforce the mode bit. The chmod "
                "half of the unreadable arm went untested; the "
                "directory-substitution test covers the same claim and never "
                "skips.".format(denied)
            )

        jobs, problems, absent = oss_config._workflow_jobs(tmp_path, files)

        assert absent == []
        assert len(problems) == 1, problems
        assert ".github/workflows/denied.yml" in problems[0]
        # Must fire: the readable sibling still produced its job.
        assert jobs == ["a.yml:unit"]
    finally:
        os.chmod(str(denied), 0o644)


def test_a_workflow_set_entirely_on_disk_reports_neither_bucket(tmp_path):
    """The ordinary repo. Both third states empty, and a non-empty `jobs` proving
    the enumeration ran -- two empty lists alone also come back from a scan that
    matched no paths at all.
    """
    directory = _workflows_dir(tmp_path)
    (directory / "b.yml").write_text(WORKFLOW_B, encoding="utf-8")
    files = [".github/workflows/a.yml", ".github/workflows/b.yml"]

    jobs, problems, absent = oss_config._workflow_jobs(tmp_path, files)

    assert (problems, absent) == ([], [])
    assert jobs == ["a.yml:unit", "b.yml:lint"]


# ------------------------------------------------- the consumer: gather()


@needs_git
def test_gather_proceeds_when_a_tracked_workflow_is_deleted_from_the_working_tree(
    tmp_path, monkeypatch
):
    """The whole of #396's reopened row. An ordinary uncommitted delete used to
    abort probe generation for the entire repository; it now costs one NOTE.

    `files` still lists the deleted path, because `files` is the index -- which is
    exactly why the absence has to be said out loud somewhere rather than left as a
    silently shorter `workflow_jobs`.
    """
    _two_workflows(tmp_path)
    (tmp_path / ".github" / "workflows" / "b.yml").unlink()
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)

    probe, problems, notes = oss_config.gather(tmp_path)

    assert problems == []
    assert probe is not None
    assert probe["workflow_jobs"] == ["a.yml:unit"]
    assert ".github/workflows/b.yml" in probe["files"]
    assert oss_config.probe_problems(probe) == []
    assert any(".github/workflows/b.yml" in note for note in notes), notes
    assert any("not on disk" in note for note in notes), notes


@needs_git
def test_gather_still_refuses_when_a_tracked_workflow_is_there_and_will_not_read(
    tmp_path, monkeypatch
):
    """The must-fire half, in the same shape of fixture as the test above: the
    refusal is not weakened, it is narrowed to the case that earns it.
    """
    _two_workflows(tmp_path)
    broken = tmp_path / ".github" / "workflows" / "b.yml"
    broken.unlink()
    broken.mkdir()
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)

    probe, problems, notes = oss_config.gather(tmp_path)

    assert probe is None
    assert notes == []
    assert any(
        "could not read" in problem and ".github/workflows/b.yml" in problem
        for problem in problems
    ), problems


# ------------------------------------------------- the receipt a human reads


@needs_git
def test_the_probe_command_writes_the_probe_and_names_the_absent_workflow(
    tmp_path, monkeypatch, capsys
):
    """The documented invocation is `--probe . | --build`, so the NOTE goes to
    stderr beside the probe rather than into it. A reader who did not read the code
    has to be able to tell a repo with one workflow from a repo mid-delete.
    """
    _two_workflows(tmp_path)
    (tmp_path / ".github" / "workflows" / "b.yml").unlink()
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)

    assert oss_config._main(["--probe", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "FAIL" not in captured.err, captured.err
    assert "NOTE" in captured.err, captured.err
    assert ".github/workflows/b.yml" in captured.err, captured.err
    assert json.loads(captured.out)["workflow_jobs"] == ["a.yml:unit"]


@needs_git
def test_the_probe_command_still_fails_loudly_on_a_workflow_that_will_not_read(
    tmp_path, monkeypatch, capsys
):
    """Must fire, same command, same fixture shape. Without this, the test above
    also passes against a `--probe` that had stopped refusing anything at all.
    """
    _two_workflows(tmp_path)
    broken = tmp_path / ".github" / "workflows" / "b.yml"
    broken.unlink()
    broken.mkdir()
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)

    assert oss_config._main(["--probe", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "FAIL" in captured.err, captured.err
    assert ".github/workflows/b.yml" in captured.err, captured.err
    assert captured.out == ""
