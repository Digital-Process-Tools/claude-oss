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
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    module object, reentering its own `from doctor_check_X import check_X` at the
    exact statement that started the reentry. Observed, by temporarily disabling
    the alias: with every moved module's `import doctor` placed before its own
    `def check_X`, this is not the silent FINDINGS-undercount it might sound like --
    Python's partial-module guard raises `ImportError: cannot import name
    'check_auto_update' from 'doctor_check_auto_update'` immediately, and doctor.py
    exits 1, which the `returncode == 0` assertion below already catches. The
    VERDICT-count comparison further down is retained anyway, as insurance against
    a differently-ordered future edit (`import doctor` placed after the `def`,
    say) under which the crash might soften into the silent undercount this was
    originally written to describe -- reasoned, not reproduced, since the current
    file layout crashes first every time this was tried.
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
    # The substring checks above are not the whole test: `_emit` prints
    # unconditionally regardless of which module object's `FINDINGS` list a
    # `doctor.report(...)` call happened to append to, so every one of those
    # substrings would still appear in `output` even with the aliasing bug this
    # test exists to catch -- a duplicate "doctor" module still calls the same
    # `_emit`/`_safe_print`, it just tallies into a `FINDINGS` list `main()`
    # never reads. The bug's only visible effect is in the VERDICT line's own
    # arithmetic: `main()` sums FAIL/WARN counts from ITS `FINDINGS`, so a check
    # whose report landed in a second module's list is missing from that sum
    # while its own report line still printed. Recomputing the counts from the
    # printed lines and comparing them to the VERDICT line's own numbers is
    # what actually exercises the aliasing fix rather than merely the fact that
    # `main()` ran to completion.
    verdict_line = lines[-1]
    printed_fails = sum(1 for line in lines[:-1] if line.startswith("FAIL "))
    printed_warns = sum(1 for line in lines[:-1] if line.startswith("WARN "))
    match = re.search(
        r"(\d+) failure\(s\), (\d+) warning\(s\)|(\d+) warning\(s\)", verdict_line
    )
    if verdict_line == "VERDICT: ok":
        stated_fails, stated_warns = 0, 0
    elif match and match.group(1) is not None:
        stated_fails, stated_warns = int(match.group(1)), int(match.group(2))
    elif match and match.group(3) is not None:
        stated_fails, stated_warns = 0, int(match.group(3))
    else:
        pytest.fail(
            "the VERDICT line has neither the `ok` shape nor a parseable "
            "failure/warning count: {!r}".format(verdict_line)
        )
    assert (stated_fails, stated_warns) == (printed_fails, printed_warns), (
        "the VERDICT line claims {} failure(s) and {} warning(s), but {} FAIL "
        "and {} WARN line(s) were actually printed -- this is exactly what the "
        "aliasing bug would produce: every moved check's own report line still "
        "prints (through a second module's identical `_emit`), while its state "
        "never reaches `main()`'s own `FINDINGS` tally.\n{}".format(
            stated_fails, stated_warns, printed_fails, printed_warns, output
        )
    )
