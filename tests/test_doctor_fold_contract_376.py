"""#376: doctor.py's module contract and its set of emitters must agree.

The defect this holds shut: `report_with_remedy` (new in `0bdfacf`, for #344)
became a second emitter and deliberately exempts its `remedy` argument from the
printable-ASCII fold, while the module docstring above it went on stating the
fold unconditionally -- "Every finding goes through `report()`, which reduces it
to one printable ASCII line". A reader auditing the property from the top of the
file got the wrong answer about three arms of the launcher check.

The judgement call #376 leaves open was settled toward **amending the contract**
rather than folding the remedy: `report_with_remedy`'s own docstring argues the
exemption convincingly, and folding the remedy would reinstate #344 -- a `?`
(shell glob) sitting inside a command the reader is meant to paste and run.

So this is the guard. It is a **second measurement**, not the same claim stated
twice: one half reads the emitter set out of the AST, the other reads the prose,
and a finding is the two disagreeing. Every assertion below is paired with a
must-fire control over synthetic source, because a static check that silently
matched nothing would pass on an empty file.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"

# The full set of functions permitted to call `_emit`. Spelled out rather than
# derived, because the point is that adding a third one is a decision somebody
# has to record in this file as well as in doctor.py.
EXPECTED_EMITTERS = {"report", "report_with_remedy"}


def emitters(source):
    """Every top-level function in `source` whose body calls `_emit`."""
    tree = ast.parse(source)
    found = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name) and func.id == "_emit":
                    found.add(node.name)
    return found


def contract_findings(source):
    """Findings against the module docstring's statement of the fold.

    A list of strings; empty means the contract names the exemption.
    """
    doc = ast.get_docstring(ast.parse(source)) or ""
    flat = " ".join(doc.split())
    out = []
    if "report_with_remedy" not in flat:
        out.append("the module contract never names report_with_remedy")
    if "exempt" not in flat.lower():
        out.append("the module contract never says any fragment is exempt from the fold")
    if "remedy" not in flat:
        out.append("the module contract never names the exempt argument")
    return out


def _source():
    return DOCTOR.read_text(encoding="utf-8")


# --- must-fire controls, first, so a check that can see nothing fails here ---

# Built by joining lines rather than written as a triple-quoted literal: the
# synthetic module needs a docstring of its own, and nesting one inside this
# file's own quoting is how a fixture stops being readable.
_SYNTHETIC_OLD = "\n".join(
    [
        '"""A diagnostic.',
        "",
        "* **The tree being diagnosed does not get to write the diagnosis.** Every",
        "  finding goes through ``report()``, which reduces it to one printable ASCII",
        "  line.",
        '"""',
        "",
        "",
        "def _emit(state, flat):",
        "    print(state, flat)",
        "",
        "",
        "def report(state, message):",
        "    _emit(state, message)",
        "",
        "",
        "def report_with_remedy(state, prose, remedy):",
        "    _emit(state, prose + remedy)",
        "",
        "",
        "def report_raw(state, message):",
        "    _emit(state, message)",
        "",
    ]
)


def test_control_the_synthetic_fixture_parses():
    """The fixture is source code assembled by hand; if it stopped parsing, every
    control below would raise rather than measure, and a raising control is not a
    control that fired.
    """
    ast.parse(_SYNTHETIC_OLD)


def test_control_the_emitter_scan_sees_a_third_emitter():
    """Must fire: a module with a third `_emit` caller is not the expected set."""
    found = emitters(_SYNTHETIC_OLD)
    assert found == {"report", "report_with_remedy", "report_raw"}, found
    assert found != EXPECTED_EMITTERS


def test_control_the_contract_scan_reports_an_unconditional_fold():
    """Must fire: the pre-#376 wording produces all three findings."""
    findings = contract_findings(_SYNTHETIC_OLD)
    assert len(findings) == 3, findings


def test_control_the_contract_scan_is_not_vacuous_on_an_absent_docstring():
    """Must fire: no docstring at all is a finding, not silence."""
    assert contract_findings("x = 1"), "an undocumented module reported clean"


# --- the real subject ---


def test_doctor_source_is_readable_and_nonempty():
    """The positive control for both assertions below: a scan of an unreadable or
    empty file reports no emitters and no findings, which reads exactly like a
    clean result.
    """
    source = _source()
    assert len(source) > 10000, len(source)
    assert "def _emit(" in source


def test_only_report_and_report_with_remedy_reach_emit():
    """Must not fire. A third emitter is a new bypass of the fold, and #376 is
    what happens when one is added without the contract moving with it.
    """
    found = emitters(_source())
    assert found == EXPECTED_EMITTERS, (
        "doctor.py's set of `_emit` callers is {} -- expected {}. A new emitter is a "
        "new route around report()'s ASCII fold: say in the module contract what it "
        "does to foreign text, then add it to EXPECTED_EMITTERS here.".format(
            sorted(found), sorted(EXPECTED_EMITTERS)
        )
    )


def test_the_module_contract_names_the_exemption():
    """Must not fire. This is #376 itself."""
    findings = contract_findings(_source())
    assert not findings, (
        "doctor.py's module docstring states the printable-ASCII fold without naming "
        "the one fragment exempt from it: {}".format("; ".join(findings))
    )
