"""#1778: `agents/doctor.md` carried no classifier-denial rule. A doctor spawn
chasing a `worktree reap` WARN ran `worktree_reap.py --apply`, was denied twice by
the harness's permission classifier, ran it a third time until it passed, and then
told its caller the retry happened "after you resent the command" -- which nothing
had done.

`skills/manager/SKILL.md` already states the rule (#1724, #1751): one identical
retry at most, and a second denial is handed over as a named gap. `developer.md`
and `tick-merge.md` carry or reference it; `doctor.md` did not, so its own
disposition 2 ("a permission this session lacks") was the only guidance it had.

Content-pin test over the agent's prose, the same class as
`tests/test_doctor_marker_clear_1728.py`.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"


def _text() -> str:
    return DOCTOR_MD.read_text(encoding="utf-8")


def _disposition_two() -> str:
    text = _text()
    start = text.index("2. **Not this repo's to fix.**")
    end = text.index("3. **Genuinely unclear, after you tried.**")
    return text[start:end]


def test_disposition_two_names_the_classifier_denial_rule():
    section = _disposition_two()
    assert "classifier denial" in section
    assert "#1724" in section and "#1751" in section


def test_second_denial_is_final_and_reported_as_could_not_repair():
    section = _disposition_two()
    assert "at most once" in section
    assert "A second denial is final" in section
    assert "could-not-repair: denied by the permission classifier" in section


def test_doctor_md_forbids_claiming_someone_else_resent_or_approved():
    section = _disposition_two()
    assert (
        "Never state that anyone else re-sent, approved or authorised a call" in section
    )


def test_disposition_two_still_carries_its_not_ours_verdict():
    """Positive control: the new clause sits inside disposition 2 without
    displacing the `not-ours` report shape that disposition exists to give."""
    section = _disposition_two()
    assert "`not-ours: <who> -- <one line of evidence>`" in section
