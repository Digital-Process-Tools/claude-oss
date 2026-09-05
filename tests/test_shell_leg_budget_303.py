"""The shell leg's budget: what is inside the timed window, and what happens without shellcheck.

The `shell` job carried `timeout-minutes: 10` and opened its last step with
`sudo apt-get update -qq && sudo apt-get install -y shellcheck`. Measured on job
96152482222 (run 32276977038, `main` at 7ea64c9) the job ran 10.32 minutes and was killed;
GitHub renders a `timeout-minutes` kill as **cancelled**, not failure, so `main` and every
open pull request read as "0 failed, 1 cancelled -- not green" with nothing broken (#303).

Two measurements decided the fix rather than the cap:

* In the killed job the step produced **no output at all** between its `##[endgroup]` at
  16:57:21.155 and `##[error]The operation was canceled.` at 17:07:33.918. `apt-get install`
  is not quiet, so it was never reached: the whole 10.2 minutes was `apt-get update`.
* In the two successful jobs read for comparison the install logged
  `shellcheck is already the newest version (0.9.0-1)`. The fetch has never installed
  anything -- `shellcheck` ships in the `ubuntu-latest` image. `apt-get update` took 68.4s
  of a 70s step in one and 5.2s in the other; the linting itself took under a second in both.

So the fetch was removed rather than pinned or given a bigger cap. A pinned tarball would be
a different network round trip bought for a binary already on the runner.

What this file holds:

* the fetch is gone from the shell job, with the job as it stood at 7ea64c9 as the positive
  control -- a `not in` that has stopped matching passes against every workflow there is;
* the step's *executed behaviour* when `shellcheck` is absent: a named refusal with its own
  exit code, not 127 once per file and not a green leg;
* the two invariants the step's shape carries and that a rewrite is most likely to lose --
  every file is linted rather than stopping at the first failure, and the loop reads the
  list by redirection so a first failure does not hide the rest.

The assertions run the `run:` body taken from the **parsed** workflow. A regex over a
workflow is the shape that keeps passing while the workflow is broken.

Python 3.9 compatible.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

#: The exit code the step uses to say `shellcheck was not there`. Distinct from
#: shellcheck's own 1 (it found something), from shell_sources.py's 2 (matched nothing)
#: and 3 (could not read), so a reader of a red leg knows which of the four happened.
NO_SHELLCHECK_EXIT = 4

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this one.

    Locally pyyaml may be absent and the rest of this file skips with a reason. On a
    runner it is installed by the workflow, so its absence is a broken leg rather than a
    contributor's laptop, and reporting `1 skipped` there is this repository's own defect
    class: a check that could not look, rendered as a check that looked.
    """
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the shell-leg assertions in this "
            "file did not run on a runner. The pytest job installs it; if that line "
            "changed, this file went quiet rather than red."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _shell_job():
    job = _workflow()["jobs"]["shell"]
    assert job, "the `shell` job is empty, so everything below asserts nothing"
    return job


def _step(job, name):
    for step in job["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(
        "no step named {!r} in the shell job; steps are {!r}".format(
            name, [s.get("name") or s.get("uses") for s in job["steps"]]
        )
    )


# ------------------------------------------------------------------ positive control

#: The `shell` job exactly as it stood at 7ea64c9, the commit #303 was measured on. Kept
#: verbatim so the `not in` below is proven able to see the defect it is written against.
THE_JOB_AS_IT_WAS_AT_7EA64C9 = """jobs:
  shell:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - name: Enumerate shell sources
        run: |
          python3 scripts/shell_sources.py --root . > shell-sources.txt
          echo "linting:"; cat shell-sources.txt
      - name: Syntax-check every shell source
        run: |
          while IFS= read -r f; do bash -n "$f" || exit 1; done < shell-sources.txt
      - name: shellcheck
        run: |
          sudo apt-get update -qq && sudo apt-get install -y shellcheck
          fail=0
          while IFS= read -r f; do shellcheck -S warning "$f" || fail=1; done < shell-sources.txt
          exit "$fail"
"""

#: Anything that reaches a package mirror or a release host from inside the job. Not a
#: list of forbidden words: each of these is a network round trip whose latency would be
#: charged to `timeout-minutes`, which is the whole of #303.
FETCHERS = (
    "apt-get",
    "apt ",
    "aptitude",
    "yum ",
    "dnf ",
    "brew install",
    "choco install",
    "curl ",
    "wget ",
    "pip install",
    "npm install",
)


def _fetches(text):
    return sorted({f.strip() for f in FETCHERS if f in text})


def _job_run_text(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


@needs_yaml
def test_the_control_job_contains_the_fetch_this_file_rejects():
    """Without this, the assertion below passes against a job that fetches by some other
    spelling, or against a read that returned nothing."""
    found = _fetches(THE_JOB_AS_IT_WAS_AT_7EA64C9)
    assert "apt-get" in found, (
        "the detector cannot see the fetch in the job as it stood at 7ea64c9 -- it "
        "found {!r}. Fix the detector, not the assertion.".format(found)
    )


@needs_yaml
def test_the_shell_job_fetches_nothing_inside_its_timed_window():
    job = _shell_job()
    found = _fetches(_job_run_text(job))
    assert not found, (
        "the shell job reaches the network from inside `timeout-minutes`: {}. That is "
        "#303 -- `apt-get update` took 5.2s, then 68.4s, then hung for 612s and got the "
        "job killed, and GitHub renders that as `cancelled` rather than `failure`. "
        "shellcheck ships in the ubuntu-latest image; the install never installed "
        "it.".format(", ".join(found))
    )


@needs_yaml
def test_the_job_still_carries_a_wall_clock_cap():
    """Removing the fetch is not a licence to remove the bound on a hang."""
    job = _shell_job()
    cap = job.get("timeout-minutes")
    assert isinstance(cap, int) and cap > 0, (
        "the shell job has no usable timeout-minutes ({!r}); a hung step would then run "
        "to the runner's own six-hour limit".format(cap)
    )


# --------------------------------------------------------- what the step actually does


def _bash():
    found = shutil.which("bash")
    if not found:
        pytest.skip(
            "no bash on PATH on {}, so the shell step's own body went unexecuted "
            "here; the leg it comes from is ubuntu-only".format(sys.platform)
        )
    return found


def _stub(directory, name, body):
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _resolves(env, name):
    """What `command -v NAME` answers under this exact env, asked of the step's own shell.

    The fixture is measured rather than assumed. `PATH` below is built to hold one
    directory and nothing else; asking the shell whether that worked is the difference
    between a test that establishes its condition and one that hopes it did.
    """
    done = subprocess.run(
        [_bash(), "-c", "command -v " + name],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return done.stdout.decode("utf-8", "replace").strip()


def _run_step(tmp_path, body, files, stub_shellcheck=None):
    """Run the workflow step's own `run:` body under `bash -e`, as the runner does.

    PATH is replaced with the stub directory **alone**. Naming `/usr/bin` and `/bin`
    beside it is what the first version of this file did, and it is wrong on exactly the
    platform that matters: `shellcheck` ships in the ubuntu-latest image at
    `/usr/bin/shellcheck`, which is the image the `shell` job runs on and one of the
    pytest matrix legs -- so the `stub_shellcheck=None` case would have found the real
    linter, linted a trivially clean fixture, exited 0, and never constructed the absence
    it asserts about. Nothing in the step body needs a system PATH: `command -v`, `echo`,
    `read` and `exit` are bash builtins, and each stub names its interpreter by absolute
    path in its own shebang.
    """
    work = tmp_path / "work"
    work.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name, text in files.items():
        (work / name).write_text(text, encoding="utf-8")
    (work / "shell-sources.txt").write_text(
        "".join(name + "\n" for name in sorted(files)), encoding="utf-8"
    )
    env = dict(os.environ)
    env["PATH"] = str(binaries)

    if stub_shellcheck is None:
        # Measured, not assumed. If some route still reaches a real shellcheck then this
        # test did not test what it says, and saying so is the only honest outcome.
        leaked = _resolves(env, "shellcheck")
        if leaked:
            pytest.skip(
                "shellcheck still resolves to {!r} with PATH={!r}, so the `absent` case "
                "could not be constructed here and the step's refusal went "
                "untested".format(leaked, env["PATH"])
            )
    else:
        _stub(binaries, "shellcheck", stub_shellcheck)
        # The same measurement the other way round: a stub this platform's shell does not
        # consider executable -- a live question for an extensionless file under the Git
        # Bash on the Windows legs -- would make every assertion below a statement about
        # the harness rather than about the step.
        placed = _resolves(env, "shellcheck")
        if not placed:
            pytest.skip(
                "the shellcheck stub written to {} is not seen as executable by this "
                "platform's shell, so the step body went unexecuted here. The job this "
                "body comes from is `runs-on: ubuntu-latest` only.".format(binaries)
            )

    return subprocess.run(
        [_bash(), "-e", "-c", body],
        cwd=str(work),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


ONE_FILE = {"a.sh": "#!/bin/sh\ntrue\n"}
TWO_FILES = {"a.sh": "#!/bin/sh\ntrue\n", "b.sh": "#!/bin/sh\ntrue\n"}

#: Records every argument it was handed, then reports whatever the fixture asked for.
STUB_OK = '#!/bin/sh\nfor a in "$@"; do echo "$a" >> "$PWD/seen"; done\nexit 0\n'
STUB_FAILS_ON_B = (
    "#!/bin/sh\n"
    'for a in "$@"; do echo "$a" >> "$PWD/seen"; done\n'
    'case "$*" in *b.sh*) exit 1 ;; esac\n'
    "exit 0\n"
)


def _linted(tmp_path):
    """The paths the stub was actually handed, without the flags around them."""
    seen = (tmp_path / "work" / "seen").read_text(encoding="utf-8").split()
    return sorted(os.path.basename(p) for p in seen if p.endswith(".sh"))


@needs_yaml
def test_the_step_is_green_when_every_file_is_clean(tmp_path):
    """Positive control for the two refusals below: this body can exit 0 at all."""
    body = _step(_shell_job(), "shellcheck")["run"]
    done = _run_step(tmp_path, body, TWO_FILES, STUB_OK)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert _linted(tmp_path) == ["a.sh", "b.sh"], _linted(tmp_path)


@needs_yaml
def test_the_step_refuses_by_name_when_shellcheck_is_absent(tmp_path):
    """`could not lint` must not render as `linted and found nothing`.

    With no stub on PATH the body as it stood at 7ea64c9 ran `shellcheck` once per file,
    collected 127 into the same `fail` flag a real finding uses, and reported it as a
    lint failure -- indistinguishable, in the leg's status, from the linter working.
    """
    body = _step(_shell_job(), "shellcheck")["run"]
    done = _run_step(tmp_path, body, ONE_FILE, stub_shellcheck=None)
    assert done.returncode == NO_SHELLCHECK_EXIT, (
        "with shellcheck absent the step exited {} -- expected {}, the code that means "
        "`the linter was not there`. stdout={!r} stderr={!r}".format(
            done.returncode, NO_SHELLCHECK_EXIT, done.stdout, done.stderr
        )
    )
    assert b"shellcheck" in done.stderr.lower(), (
        "the refusal does not name what was missing: {!r}".format(done.stderr)
    )


@needs_yaml
def test_every_file_is_linted_even_after_one_fails(tmp_path):
    """The `fail=1` flag, not `|| exit 1`: a first failure must not hide the rest."""
    body = _step(_shell_job(), "shellcheck")["run"]
    done = _run_step(tmp_path, body, TWO_FILES, STUB_FAILS_ON_B)
    assert done.returncode == 1, "a failing file did not fail the step: {} {!r}".format(
        done.returncode, done.stderr
    )
    assert _linted(tmp_path) == ["a.sh", "b.sh"], (
        "the step stopped early: it linted {!r}, so a file after the first failure is "
        "never read and the leg reports on a partial list".format(_linted(tmp_path))
    )
