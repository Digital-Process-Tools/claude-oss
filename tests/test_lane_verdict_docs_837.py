"""#837: every `lane_report` availability/overlap verdict `lane_setup.py` can
produce must be named, in backticks, by `skills/manager/phases/dispatch.md` --
the document where a maintainer reads what a lane's verdict means before
dispatching on it. #809 added `resolved-to-nothing` to the script and nothing
consumed it: `grep -rn "resolved-to-nothing" commands/ skills/ agents/`
returned nothing until this issue's own fix. This guard is the one that would
have caught that silently, and the fixture below proves it fires on the real
shape of the defect (a state added to the script, not to the doc) and passes
on the real, now-fixed pair -- never only on a synthetic string.
"""

import re

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

LANE_SETUP = REPO_ROOT / "scripts" / "lane_setup.py"

DISPATCH_MD = REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md"


def _lane_report_source(text):
    """The body of `lane_report`, from its `def` to the next top-level `def`.

    Scoped deliberately: `"state":` is a common dict key all over this file
    (worktree state, claim state, release state, ...) and a sweep of every
    occurrence would pull in verdicts this document has nothing to do with.
    """
    start = text.index("\ndef lane_report(")
    rest = text[start + 1 :]
    m = re.search(r"\ndef [a-zA-Z_]", rest)
    end = start + 1 + (m.start() if m else len(rest))
    return text[start:end]


def _availability_states(source):
    """Every non-trivial verdict string `lane_report` can produce.

    Two shapes carry the verdict: `"state": "X"` inside an `availability`
    dict, and a bare `overlap_state = "X"` assignment. `"n/a"` and
    `"resolved"` are excluded -- they are the unmarked, nothing-to-report
    defaults, not verdicts a reader has to be told how to interpret; every
    other literal is a state this test requires a document to name.
    """
    states = set()
    for m in re.finditer(r'"state":\s*"([a-z-]+)"', source):
        states.add(m.group(1))
    for m in re.finditer(r'overlap_state\s*=\s*"([a-z-]+)"', source):
        states.add(m.group(1))
    states.discard("n/a")
    states.discard("resolved")
    return states


def _named_in_doc(states, doc_text):
    missing = set()
    for state in states:
        if "`{0}`".format(state) not in doc_text:
            missing.add(state)
    return missing


def test_every_availability_state_is_named_in_dispatch_md():
    source = LANE_SETUP.read_text(encoding="utf-8")
    lane_report_source = _lane_report_source(source)
    states = _availability_states(lane_report_source)
    assert states, (
        "extraction found nothing -- the scoping regex is broken, not the doc"
    )
    assert {
        "available",
        "blocked",
        "could-not-check",
        "could-not-derive-the-held-set",
        "resolved-to-nothing",
    } <= states, "the known verdict set moved; update this test's own expectation"
    doc_text = DISPATCH_MD.read_text(encoding="utf-8")
    missing = _named_in_doc(states, doc_text)
    assert not missing, (
        "lane_report can produce {0}, and skills/manager/phases/dispatch.md "
        "names none of it -- a lane verdict a reader cannot look up".format(
            ", ".join(sorted(missing))
        )
    )


def test_control_fires_on_the_real_shape_of_the_defect():
    """Red: a state added to the script and never carried to the doc.

    Simulates #809 landing `resolved-to-nothing` with nothing updated in
    dispatch.md, by extracting the real function's states and checking them
    against a doc snippet that is missing that one word -- the exact silence
    #837 reported.
    """
    source = LANE_SETUP.read_text(encoding="utf-8")
    lane_report_source = _lane_report_source(source)
    states = _availability_states(lane_report_source)
    doc_without_the_new_state = (
        "the states are `available`, `blocked`, `could-not-check` and "
        "`could-not-derive-the-held-set`"
    )
    missing = _named_in_doc(states, doc_without_the_new_state)
    assert "resolved-to-nothing" in missing


def test_control_passes_when_every_state_is_named():
    """Green: the same kind of set, checked against a doc that names all of
    it -- proving the assertion is reachable, not permanently true."""
    states = {"available", "blocked", "could-not-check", "resolved-to-nothing"}
    doc_with_every_state = (
        "verdicts: `available`, `blocked`, `could-not-check`, `resolved-to-nothing`"
    )
    assert not _named_in_doc(states, doc_with_every_state)
