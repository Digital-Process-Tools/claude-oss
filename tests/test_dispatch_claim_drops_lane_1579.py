"""#1579: the dispatcher's `--claim` call must not pass `--lane`.

`lane_setup.py`'s `--claim` mode never reads its own `--lane` patterns except to
render them into the claim receipt's own `[lane]` block (`lane_setup.py:875`,
`:922`, `:1178-1192`) -- not into the prompt (#1535), not into the disjointness
check (#1532, `--derive-held`/live-worktree board), and not into `--phrase`'s
composition (`fleet_label` takes only the issue numbers and the phrase string).
Nothing outside `lane_setup.py` itself was found to read that receipt block
(grepped across `agents/`, `skills/`, `scripts/` for `lane_report`, `["lane"]`
and `[lane]`). So a `--claim` call that still composes and passes `--lane`
patterns pays a glob-resolution-and-guard-lookup cost for a value nothing reads.

The dispatcher's own, later, better-informed `--lane` call in `agents/
developer.md` -- made after recon, against the sites the lane actually intends
to edit -- is the one that decides which guards run, and is untouched by this
issue: `--lane` stays a first-class flag on `lane_setup.py` itself, required by
`--suggest-companions` (#1579's own "not established" section says so
explicitly, and `tests/test_lane_setup_851.py` already pins that requirement).
This file only checks that the *dispatch call shape documented in the loop's
own prose* stopped composing it.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

TICK_DISPATCH = REPO_ROOT / "agents" / "tick-dispatch.md"
DISPATCH = REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md"
TICK_ORDER = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"


def _claim_lines(text):
    """Every line that invokes ``lane_setup.py ... --claim``, continuation
    backslash included -- a multi-line call's flags can sit on the next
    physical line, so a single-line match would miss them.
    """
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "lane_setup.py" in line and "--claim" in line:
            joined = line
            j = i
            while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
                j += 1
                joined += " " + lines[j]
            out.append(joined)
        i += 1
    return out


def _all_claim_lines():
    return {
        "agents/tick-dispatch.md": _claim_lines(
            TICK_DISPATCH.read_text(encoding="utf-8")
        ),
        "skills/manager/phases/dispatch.md": _claim_lines(
            DISPATCH.read_text(encoding="utf-8")
        ),
        "skills/manager/phases/tick-order.md": _claim_lines(
            TICK_ORDER.read_text(encoding="utf-8")
        ),
    }


def test_the_files_document_a_claim_call_at_all():
    """Positive control: without this, the assertion below passes vacuously."""
    found = _all_claim_lines()
    assert any(found.values()), (
        "none of the three dispatch-shape files document a lane_setup.py "
        "--claim call at all -- the check below would pass over nothing"
    )


def test_no_documented_claim_call_passes_lane():
    found = _all_claim_lines()
    offenders = [
        (path, line)
        for path, lines in found.items()
        for line in lines
        if re.search(r"--lane" + chr(92) + "b", line)
    ]
    assert not offenders, (
        "a documented lane_setup.py --claim call still composes --lane (#1579) "
        "-- the dispatcher's glob guess only ever fed the claim receipt's own "
        "unread [lane] block: {0!r}".format(offenders)
    )


def test_suggest_companions_still_requires_lane():
    """The positive control for the negative assertion above: `--lane` is not
    being deleted from the script, only from the `--claim` call shape. If
    `--suggest-companions` ever stopped requiring it, the assertion above
    would be guarding a flag that no longer means anything.
    """
    import lane_setup

    text = DISPATCH.read_text(encoding="utf-8")
    assert "--suggest-companions" in text, (
        "skills/manager/phases/dispatch.md no longer mentions "
        "--suggest-companions -- nothing here proves it still requires --lane"
    )
    assert hasattr(lane_setup, "main"), "lane_setup.main missing entirely"
