"""#1719: the doctor's own brief always passed `--i-was-asked`, so the #1690
`scaffold.py --apply` refusal could never actually refuse the doctor.

#1690 built a code-level guard (`agent_role.scaffold_apply_refusal`) that
refuses `scaffold.py --apply` under role `doctor` unless `--i-was-asked` is
passed -- the escape hatch for the doctor's own sanctioned, scripted repair
path. But `agents/doctor.md`'s "Ours to repair" step supplied that flag
unconditionally, on every run, regardless of what the spawning caller's own
prompt said. A doctor spawn told "diagnose only, do not repair anything" hit
the identical literal line as an ordinary repair run and still ran `--apply`
-- the guard was live in code but unreachable in practice, because nothing
in the brief ever withheld the flag.

The fix: the brief now checks, before running `--apply`, whether its own
prompt told it to diagnose only or skip repair; if so it never passes
`--i-was-asked` and never runs `--apply` at all, reporting `not-ours: repair
skipped` instead.

Content-pin test, the same class as `tests/test_doctor_role_marker_gate_
1690.py`: it cannot prove a spawn obeys its brief, only that the brief still
says what it must.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"


def _text():
    return DOCTOR_MD.read_text(encoding="utf-8")


def test_the_apply_bullet_checks_the_prompt_before_using_the_escape_hatch():
    text = _text()
    apply_idx = text.find("scripts/scaffold.py --apply --i-was-asked")
    assert apply_idx != -1
    # The conditional gate must sit in the SAME bullet as the apply call,
    # not merely somewhere in the file -- a check placed elsewhere would
    # not visibly govern this specific line.
    nearby = text[max(0, apply_idx - 400) : apply_idx + 400]
    assert "#1719" in nearby
    assert "diagnose only" in nearby or "skip repair" in nearby


def test_a_skip_instruction_means_no_apply_and_no_escape_hatch():
    text = _text()
    assert "never pass `--i-was-asked`" in text
    assert "run no `--apply` at all" in text or "no `--apply`" in text


def test_the_skip_reports_not_ours_rather_than_silently_continuing():
    assert "not-ours: repair skipped" in _text()


def test_the_1690_escape_hatch_still_appears_for_the_ordinary_case():
    """The #1690 guardrail (the doctor's own sanctioned repair passes
    --i-was-asked) must not have been silently dropped while adding the new
    conditional -- only narrowed to the case where nothing said otherwise."""
    assert "scaffold.py --apply --i-was-asked" in _text()
