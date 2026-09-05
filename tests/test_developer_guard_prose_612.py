"""#612: agents/developer.md's #432 guard paragraph tells a developer to add
every guard test its receipt names under `guard` to whatever you run. Since
#566, that receipt line is not flat text -- `lane_setup.py` renders one of
three states per guard, and only the exists state names a file that can
actually be added to a run. #612 was filed because a brief that reads that
instruction literally against an absent row sends a dispatched agent
chasing a guard test file that does not exist in the repo it is working on --
observed on claude-supertool, one layer above the `lane_setup.py` fix that
already ships on this branch's base. The prose has to name the other two
states in the receipt's own words, not just the happy path, or the same
round-trip the issue describes happens again one file away from the fix.
"""

import pathlib

DEVELOPER_MD = (
    pathlib.Path(__file__).resolve().parent.parent / "agents" / "developer.md"
)


def test_guard_paragraph_names_all_three_receipt_states():
    text = DEVELOPER_MD.read_text(encoding="utf-8")
    anchor = "is the derived list"
    idx = text.find(anchor)
    assert idx != -1, "the #432 guard paragraph moved or was reworded"
    window = text[max(0, idx - 400) : idx + 1600]
    assert "NOT IN THIS REPO" in window, (
        "the guard paragraph must say what an absent receipt line means -- "
        "lane_setup.py's own wording, since #566"
    )
    assert "COULD NOT TELL" in window, (
        "the guard paragraph must say what a could-not-tell receipt line "
        "means -- lane_setup.py's own wording, since #566"
    )
