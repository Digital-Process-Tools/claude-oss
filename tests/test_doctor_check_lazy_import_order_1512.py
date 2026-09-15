"""#1512: six `doctor_check_*` modules (plus `script_call_survey.py`, which
`doctor_check_script_call_survey.py` imports lazily) used to carry `import
doctor` at MODULE scope. `doctor.py` imports each of them back at ITS OWN
module scope (`from doctor_check_X import ...`), so importing the submodule
directly -- before `doctor.py` has finished executing -- used to re-enter
`doctor.py`, which then tried to pull names out of the submodule while it was
still mid-load and raised `ImportError: cannot import name ... from partially
initialized module ...`.

Every existing test in this suite imports `doctor` first (see the `# noqa:
E402` convention across the file), which masks the bug -- by the time
`doctor` finishes loading, every `doctor_check_*` submodule it needs is
already fully initialized. Reproducing the real failure needs a FRESH
interpreter that imports the submodule FIRST, which is why this uses
`subprocess` rather than an in-process `import` -- `sys.modules` caching in
this same test process would otherwise hide the exact defect being pinned
(the same reason `tests/test_settings_git_allowlist_982.py`'s own comment on
this class gives for importing `doctor` first there instead).

Convention match: `doctor_check_scheduler_processes.py` (#1350) is the
existing sibling that already does this correctly -- `import doctor` moved
inside the function that needs it, never at module scope.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import spawn_guard

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

#: Every module #1512 (and its own follow-up comment) named as re-entering
#: this same circular-import trap.
MODULES = [
    "doctor_check_event_filter",
    "doctor_check_script_call_survey",
    "script_call_survey",
    "doctor_check_mcp_channel_connection",
    "doctor_check_mcp_channel_registration",
    "doctor_check_channel_health_agreement",
    # #1519: landed after #1512 with the identical shape (module-scope
    # `import doctor`), caught only by manually reproducing this test's own
    # standalone-import technique against it, not by this list.
    "doctor_check_action_pins",
]


def _import_standalone(module_name):
    """Runs a fresh interpreter that imports ONLY `module_name` first --
    never `doctor` -- and reports whether that import itself raised."""
    return spawn_guard.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, {!r}); import {}".format(
                str(SCRIPTS_DIR), module_name
            ),
        ],
        subject="whether {} raises a circular ImportError when imported "
        "before doctor.py (#1512)".format(module_name),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )


@pytest.mark.parametrize("module_name", MODULES)
def test_importing_the_submodule_before_doctor_does_not_raise(module_name):
    """Must-fire half: before the fix, each of these raised `ImportError:
    ... partially initialized module ...` the moment it was imported before
    `doctor.py` finished loading -- exactly the shape #1512 reported for
    `doctor_check_event_filter`, `doctor_check_script_call_survey` and
    `script_call_survey`, and the shape the issue's own follow-up comment
    named for the three channel modules too."""
    completed = _import_standalone(module_name)
    assert completed.returncode == 0, completed.stdout.decode("utf-8", "replace")
    assert b"circular import" not in completed.stdout
    assert b"partially initialized" not in completed.stdout


def test_importing_doctor_first_still_works_positive_control():
    """Positive control for the test above: the ordinary order (`doctor`
    first, the way `doctor.py`'s own `main()` and every existing test in this
    suite already does it) has to keep working, so a harness that could not
    see ANY import failure would not pass this suite silently."""
    completed = spawn_guard.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, {!r}); import doctor; "
            "import doctor_check_event_filter; "
            "import doctor_check_mcp_channel_connection".format(str(SCRIPTS_DIR)),
        ],
        subject="whether importing doctor first still works (positive control)",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout.decode("utf-8", "replace")
