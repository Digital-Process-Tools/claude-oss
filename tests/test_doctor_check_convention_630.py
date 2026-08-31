"""#630: the split of `scripts/doctor.py` into per-check modules stopped being
applied, and nothing in the file told the next author it was a direction.

Six `scripts/doctor_check_*.py` modules exist. #628 then added a whole new check
-- 239 lines -- straight into `doctor.py`, twenty minutes before #630 was filed.
Nothing objected, and nothing could: six completed moves are a batch, not a
rule, and a comment is advice this repository has already measured at zero
effect once (#490's batching instruction, which had to become a hook).

So the convention gets a machine-checkable ratchet rather than a paragraph
alone. `scripts/doctor_modules.py` declares which `check_*` functions are still
defined inside `doctor.py`, and this file holds that declaration to disk in both
directions:

* a check in `doctor.py` that is **not** declared fails -- which is what #628
  would have hit, with the module path it belongs in named in the message;
* a declared check that is **no longer** in `doctor.py` fails too, so the list
  can only shrink. An entry left behind after a move is a licence, not a record.

The second half of #630 is the smaller instance and lives in the same place: the
header comment opened "#497: five `check_*` functions moved out" while six
modules existed. A count written down beside a set derived from disk goes stale
the moment the set moves, which is the drift this whole repository guards
against -- so the header states the convention and no tally, and that is
asserted here with a positive control rather than assumed.
"""

import ast
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import doctor  # noqa: E402
import doctor_modules  # noqa: E402


DOCTOR_SOURCE = (SCRIPTS_DIR / "doctor.py").read_text(encoding="utf-8")


# --- the module set, derived from disk ---------------------------------------


def test_the_module_set_is_read_off_disk_not_listed(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("doctor.py", "doctor_check_alpha.py", "doctor_check_beta.py", "other.py"):
        (scripts / name).write_text("", encoding="utf-8")
    modules, unreadable = doctor_modules.check_modules(scripts)
    assert modules == ["doctor_check_alpha", "doctor_check_beta"], modules
    assert unreadable == [], unreadable


def test_the_real_tree_carries_every_module_doctor_imports():
    modules, unreadable = doctor_modules.check_modules()
    assert not unreadable, unreadable
    assert len(modules) >= 6, (
        "#497 moved six checks out; the derivation found {!r}".format(modules)
    )
    for name in modules:
        rel = "scripts/{}.py".format(name)
        assert rel in DOCTOR_SOURCE, (
            "{} exists on disk and doctor.py never names it by its full path, so "
            "tests/test_unwired_scripts_253.py will report it unwired -- and, more "
            "to the point, nothing calls it".format(rel)
        )


@pytest.mark.must_assert_on("linux")
def test_an_unreadable_scripts_directory_is_not_an_empty_module_set(tmp_path):
    """The third state, and the reason this is a function. A directory that could
    not be listed and a directory with no modules in it must not both come back
    as `[]` -- every guard built on this would then pass vacuously."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "doctor_check_alpha.py").write_text("", encoding="utf-8")

    readable, _unreadable = doctor_modules.check_modules(scripts)
    assert readable == ["doctor_check_alpha"], (
        "positive control: the fixture must be readable before it is denied, or "
        "the assertion below is about a directory that was never right"
    )

    try:
        os.chmod(str(scripts), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is whether "
            "an unreadable scripts directory is distinguishable from an empty "
            "one".format(exc)
        )
    try:
        if os.access(str(scripts), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 directory (root, or a filesystem "
                "without POSIX modes); what went untested is whether an unreadable "
                "scripts directory is distinguishable from an empty one"
            )
        try:
            os.listdir(str(scripts))
        except OSError:
            pass
        else:
            pytest.skip(
                "the deny did not take -- os.listdir still succeeded on the 0o000 "
                "directory; what went untested is whether an unreadable scripts "
                "directory is distinguishable from an empty one"
            )
        modules, unreadable = doctor_modules.check_modules(scripts)
        assert modules == [], modules
        assert unreadable, (
            "a directory that could not be listed came back as an empty module "
            "set with nothing said about it"
        )
    finally:
        os.chmod(str(scripts), 0o700)


# --- what is still defined inside doctor.py ----------------------------------


def test_inline_checks_are_derived_from_the_source_not_from_a_list():
    state, names = doctor_modules.inline_checks(DOCTOR_SOURCE)
    assert state == "read", (state, names)
    assert "check_config" in names
    assert "check_memory" not in names, (
        "check_memory is imported back from doctor_check_memory.py, not defined "
        "here -- a re-export must not read as an inline check, or every completed "
        "move would still count against the ratchet"
    )


def test_unparseable_source_is_could_not_read_never_an_empty_set():
    state, detail = doctor_modules.inline_checks("def check_x(:\n")
    assert state == "could-not-read", (state, detail)


# --- the ratchet -------------------------------------------------------------


def test_every_check_defined_in_doctor_py_is_declared():
    """This is the assertion #628 would have failed."""
    state, findings = doctor_modules.convention_state()
    assert state == "ok", (
        "scripts/doctor_modules.py and scripts/doctor.py disagree about which "
        "checks are still inline:\n  {}".format("\n  ".join(findings))
    )


def test_a_new_inline_check_is_refused_and_told_where_it_belongs():
    """The positive control for the assertion above: with the real source it
    passes, so the failure arm has to be exercised against a source that adds
    one -- otherwise `ok` proves only that nothing was compared."""
    source = DOCTOR_SOURCE + "\n\ndef check_brand_new_subject():\n    return None\n"
    state, findings = doctor_modules.convention_state(source=source)
    assert state == "findings", (state, findings)
    joined = "\n".join(findings)
    assert "check_brand_new_subject" in joined
    assert "doctor_check_brand_new_subject.py" in joined, (
        "the refusal has to name the module the check belongs in, or the next "
        "author learns only that something is wrong; got:\n{}".format(joined)
    )


def test_a_declaration_left_behind_after_a_move_is_refused():
    """The ratchet's other direction: the declared set can only shrink. An entry
    for a check that has already moved is a licence rather than a record."""
    state, findings = doctor_modules.convention_state(
        declared_pending=doctor_modules.PENDING + ("check_a_ghost",)
    )
    assert state == "findings", (state, findings)
    assert "check_a_ghost" in "\n".join(findings)


def test_the_shared_helpers_are_declared_apart_from_the_pending_checks():
    """`check_tool` and `check_directory` take their subject as an argument --
    they are the machinery, not a check of anything in particular, and they are
    not "not moved yet". Folding the two lists together would make the pending
    list's own count meaningless."""
    assert set(doctor_modules.SHARED) & set(doctor_modules.PENDING) == set()
    state, names = doctor_modules.inline_checks(DOCTOR_SOURCE)
    assert state == "read"
    assert set(doctor_modules.SHARED) <= set(names)


def test_an_unreadable_doctor_source_is_could_not_read_not_ok():
    state, findings = doctor_modules.convention_state(
        source=None, source_path=Path("no-such-file")
    )
    assert state == "could-not-read", (state, findings)
    assert state != "ok"


# --- the half that keeps working after the extraction stops ------------------


CONVENTION_HEADER = doctor_modules.convention_header(DOCTOR_SOURCE)


def test_doctor_py_states_the_convention_at_the_top():
    assert CONVENTION_HEADER, (
        "scripts/doctor.py carries no convention block at all -- #630's part 2 is "
        "the half that keeps working after the extraction stops"
    )
    for needed, why in (
        ("scripts/doctor_check_", "the module path a new check is expected to take"),
        ("import doctor", "how a moved module reaches shared names"),
        ("main()", "where the check is called from"),
        ("scripts/doctor_modules.py", "the derivation and the guard behind the rule"),
    ):
        assert needed in CONVENTION_HEADER, (
            "the convention block does not name {} ({})".format(needed, why)
        )


def test_the_convention_states_when_staying_in_doctor_py_is_right():
    """A prohibition somebody has to route around is not a rule. #630 asks for the
    exception to be part of the sentence."""
    lowered = CONVENTION_HEADER.lower()
    assert "shared" in lowered, (
        "the convention block states no exception, so it reads as a prohibition"
    )


def test_the_convention_block_states_no_tally_of_the_modules():
    """#630's second, smaller instance: the header opened "#497: five `check_*`
    functions moved out" while six modules existed. A count beside a set derived
    from disk is stale the moment the set moves."""
    offenders = doctor_modules.counted_claims(CONVENTION_HEADER)
    assert offenders == [], (
        "the convention block writes down a count of something the filesystem "
        "already answers: {!r}".format(offenders)
    )


def test_the_stale_count_this_replaces_would_still_be_caught():
    """The positive control for the assertion above. Without it, `no offenders`
    is also what a detector that matches nothing at all returns."""
    stale = (
        "# #497: five `check_*` functions moved out of this file into their own\n"
        "# modules (`scripts/doctor_check_*.py`).\n"
    )
    assert doctor_modules.counted_claims(stale) == ["five check_* functions"], (
        doctor_modules.counted_claims(stale)
    )
    assert doctor_modules.counted_claims("# six modules live beside this one\n") == [
        "six modules"
    ]


def test_the_detector_does_not_fire_on_an_ordinary_issue_reference():
    """A block naming `#497` and `#630` is full of digits and none of them is a
    tally. A detector that fires on those would be edited away within a week."""
    assert doctor_modules.counted_claims("# #497 and #630, python 3.9 compatible\n") == []


# --- every module on disk is one object, not two copies ----------------------


def test_each_module_is_re_exported_rather_than_copied():
    import importlib

    modules, unreadable = doctor_modules.check_modules()
    assert not unreadable, unreadable
    for module_name in modules:
        module = importlib.import_module(module_name)
        checks = [
            name
            for name in dir(module)
            if name.startswith("check_") and callable(getattr(module, name))
        ]
        assert checks, "{} defines no check at all".format(module_name)
        for name in checks:
            assert hasattr(doctor, name), (
                "doctor.{} is missing -- the module is on disk and nothing calls "
                "into it".format(name)
            )
            assert getattr(doctor, name) is getattr(module, name), (
                "doctor.{0} and {1}.{0} are two different objects -- the "
                "two-copies-that-drift shape, not a re-export".format(name, module_name)
            )


def test_no_module_reaches_doctor_with_a_from_import():
    """`from doctor import name` binds the value at import time, so a test's
    `monkeypatch.setattr(doctor, ...)` never reaches the moved code. The existing
    modules all say so in prose; this is the assertion behind the prose."""
    modules, unreadable = doctor_modules.check_modules()
    assert not unreadable, unreadable
    offenders = []
    for module_name in modules:
        source = (SCRIPTS_DIR / "{}.py".format(module_name)).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module == "doctor":
                offenders.append(
                    "{}:{} imports {} out of doctor".format(
                        module_name, node.lineno, ", ".join(a.name for a in node.names)
                    )
                )
    assert offenders == [], offenders
