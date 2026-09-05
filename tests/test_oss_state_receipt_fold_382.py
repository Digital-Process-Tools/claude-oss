r"""#382: `oss_state`'s receipt renderers printed their fields raw, so a newline in one
forges receipt lines a reader cannot tell from the tool's own.

`scripts/oss_state.py` carried no fold at all -- `release_delta.py`, `doctor.py`,
`release_version.py`, `scaffold.py` and (since #372/`6d5e95d`) `lane_setup.py` all have
one. This is #372's class one module over, in the receipt `45f56c7` added.

Measured before the fix, as reprs:

    'lane models tick\nlane models X: FORGED-WINDOW: 1 sonnet (0 overrides)'
    'intake tick\nintake X: FORGED: could not count (why\nintake Y: FORGED-WHY) -- ...'

The issue names `lane_models_line` and says in *Not claimed* that it is "the one
receipt". That understated it by one: `intake_line`, two hundred lines up in the same
file, renders `window` and `why` through the same raw `.format` and forges identically.
Both are covered here, and the fix is one module-level fold applied at each renderer's
single join rather than a guard per field -- a per-field guard closes what somebody
enumerated and leaves the next field unguarded, which is the argument `6d5e95d` already
made for `lane_setup.receipt()`.

Unlike `lane_setup.receipt()`, neither line here is column-aligned: there is no `{:<10}`
padding anywhere in this module, so `_one_line`'s `" ".join(text.split())` would destroy
nothing. It is still not what runs, for a different reason -- this module has no
`_one_line` to reuse, and the truncation these lines need is a **marked** one.

The assertion is the rendered **line count** against a clean control, per the issue: a
regex that matched would also pass against a version that folded the value and printed
it somewhere else. Every "must not forge" case is paired with a "must still render" one
in the same fixture, because a renderer that returned "" would have a very stable line
count.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

# Shaped exactly like a line each renderer really prints, so a forged line is
# indistinguishable from a real one by eye. That is the whole defect.
FORGE_LANES = "\nlane models the next tick: 9 opus (0 overrides)"
FORGE_INTAKE = "\nintake the next tick: 0 filings / 9 merged pull requests = 0.00"


def _lane_record(window="a tick", model="sonnet"):
    return oss_state.lane_models(
        [{"issue": 1, "model": model, "choice": oss_state.CHOICE_DEFAULT}],
        window=window,
    )


# --------------------------------------------------------------------------
# lane_models_line
# --------------------------------------------------------------------------


def test_clean_lane_line_is_one_line_and_carries_every_field():
    """The positive control. Without it, a renderer returning "" passes every
    must-not-forge case below."""
    line = oss_state.lane_models_line(_lane_record())
    assert len(line.splitlines()) == 1
    assert "lane models a tick:" in line
    assert "1 sonnet" in line
    assert "(0 overrides)" in line


@pytest.mark.parametrize(
    "record_kwargs",
    [
        {"window": "a tick" + FORGE_LANES},
        {"model": "sonnet" + FORGE_LANES},
    ],
    ids=["window", "model"],
)
def test_no_lane_field_can_forge_a_second_line(record_kwargs):
    clean = len(oss_state.lane_models_line(_lane_record()).splitlines())
    forged = oss_state.lane_models_line(_lane_record(**record_kwargs))
    assert len(forged.splitlines()) == clean == 1
    # And the value is still reported, folded -- not dropped. A renderer that
    # deleted the field would also pass the line count.
    assert "?" in forged


def test_could_not_establish_why_cannot_forge():
    record = oss_state.lane_models(None, window="a tick", why="no roster" + FORGE_LANES)
    line = oss_state.lane_models_line(record)
    assert len(line.splitlines()) == 1
    assert "could not establish" in line
    assert "this is not zero lanes" in line


def test_partial_lane_state_cannot_forge_through_why():
    record = {
        "state": oss_state.LANES_PARTIAL,
        "window": "six ticks",
        "lanes": 3,
        "counts": {"sonnet": 3},
        "overrides": 0,
        "why": "two ticks recorded nothing" + FORGE_LANES,
    }
    line = oss_state.lane_models_line(record)
    assert len(line.splitlines()) == 1
    assert line.startswith("PARTIAL,")
    assert "3 sonnet" in line


def test_unrecognised_lane_state_is_safe_by_repr_not_by_the_fold():
    r"""Named for what it is. The unrecognised-state branch is the one branch the
    fold does not decide: it renders the state through `{!r}`, which escapes a
    newline to a literal backslash-n before `_receipt_line` sees anything, so a
    line-count assertion here passes with the fold stubbed out and measures nothing.

    Asserting the escaped form instead is not vacuous: it fails the moment that
    branch is changed to `{}`, because then the real newline reaches the fold and
    comes back as `?`. So this pins the mechanism that actually holds the branch.
    """
    line = oss_state.lane_models_line(
        {"state": "not-a-state" + FORGE_LANES, "window": "a tick"}
    )
    assert len(line.splitlines()) == 1
    assert "nothing is claimed" in line
    assert r"\n" in line
    assert "?" not in line


# --------------------------------------------------------------------------
# intake_line -- same module, same class, not named by the issue
# --------------------------------------------------------------------------


def test_clean_intake_line_is_one_line_and_carries_every_field():
    line = oss_state.intake_line(oss_state.intake(6, 11, "a tick"))
    assert len(line.splitlines()) == 1
    assert "intake a tick:" in line
    assert "6 filings" in line
    assert "11 merged pull requests" in line
    assert "0.55" in line


def test_intake_window_cannot_forge():
    line = oss_state.intake_line(oss_state.intake(6, 11, "a tick" + FORGE_INTAKE))
    assert len(line.splitlines()) == 1
    assert "6 filings" in line
    assert "?" in line


def test_intake_could_not_count_why_cannot_forge():
    record = oss_state.intake(None, 11, "a tick", why="no count" + FORGE_INTAKE)
    line = oss_state.intake_line(record)
    assert len(line.splitlines()) == 1
    assert "could not count" in line
    assert "this is not zero" in line


def test_intake_partial_why_cannot_forge():
    record = {
        "state": oss_state.INTAKE_PARTIAL,
        "window": "six ticks",
        "filings": 2,
        "merged_prs": 3,
        "ratio": None,
        "why": "one tick contributed no pair" + FORGE_INTAKE,
    }
    line = oss_state.intake_line(record)
    assert len(line.splitlines()) == 1
    assert "PARTIAL" in line


# --------------------------------------------------------------------------
# What the fold does and does not do
# --------------------------------------------------------------------------


def test_carriage_return_and_control_characters_are_folded_too():
    """A bare CR repaints a line on a terminal without ever adding one, so a
    line-count assertion alone cannot see it."""
    line = oss_state.lane_models_line(_lane_record(window="a tick\rOVERWRITTEN\x1b[2K"))
    assert "\r" not in line
    assert "\x1b" not in line
    assert len(line.splitlines()) == 1


def test_an_ordinary_line_passes_through_byte_for_byte():
    """The must-fire half's opposite: the fold must not rewrite a clean receipt.
    Two spaces are deliberate -- this module aligns nothing, but a fold that
    collapsed runs of spaces would be the wrong one to have reached for."""
    record = _lane_record(window="since  the last tick")
    assert oss_state.lane_models_line(record) == (
        "lane models since  the last tick: 1 sonnet (0 overrides)"
    )


def test_a_truncated_line_says_so():
    """A cut line rendering as a complete one is this repository's own defect
    class pointed at its own receipt."""
    record = _lane_record(window="w" * (oss_state._RECEIPT_LINE_LIMIT + 500))
    line = oss_state.lane_models_line(record)
    assert len(line) == oss_state._RECEIPT_LINE_LIMIT
    assert line.endswith(oss_state._TRUNCATION_MARK)
    assert len(line.splitlines()) == 1


def test_a_line_at_the_limit_is_not_marked():
    """The paired must-not-fire: truncation that fires on an uncut line would
    make every receipt claim it lost something."""
    line = oss_state.lane_models_line(_lane_record())
    assert len(line) < oss_state._RECEIPT_LINE_LIMIT
    assert oss_state._TRUNCATION_MARK not in line
