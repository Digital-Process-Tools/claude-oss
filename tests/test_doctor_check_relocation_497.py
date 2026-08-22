"""#497: five ``check_*`` functions move out of ``scripts/doctor.py`` into their own
modules, `doctor.py` keeps `main()`, the check registry and the shared contract.

This is a pure move, so what needs proving is not new behaviour -- the existing
per-check test files already exercise it, unchanged, from `doctor.check_X`, which is
exactly the attribute this file confirms is still a live re-export rather than a
second copy. What this file adds is the ONE new failure mode the move itself creates
and nothing else exercises: `doctor.py` runs as a script (`python3 scripts/doctor.py`)
as well as being imported as `doctor`, and the moved modules do `import doctor` to
reach shared names. When `doctor.py` is `__main__`, nothing named "doctor" is in
`sys.modules` unless `doctor.py` puts it there itself -- and without that alias each
moved module would import a SECOND, freshly-executed copy of `doctor.py` under
`sys.modules["doctor"]`, with its own separate `FINDINGS` list, silently dropping
every finding a moved check reports from the VERDICT the running `__main__` copy
tallies. That is exactly this repository's own defect class: an absence produced by
the tool, rendered identically to a clean run.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import doctor  # noqa: E402

MOVED = {
    "doctor_check_auto_update": ["check_auto_update"],
    "doctor_check_statusline": ["_POSIX_VAR_RE", "_statusline_windows_gap", "check_statusline"],
    "doctor_check_fragments_readme": [
        "COMPATIBILITY_BULLET",
        "_fragments_directory",
        "check_fragments_readme",
    ],
    "doctor_check_memory": [
        "MEMORY_DIR",
        "MEMORY_CONFIG_DIR",
        "memory_layout",
        "_display",
        "_listdir",
        "_identity_names",
        "check_memory",
    ],
    "doctor_check_merge_permission": [
        "MERGE_OP",
        "MERGE_RULE_FILE",
        "settings_candidates",
        "_permission_entries",
        "_entry_count",
        "merge_permission_state",
        "check_merge_permission",
    ],
}


def test_every_moved_name_is_one_object_not_two_copies():
    """``doctor.<name>`` and ``<module>.<name>`` must be the identical object.

    Not merely equal -- ``is``, the same object. CLAUDE.md's own rule is that a
    helper used from more than one place lives in exactly one place; a re-export
    that copied the value instead of aliasing it would satisfy every other test
    here and still be the two-copies-that-drift shape the rule exists to forbid.
    """
    import importlib

    for module_name, names in MOVED.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert hasattr(doctor, name), (
                "doctor.{} is missing -- the move must re-export it".format(name)
            )
            assert hasattr(module, name), (
                "{}.{} is missing -- the definition itself moved away".format(
                    module_name, name
                )
            )
            assert getattr(doctor, name) is getattr(module, name), (
                "doctor.{0} and {1}.{0} are two different objects -- this is the "
                "two-copies-that-drift shape, not a re-export".format(name, module_name)
            )


def test_moved_modules_are_referenced_by_their_full_path_in_doctor_py():
    """`tests/test_unwired_scripts_253.py` requires a tracked script to be
    mentioned by a non-narrative file; a bare `import module_name` statement does
    not contain the `.py` suffix that check matches on, so each module's full
    relative path must appear somewhere in `doctor.py` in addition to the import.
    """
    text = (SCRIPTS_DIR / "doctor.py").read_text(encoding="utf-8")
    for module_name in MOVED:
        rel = "scripts/{}.py".format(module_name)
        assert rel in text, (
            "{} is not mentioned by its full path in doctor.py, so "
            "test_unwired_scripts_253.py will report it unwired".format(rel)
        )


def test_doctor_py_runs_as_the_script_entry_point_and_reaches_every_moved_check(tmp_path):
    """The one failure mode this move can introduce that no per-check unit test can
    see: running `python3 scripts/doctor.py` (module name `__main__`, not `doctor`)
    while the moved checks do `import doctor` to reach shared helpers.

    Without `doctor.py` aliasing itself into `sys.modules["doctor"]` when it is
    `__main__`, each `import doctor` inside a moved module would trigger a SECOND,
    independent execution of doctor.py under the name "doctor" -- a different
    module object, with its own separate `FINDINGS` list that the real, running
    `__main__` copy's `main()` never inspects. Every finding a moved check reports
    would vanish from the tally silently: exit 0, a VERDICT line, just the wrong
    one. Asserting on the report TEXT for each moved check (not merely "some
    report happened") is what tells that apart from the checks running and being
    dropped anyway.
    """
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "doctor.py"), "--root", str(tmp_path)],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    output = completed.stdout.decode("utf-8", "replace")
    assert completed.returncode == 0, (
        "doctor.py must exit 0 always; got {}:\n{}".format(completed.returncode, output)
    )
    lines = output.splitlines()
    assert lines and lines[-1].startswith("VERDICT:"), (
        "the last line must be one VERDICT line; got:\n{}".format(output)
    )
    # One substring per moved check, each naming something only that check's
    # message text contains -- proof each one actually ran inside this
    # subprocess's own `__main__` copy of doctor.py, not merely that a copy of
    # `check_memory` exists somewhere importable.
    expectations = {
        "check_auto_update": "auto-update:",
        "check_statusline": "statusline:",
        "check_fragments_readme": "fragments readme:",
        "check_memory": "identity.md",
        "check_merge_permission": "gh-pr-merge",
    }
    for check_name, needle in expectations.items():
        assert needle in output, (
            "expected {}'s own output ({!r}) in the __main__ run; it is missing, "
            "which is exactly the silent-drop this test exists to catch:\n{}".format(
                check_name, needle, output
            )
        )
