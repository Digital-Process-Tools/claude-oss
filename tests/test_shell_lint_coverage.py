"""Which files the shell leg actually reads, and whether it says so when it reads none.

The shellcheck leg was green for every release and had never opened
`bin/oss-workspace`. Both of its guards scoped themselves with `git ls-files '*.sh'`,
which returns exactly one path in this repository -- `scripts/doctor.sh` -- while the
plugin's own entry point is tracked, is POSIX `sh`, and carries no extension. A lint
that ran and found nothing and a lint that never saw the file exit 0 identically, and
the step is named as though it covers the repository's shell (#193).

Two properties are held here, and they are not the same property:

* **Coverage.** Every tracked shell source reaches the leg. Asserted against a shebang
  scan written here, deliberately as a second implementation rather than a call into
  `shell_sources`, so agreement is evidence and not a tautology.
* **Loudness.** Matching nothing is a failure and not a silent success. Without that
  half the repair reintroduces its own bug the first time somebody narrows the
  selection: `shellcheck` with no arguments exits 0.

Every coverage assertion below is paired with a positive control, because a scan that
found nothing would satisfy "every shell source is covered" perfectly.

Deliberately not a YAML parse: the assertion is about what a maintainer reads in the
file -- the same call `tests/test_workflow_permissions.py` makes.

Python 3.9 compatible.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import shell_sources  # noqa: E402

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

#: The instance #193 was filed about. Named on purpose: a general scan proves the rule,
#: and this proves the case, so a selection that drifts back to extensions fails with
#: the filename in the message rather than with a set difference.
THE_EXTENSIONLESS_LAUNCHER = "bin/oss-workspace"

#: Interpreter basenames whose files shellcheck can read. Spelled out here rather than
#: imported so this scan is independent of the one under test.
SHELLS = {"sh", "bash", "dash", "ksh", "ash", "zsh"}


def _tracked():
    done = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode != 0:
        pytest.skip("git ls-files failed here: {!r}".format(done.stderr[-200:]))
    return [name for name in done.stdout.decode("utf-8").split("\0") if name]


def _looks_like_shell(path):
    """First line only, bytes-first so a binary blob cannot raise a decode error."""
    try:
        with open(str(path), "rb") as handle:
            head = handle.read(256)
    except OSError:
        return False
    if not head.startswith(b"#!"):
        return False
    first = head.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    words = [word for word in first[2:].replace("\t", " ").split(" ") if word]
    if not words:
        return False
    name = os.path.basename(words[0])
    if name == "env":
        rest = [word for word in words[1:] if not word.startswith("-")]
        name = os.path.basename(rest[0]) if rest else ""
    return name in SHELLS


def _scanned_shell_sources():
    found = []
    for name in _tracked():
        path = REPO_ROOT / name
        if name.endswith((".sh", ".bash", ".ksh", ".dash")) or _looks_like_shell(path):
            found.append(name)
    return sorted(found)


SCANNED = _scanned_shell_sources()


# ------------------------------------------------------------------ positive controls


def test_the_scan_found_shell_to_check():
    """Without this, every coverage assertion below passes having read nothing."""
    assert len(SCANNED) >= 2, (
        "the shebang scan found {!r} -- fewer than the two shell sources this "
        "repository is known to track, so the coverage checks below are "
        "vacuous".format(SCANNED)
    )


def test_the_scan_sees_both_shapes():
    """One with an extension, one without. A scan that saw only `.sh` would agree with
    the very glob this file exists to reject."""
    assert "scripts/doctor.sh" in SCANNED
    assert THE_EXTENSIONLESS_LAUNCHER in SCANNED, (
        "the scan in this test file cannot see {} -- fix the scan, not the "
        "assertion".format(THE_EXTENSIONLESS_LAUNCHER)
    )


# ------------------------------------------------------------------------- coverage


def test_the_enumerator_selects_the_extensionless_launcher():
    selected = shell_sources.shell_sources(REPO_ROOT)
    assert THE_EXTENSIONLESS_LAUNCHER in selected, (
        "{} is tracked, is POSIX sh and has no extension, and the shell leg still "
        "cannot see it. That is #193 exactly: shellcheck exits 0 whether it read the "
        "file or never received it. Selected: {!r}".format(
            THE_EXTENSIONLESS_LAUNCHER, selected
        )
    )


def test_the_enumerator_covers_every_tracked_shell_source():
    selected = set(shell_sources.shell_sources(REPO_ROOT))
    missed = [name for name in SCANNED if name not in selected]
    assert not missed, (
        "these tracked files carry a shell shebang or a shell extension and are not "
        "selected for linting: {}".format(", ".join(missed))
    )


# -------------------------------------------------------------------------- loudness


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "shell_sources.py")] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
    )


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["git", "init", "-q", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {!r}".format(done.stderr[-200:]))
    return path


def test_a_repo_with_shell_exits_zero_and_names_the_files():
    """The control for the two refusals below: same command, real repository."""
    done = _run(["--root", str(REPO_ROOT)])
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    printed = done.stdout.decode("utf-8").split()
    assert THE_EXTENSIONLESS_LAUNCHER in printed


def test_matching_nothing_is_a_failure_and_not_an_empty_success(tmp_path):
    """The half of the repair that is easy to leave out.

    A selection that matches nothing today runs `shellcheck` with no arguments, which
    exits 0. `matched and clean` and `matched nothing` have to be different exit codes
    or the fix reintroduces the bug it repairs.
    """
    repo = _git_repo(tmp_path / "empty")
    (repo / "notes.md").write_text("no shell here\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "notes.md"], check=True)

    done = _run(["--root", str(repo)])
    assert done.returncode == 2, (
        "a repository with a tracked file and no shell source exited {} -- an empty "
        "match has to be loud".format(done.returncode)
    )
    message = done.stderr.decode("utf-8", "replace")
    assert "no tracked shell source" in message, message
    assert not done.stdout.strip(), "printed a file list while reporting an empty match"


def test_a_tracked_file_it_cannot_read_is_reported_rather_than_skipped(tmp_path):
    """The third state. A file whose first line could not be read is not a file that
    has no shebang, and answering `not shell` for it would hide a script from the leg
    with the leg still green."""
    repo = _git_repo(tmp_path / "gone")
    (repo / "runme").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (repo / "keep.sh").write_text("#!/bin/sh\necho keep\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "runme", "keep.sh"], check=True)
    (repo / "runme").unlink()

    done = _run(["--root", str(repo)])
    message = done.stderr.decode("utf-8", "replace")
    assert done.returncode == 3, (
        "a tracked file that could not be read exited {} -- silently answering `not "
        "shell` is the absence this plugin is named after, and `could not look` is a "
        "different exit code from `looked, found nothing` on purpose. stderr: "
        "{}".format(done.returncode, message)
    )
    assert "could not be read" in message, message
    assert "runme" in message, message


# ------------------------------------------------------------------- the workflow


def _shell_job_lines(text):
    """The `shell:` job's lines, from its key to the next job at the same indent.

    Takes the text rather than reading the file, so the checks below can be pointed at
    a fixture that is known to be wrong and watched fire.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.rstrip() == "  shell:":
            start = index
            break
    assert start is not None, "no `shell:` job in {}".format(WORKFLOW)
    body = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("    "):
            break
        body.append(line)
    return body


def _shell_job():
    return _shell_job_lines(WORKFLOW.read_text(encoding="utf-8"))


def _extension_selectors(text):
    """Lines of the `shell:` job that pick files by extension, comments excluded.

    Comment lines are dropped, and that is not a loophole: the workflow's own comments
    quote the glob to record why it was removed, and a check that could not tell a
    quoted defect from an executed one would forbid documenting the fix.
    """
    code = [line for line in _shell_job_lines(text) if not line.strip().startswith("#")]
    return [line.strip() for line in code if "*.sh" in line]


#: The `shell:` job exactly as it stood at ce26035, the parent of the commit that fixed
#: #193. The positive control for the two `not in` checks below: they are substring
#: tests, and a substring test that has silently stopped matching -- a renamed job key,
#: an indent change, a `_shell_job_lines` that returns nothing -- passes against any
#: workflow at all, including this one.
THE_JOB_AS_IT_WAS = """jobs:
  shell:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Syntax-check every script
        run: |
          for f in $(git ls-files '*.sh'); do bash -n "$f"; done
      - name: shellcheck
        run: |
          shellcheck -S warning $(git ls-files '*.sh')

  other:
    runs-on: ubuntu-latest
"""


def test_the_shell_job_exists_and_has_a_body():
    """Positive control for the two assertions below, both of which are `not in`."""
    body = _shell_job()
    assert body, "the `shell:` job is empty, so the checks below assert nothing"
    assert any("shellcheck" in line for line in body)
    assert any("bash -n" in line for line in body)


def test_the_shell_job_does_not_select_its_files_by_extension():
    """The defect, stated as the thing that must not be in the file.

    `git ls-files '*.sh'` cannot return an extensionless script, so scoping the guards
    that way is not a narrow selection -- it is a selection that structurally cannot see
    the file most worth reading.
    """
    control = _extension_selectors(THE_JOB_AS_IT_WAS)
    assert len(control) == 2, (
        "the check cannot see the defect it is looking for: pointed at the job as it "
        "stood at ce26035 it found {!r} instead of both `git ls-files '*.sh'` lines. "
        "A `not in` that has stopped matching passes against every workflow there "
        "is.".format(control)
    )

    offenders = _extension_selectors(WORKFLOW.read_text(encoding="utf-8"))
    assert not offenders, (
        "the shell job still selects files by extension: {}. `bin/oss-workspace` is "
        "tracked POSIX sh with no extension and is invisible to that glob, which is "
        "why the leg was green having linted one file of two (#193).".format(offenders)
    )


def test_the_shell_job_derives_its_file_list_from_the_enumerator():
    control = _shell_job_lines(THE_JOB_AS_IT_WAS)
    assert control and not any("shell_sources.py" in line for line in control), (
        "the control job, which predates the enumerator, reads as using it -- so this "
        "check cannot distinguish a job that derives its list from one that does not"
    )

    body = _shell_job()
    assert any("shell_sources.py" in line for line in body), (
        "the shell job does not run scripts/shell_sources.py. Naming each script in "
        "this workflow instead would put a fact about this repository in a file that "
        "nothing re-derives, and it goes stale on the next extensionless script."
    )


# ------------------------------------------------------ what a first line is read as

#: (first bytes, interpreter basename or None, is it something shellcheck can read).
#: The `csh` row and the `/opt/shiny/python` row are the two worth having: both are one
#: substring match away from being selected, and shellcheck refuses csh outright -- so
#: selecting one would fail the leg on a file it cannot analyse, which is a red build
#: for a reason nobody chose.
SHEBANGS = [
    (b"#!/bin/sh\n", "sh", True),
    # CRLF, which is not hypothetical: a Windows leg checks this repository out with
    # core.autocrlf on, so every shebang the enumerator reads there ends `\r\n`. Left
    # unstripped the interpreter reads as "sh\r", matches nothing, and bin/oss-workspace
    # drops out of the leg on exactly the platform the launcher has been burned on.
    (b"#!/bin/sh\r\n", "sh", True),
    (b"#! /bin/dash\n", "dash", True),
    (b"#!/usr/bin/env bash\n", "bash", True),
    (b"#!/usr/bin/env -S bash -e\n", "bash", True),
    (b"#!/bin/bash -eu\nset -e\n", "bash", True),
    (b"#!/usr/bin/python3\n", "python3", False),
    (b"#!/usr/bin/env python3\n", "python3", False),
    (b"#!/bin/csh\n", "csh", False),
    (b"#!/opt/shiny/python\n", "python", False),
    (b"#!/usr/bin/env\n", None, False),
    (b"#!\n", None, False),
    (b"import os\n", None, False),
    (b"", None, False),
    (b"\x7fELF\x02\x01\x01\x00\x00", None, False),
]


@pytest.mark.parametrize("head,expected,is_shell", SHEBANGS, ids=range(len(SHEBANGS)))
def test_the_first_line_is_read_as_an_interpreter_name(head, expected, is_shell):
    name = shell_sources._shebang_interpreter(head)
    assert name == expected, "{!r} read as {!r}".format(head, name)
    assert (name in shell_sources.SHELL_INTERPRETERS) is is_shell


def test_both_verdicts_are_present_in_the_table():
    """Positive control. A table of only-shell rows would pass a parser that answered
    `shell` unconditionally, and a table of only-other rows one that answered `no`."""
    verdicts = {row[2] for row in SHEBANGS}
    assert verdicts == {True, False}
