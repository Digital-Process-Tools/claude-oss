"""#398. Which interpreter the shell entry point picks, and why that is a choice.

`scripts/doctor.sh` used to walk `python3.14 python3.13 ... python3.9 python3 python`,
newest first, with bare `python3` seventh. That ordering encodes *newest is best* and
consults neither of the two facts that matter here:

* **CI gates 3.9-3.12.** The first candidate tried was therefore the one no leg covers.
* **A `python3.N` on PATH is no evidence it is the good build.** On the machine #398 was
  filed from the only 3.14 was an x86_64 build under Rosetta in `/usr/local`, while the
  native arm64 interpreter answers to bare `python3` in `/opt/homebrew` -- so preferring
  the explicit minor is exactly what selected the translated one, and the documented
  shell invocation disagreed with the documented direct one on the same tree.

The enumeration itself is not the defect and these tests are written so that deleting it
fails them. `test_a_present_but_broken_python3_falls_through` is the paired control: the
candidate the new order prefers is present, resolves, and does not run -- the Windows App
Execution Alias shape the enumeration exists for -- and the launcher must still reach a
working one. An ordering-only test would pass against a rewrite that trusted `command -v`
and stopped trying candidates; that one would not.

Python 3.9 compatible.
"""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import shell_probe  # noqa: E402

LAUNCHER = REPO_ROOT / "scripts" / "doctor.sh"
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"

_ATTEMPTS = shell_probe.attempts([LAUNCHER, DOCTOR])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

_LAUNCHER_TEXT = LAUNCHER.read_text(encoding="utf-8")

# Read out of the launcher rather than copied, so a change to the sentinel makes these
# tests fail loudly instead of quietly measuring a string nothing uses any more.
_SENTINEL_MATCH = re.search(r'^SENTINEL="([^"]+)"', _LAUNCHER_TEXT, re.MULTILINE)
assert _SENTINEL_MATCH, (
    "doctor.sh no longer defines SENTINEL in the shape this test reads"
)
SENTINEL = _SENTINEL_MATCH.group(1)


def _stub(bindir, name, works=True):
    """An interpreter that answers the probe and then names itself.

    `$1` is `-c` during the probe and the path of doctor.py afterwards, so one script
    covers both halves and the second half is what tells us which candidate won.
    """
    path = bindir / name
    if works:
        body = (
            "#!/bin/sh\n"
            'if [ "$1" = "-c" ]; then printf %s "' + SENTINEL + '"; exit 0; fi\n'
            'printf "SELECTED ' + name + '\\n"\n'
            'printf "VERDICT: stub\\n"\n'
        )
    else:
        # Resolves, runs, produces nothing useful: the App Execution Alias shape.
        body = "#!/bin/sh\nexit 9\n"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _selected(tmp_path, present):
    """Run the launcher against a PATH holding exactly `present` and say who won.

    VIRTUAL_ENV is blanked rather than inherited: an active venv short-circuits
    find_python before the candidate loop is reached, and the whole fixture would then
    measure the developer's shell instead of the launcher.
    """
    if BASH is None:
        pytest.skip(SHELL_REPORT)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, works in present.items():
        _stub(bindir, name, works=works)
    environment = dict(os.environ)
    environment.update({"PATH": str(bindir), "VIRTUAL_ENV": ""})
    done = subprocess.run(
        [BASH, str(LAUNCHER)],
        cwd=str(tmp_path),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert done.returncode == 0, done.stdout
    chosen = [
        line.split(None, 1)[1]
        for line in done.stdout.splitlines()
        if line.startswith("SELECTED ")
    ]
    return (chosen[0] if chosen else None), done.stdout


def test_bare_python3_is_preferred_over_a_newer_explicit_minor(tmp_path):
    """The measured defect. All three run; the environment's own default must win.

    This is what makes `bash scripts/doctor.sh` and `python3 scripts/doctor.py` agree,
    which is the property the issue is about -- PATH order already encodes which build
    of a given version this machine wants, and an explicit minor throws that away.
    """
    chosen, out = _selected(
        tmp_path, {"python3": True, "python3.13": True, "python3.14": True}
    )
    assert chosen == "python3", out


def test_a_ci_covered_minor_beats_a_newer_one(tmp_path):
    """With no bare `python3`, the fallback order must prefer the band CI gates.

    3.9-3.12 is what the 12 pytest legs actually run. An interpreter outside it is a
    fallback, not a default: first-tried and never-tested is the combination #398 names.
    """
    chosen, out = _selected(tmp_path, {"python3.12": True, "python3.14": True})
    assert chosen == "python3.12", out


def test_the_oldest_supported_minor_still_beats_a_newer_one(tmp_path):
    """The band is preferred as a whole, not merely 3.12. Guards against a reorder that
    moved one name and left the rest of the walk newest-first."""
    chosen, out = _selected(tmp_path, {"python3.9": True, "python3.13": True})
    assert chosen == "python3.9", out


def test_a_newer_interpreter_is_still_found_when_it_is_the_only_one(tmp_path):
    """The cost of preferring the band, stated as a test rather than as a comment: a
    machine whose only interpreter is newer than 3.12 still runs the diagnostic. The
    preference reorders candidates; it never removes them."""
    chosen, out = _selected(tmp_path, {"python3.14": True})
    assert chosen == "python3.14", out


def test_a_present_but_broken_python3_falls_through(tmp_path):
    """The control, and the reason the enumeration exists.

    `python3` resolves and fails -- Windows' App Execution Alias, reasoned not observed
    here. Each candidate is proved by RUNNING it, so the launcher must walk past the
    preferred name to a working one. A rewrite that trusted `command -v` and stopped
    would pass every ordering test above and fail this.
    """
    chosen, out = _selected(tmp_path, {"python3": False, "python3.12": True})
    assert chosen == "python3.12", out
    assert "VERDICT: could not run" not in out


def test_every_candidate_is_still_tried_when_none_works(tmp_path):
    """The negative half of the control: all present, none working, and the launcher
    says it could not run rather than implying the repo is fine."""
    chosen, out = _selected(
        tmp_path,
        {"python3": False, "python3.12": False, "python3.14": False, "python": False},
    )
    assert chosen is None
    assert "VERDICT: could not run" in out


def test_the_failure_message_names_the_order_actually_walked():
    """A receipt that lists a walk the code no longer performs is this repo's own defect
    class in miniature: a confident sentence about something nobody did."""
    # find_python holds TWO `for candidate` loops: the venv one, whose names are paths
    # in an environment variable and cannot be listed in a receipt, and the PATH walk
    # this receipt is about. Selecting on the text rather than on position, because
    # "the first one" is a fact about today's layout.
    loops = [
        body
        for body in re.findall(
            r"^\s*for candidate in ([^;]+); do", _LAUNCHER_TEXT, re.MULTILINE
        )
        if "VIRTUAL_ENV" not in body
    ]
    assert len(loops) == 1, loops
    candidates = loops[0].split()
    failure = [
        line
        for line in _LAUNCHER_TEXT.splitlines()
        if "no working Python found" in line
    ]
    assert len(failure) == 1, failure
    for name in candidates:
        assert name in failure[0], (
            "{} is tried but the FAIL line does not name it".format(name)
        )
