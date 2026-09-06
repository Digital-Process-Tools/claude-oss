"""#1177 step 2: every pytest leg reports what `pytest -n auto` would ask it for.

#1177's candidate 1 is pytest-xdist (`-n auto --dist loadfile`) and it names its own
precondition: the runners' core counts have not been read, so the expected 2-3x is
reasoned rather than observed. `scripts/doctor.py`'s `xdist_auto_workers` (#367) is a
transcription of xdist's own worker-count logic, so the number is reportable rather than
guessed -- but nothing was reporting it anywhere a CI reader could see.

The probe is `doctor.py --worker-sizing`: the interpreter-environment check alone, on
every leg of the matrix, so the three operating systems and four interpreters answer for
themselves instead of being read off a documentation page that has changed before. It
runs unconditionally and exits 0 like every other doctor mode, so it can never fail a leg.

The reading it produces is a prerequisite for a change, not a change. Nothing here
asserts that xdist is used, installed or desirable.

Python 3.9 compatible.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"

#: The exact argument the workflow step passes. Both the step and this file's own
#: subprocess run go through this name, so a rename that missed one is red here.
FLAG = "--worker-sizing"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this one."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the workflow assertions in this "
            "file did not run on a runner. The pytest job installs it; if that line "
            "changed, this file went quiet rather than red."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _pytest_job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["pytest"]
    assert job.get("steps"), (
        "the `pytest` job has no steps, so everything below asserts nothing"
    )
    return job


def _step_running(job, needle):
    for step in job["steps"]:
        if needle in (step.get("run") or ""):
            return step
    raise AssertionError(
        "no step in the pytest job runs {!r}; steps are {!r}".format(
            needle, [s.get("name") or s.get("uses") for s in job["steps"]]
        )
    )


# ------------------------------------------------------------------ the flag itself


def test_the_flag_selects_the_probe_and_its_absence_does_not():
    """Positive and negative in one pair: a mode flag that is always on is not a mode."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import doctor

    parsed = doctor.parse_args([FLAG])
    assert parsed[4] is True, "{} did not select the probe: {!r}".format(FLAG, parsed)
    assert doctor.parse_args([])[4] is False, "the probe ran with no flag asking for it"


def test_the_probe_runs_here_and_says_what_n_auto_would_ask_for():
    """The step's own executed behaviour, not the fact that a step exists.

    A workflow step naming a flag `doctor.py` does not have prints a usage line, is
    reported as an argument problem, and still exits 0 -- twelve green legs carrying no
    reading at all. So this runs the real command and reads the real stdout.
    """
    proc = subprocess.run(
        [sys.executable, str(DOCTOR), FLAG],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    assert proc.returncode == 0, "doctor must exit 0 in every mode; stderr: {}".format(
        proc.stderr
    )
    assert "worker sizing:" in proc.stdout, (
        "the probe produced no worker-sizing line, so a leg running it reads as a leg "
        "that reported nothing. stdout: {!r}".format(proc.stdout)
    )
    verdicts = [ln for ln in proc.stdout.splitlines() if ln.startswith("VERDICT:")]
    assert len(verdicts) == 1, "one VERDICT line is the contract; got {!r}".format(
        verdicts
    )
    assert "argument:" not in proc.stdout, (
        "the flag was not recognised and the run fell through to a normal diagnosis: "
        "{!r}".format(proc.stdout)
    )


# ------------------------------------------------------------------ the workflow


@needs_yaml
def test_every_leg_of_the_matrix_runs_the_probe():
    job = _pytest_job()
    step = _step_running(job, "doctor.py {}".format(FLAG))
    assert "if" not in step, (
        "the probe step is conditional ({!r}), so the legs it skips report nothing and "
        "the reading covers fewer platforms than the matrix does".format(step.get("if"))
    )
    matrix = job["strategy"]["matrix"]
    assert len(matrix["os"]) * len(matrix["python-version"]) >= 12, (
        "the matrix no longer has the 12 legs this reading is taken across: {!r}".format(
            matrix
        )
    )


@needs_yaml
def test_the_conditional_check_can_see_a_conditional_step():
    """Positive control for the `if not in step` assertion above.

    An absence assertion also passes when the parser hands back steps with no keys at
    all. The Windows Defender exclusion step is conditional on purpose, so it is the
    proof that a conditional step is visible here.
    """
    conditional = [s for s in _pytest_job()["steps"] if "if" in s]
    assert conditional, (
        "no step in the pytest job carries an `if:`, so the assertion that the probe "
        "step carries none is vacuous"
    )
