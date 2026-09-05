"""#807: `lane_setup.py`'s fourth `availability` state, `could-not-check`

(#774), was never taught to the loop's own prose. `git grep could-not-check --
skills/ agents/ commands/` returned nothing before this fix -- the runbook
still only named `could-not-derive-the-held-set` as the one third state a
manager might hit, with no mention that a refused pattern is a different
failure that does not take the same fallback.

Same shape as `tests/test_dispatch_runbook_derive_held_586.py`: every
"must say X" here is paired with proof the file is readable at all, so the
positive assertion cannot pass on a missing or empty file.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCH = REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md"
SPINE = REPO_ROOT / "skills" / "manager" / "SKILL.md"


def _read(path):
    assert path.is_file(), "{0} must exist and be readable".format(path)
    text = path.read_text(encoding="utf-8")
    assert text, "{0} must not be empty".format(path)
    return text


def test_dispatch_names_could_not_check_as_its_own_state():
    text = _read(DISPATCH)
    assert "could-not-check" in text, (
        "dispatch.md must name the fourth availability state, could-not-check "
        "(#774), rather than only could-not-derive-the-held-set (#807)"
    )


def test_dispatch_says_could_not_check_takes_a_different_response():
    """The judgment call this issue asks for: could-not-check is not

    could-not-derive-the-held-set wearing a different name, and retyping the
    identical refused pattern as --against does not fix it -- the pattern
    itself is what is wrong.
    """
    text = _read(DISPATCH)
    idx = text.index("could-not-check")
    # The paragraph naming could-not-check must say it is not the same
    # fallback as could-not-derive-the-held-set's.
    window = text[idx : idx + 1500]
    assert "could-not-derive-the-held-set" in window, (
        "the could-not-check paragraph must contrast itself against "
        "could-not-derive-the-held-set, not stand alone with no relation "
        "to the state already documented"
    )
    assert "_lane_pattern_problem" in window, (
        "the remedy has to be grounded in why a pattern is refused "
        "(_lane_pattern_problem), not asserted without a mechanism"
    )


def test_spine_table_row_names_could_not_check_too():
    text = _read(SPINE)
    idx = text.index("naming a lane, against everything already running")
    row_end = text.index("\n", idx)
    row = text[idx:row_end]
    assert "could-not-check" in row, (
        "the spine's own copy of this instruction (loaded every tick) must "
        "also name could-not-check, not only could-not-derive-the-held-set, "
        "or a fourth state exists in only one of the two copies (#807)"
    )


def test_dispatch_still_names_could_not_derive_the_held_set():
    """Must not fire if the paragraph was rewritten wholesale and lost the

    state it used to teach -- both states have to survive together.
    """
    text = _read(DISPATCH)
    assert "could-not-derive-the-held-set" in text
    assert "could-not-check" in text
