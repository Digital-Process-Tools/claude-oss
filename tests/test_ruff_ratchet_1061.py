"""#1061: `scripts/ruff_ratchet.py` gates on a set diff, not a bare count.

The original gate compared `len(findings) > BASELINE`. A pull request that
fixes one pre-existing finding while introducing a different, unrelated one
leaves the count unchanged and the leg stays green -- exactly the case a
ratchet exists to catch. This is the regression test for that exact shape:
one baseline finding removed, one new (different) finding introduced, same
total count, and the gate must still fail.

Every "must fire" case here is paired with a "must not fire" one in the same
shape, so a harness that always fails is not indistinguishable from one that
actually diffs.
"""

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RATCHET = REPO_ROOT / "scripts" / "ruff_ratchet.py"

pytestmark = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not on PATH")

_PYPROJECT = textwrap.dedent(
    """\
    [tool.ruff]
    target-version = "py39"

    [tool.ruff.lint]
    select = ["F401", "F841", "E722", "B006", "A001"]
    """
)


def _run(root, baseline_file, extra_args=()):
    return subprocess.run(
        [
            sys.executable,
            str(RATCHET),
            "--root",
            str(root),
            "--baseline-file",
            str(baseline_file),
        ]
        + list(extra_args),
        capture_output=True,
        text=True,
    )


def _tree(tmp_path, files):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    for rel, body in files.items():
        (tmp_path / rel).write_text(body)
    return tmp_path


def test_a_fix_and_an_unrelated_new_finding_leave_the_count_flat_but_still_fail(
    tmp_path,
):
    # Two files, two pre-existing findings, captured as the baseline.
    before = _tree(
        tmp_path,
        {
            "a.py": "import os\n\n\ndef f():\n    return 1\n",
            "b.py": "def g():\n    return 2\n",
        },
    )
    baseline = tmp_path / "baseline.txt"
    r_write = _run(before, baseline, extra_args=["--write-baseline"])
    assert r_write.returncode == 0, r_write.stdout + r_write.stderr
    assert baseline.read_text(encoding="utf-8").count("\n") == 1, (
        "positive control: the captured baseline must have exactly the one "
        "finding a.py's own unused import produces, or this fixture is not "
        "testing what it claims to"
    )

    # a.py's finding is fixed; b.py gains a different, unrelated one. Same
    # total count as before (1), different composition.
    (before / "a.py").write_text("def f():\n    return 1\n")
    (before / "b.py").write_text("import sys\n\n\ndef g():\n    return 2\n")

    r = _run(before, baseline)
    assert r.returncode == 1, (
        "a fix that swaps places with a different, unrelated new finding "
        "must still fail the gate even though the total count did not "
        "change -- got:\n" + r.stdout + r.stderr
    )
    assert "b.py" in r.stdout
    assert "F401" in r.stdout


def test_a_pure_fix_with_nothing_new_passes(tmp_path):
    """Positive control for the case above: fixing the baseline finding with
    nothing new introduced anywhere must pass."""
    before = _tree(
        tmp_path,
        {
            "a.py": "import os\n\n\ndef f():\n    return 1\n",
            "b.py": "def g():\n    return 2\n",
        },
    )
    baseline = tmp_path / "baseline.txt"
    r_write = _run(before, baseline, extra_args=["--write-baseline"])
    assert r_write.returncode == 0, r_write.stdout + r_write.stderr

    (before / "a.py").write_text("def f():\n    return 1\n")

    r = _run(before, baseline)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


_ONE_BARE_EXCEPT = "def f():\n    try:\n        pass\n    except:\n        pass\n"
_TWO_BARE_EXCEPTS = (
    "def f():\n    try:\n        pass\n    except:\n        pass\n\n\n"
    "def g():\n    try:\n        pass\n    except:\n        pass\n"
)


def test_a_second_occurrence_of_an_already_known_message_is_still_new(tmp_path):
    """A `Counter`, not a bare `set`: two genuinely identical findings (same
    file, same rule, same message -- ruff's own E722 text is a constant, "Do
    not use bare `except`") must not let the second occurrence hide behind
    the first's baseline entry."""
    before = _tree(tmp_path, {"a.py": _ONE_BARE_EXCEPT})
    baseline = tmp_path / "baseline.txt"
    r_write = _run(before, baseline, extra_args=["--write-baseline"])
    assert r_write.returncode == 0, r_write.stdout + r_write.stderr
    assert baseline.read_text(encoding="utf-8").count("\n") == 1, (
        "positive control: the captured baseline must have exactly the one "
        "bare-except finding, or this fixture is not testing what it claims"
    )

    (before / "a.py").write_text(_TWO_BARE_EXCEPTS)

    r = _run(before, baseline)
    assert r.returncode == 1, (
        "a second, identical-message finding in the same file must still "
        "be reported as new against a baseline that only ever saw one -- "
        "got:\n" + r.stdout + r.stderr
    )


def test_the_same_single_bare_except_against_its_own_baseline_passes(tmp_path):
    """Positive control: the one-occurrence tree, checked against its own
    freshly written baseline, must pass."""
    before = _tree(tmp_path, {"a.py": _ONE_BARE_EXCEPT})
    baseline = tmp_path / "baseline.txt"
    r_write = _run(before, baseline, extra_args=["--write-baseline"])
    assert r_write.returncode == 0, r_write.stdout + r_write.stderr

    r = _run(before, baseline)
    assert r.returncode == 0, r.stdout + r.stderr
