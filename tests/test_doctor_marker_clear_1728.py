"""#1728: `agents/doctor.md` writes its own role marker (`agent_role.py
--write doctor`, #1690) as its very first step, but had no step that ever
cleared it. Every ordinary `/oss:run` step-1 doctor spawn left that marker
live for up to `agent_role.MARKER_TTL_SECONDS`, long enough that the very
next tick's own `sub-manager` refused to declare its role (#1716's own
conflict refusal, tripped by the doctor's own residue rather than a real
rival).

The sub-manager already clears its own marker through
`tick_handback.py --clear-marker-root` (#1585); the doctor has no code-level
handback classifier to hang an equivalent off, so the fix is a prose step in
this loop-prose file, pinned here the same way `tests/test_stale_remedy_
strings_1431.py` pins other instructive strings in a sibling agent file.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"


def _text() -> str:
    return DOCTOR_MD.read_text(encoding="utf-8")


def test_doctor_md_clears_its_own_role_marker_before_reporting():
    text = _text()
    assert (
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_role.py" --clear --root .' in text
    )


def test_doctor_md_names_the_stop_case_that_must_skip_the_clear():
    """Must-not-fire control: a run that stopped at the top-of-file
    `could-not-tell` (a live marker names a different role, #1716) never
    wrote a marker of its own, so it must not be told to clear one that
    belongs to a real, live rival."""
    text = _text()
    idx = text.index(
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_role.py" --clear --root .'
    )
    preceding = text[:idx]
    assert "could-not-tell" in preceding
    assert "you never wrote a marker of your own to begin with" in preceding


def test_doctor_md_reports_a_failed_clear_as_a_finding_not_silently():
    text = _text()
    assert "could-not-tell: could not\nclear this run's own role marker" in text
