"""Guard against #520: the fleet floor bounded lanes and said nothing about issues

per lane, so four single-issue lanes computed `filled` while related work sat
unstarted on files those lanes already held.

`skills/manager/SKILL.md`'s *Run a fleet, not a queue* used to define `filled`
purely as "one developer per available lane" -- an axis that stays satisfied by a
fleet of single-issue lanes even when every further open issue on the board
routes through a file one of those lanes already claims. This test asserts the
post-condition a maintainer needs from the fixed prose, not the presence of any
one sentence: `filled` reads on **both** axes, the second axis is checkable with
the same tool the disjointness check already uses, and `under-filled` names what
blocked a lane from taking a further issue rather than only how many lanes ran.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "manager" / "SKILL.md"


def _text():
    return SKILL.read_text(encoding="utf-8")


def _fleet_section():
    text = _text()
    start = text.index("### Run a fleet, not a queue")
    # up to the next top-level or second-level heading
    rest = text[start + 1 :]
    match = re.search(r"\n#{2,3} ", rest)
    end = start + 1 + (match.start() if match else len(rest))
    return text[start:end]


def test_fleet_section_exists():
    assert "### Run a fleet, not a queue" in _text()


def test_filled_is_defined_on_both_axes():
    section = _fleet_section()
    assert re.search(r"one developer per\b.*\blane", section, re.DOTALL), (
        "the lane-count axis must still be part of `filled` (#520)"
    )
    assert re.search(
        r"every further open issue|further issue|second issue",
        section,
        re.IGNORECASE,
    ), (
        "`filled` must also require that each lane carry every further open issue whose "
        "files fall inside its already-claimed set -- not lane count alone (#520)"
    )


def test_under_filled_names_the_blocking_file_and_queued_issues():
    section = _fleet_section()
    assert re.search(r"under-filled", section), "the under-filled state must still be named"
    assert re.search(r"shared file|blocking file|already-claimed", section, re.IGNORECASE), (
        "an under-filled lane's receipt must name the shared/already-claimed file that "
        "blocked a further issue from joining it (#520)"
    )
    assert re.search(r"queued", section, re.IGNORECASE), (
        "an under-filled lane's receipt must name the issues queued behind the blocking "
        "file, not just report a smaller count (#520)"
    )


def test_second_axis_stays_a_maintainer_judgement_not_a_script_claim():
    """#267: an issue's files are not derivable from its body, so the script must not be

    framed as enumerating candidate issues on its own -- only as answering the
    intersection once the maintainer has named them.
    """
    section = _fleet_section()
    assert "#267" in section, (
        "the second axis must cite #267 -- an issue's files are not derivable from its "
        "body, so this stays a maintainer judgement the script supports"
    )
    assert "lane_setup.py" in section, (
        "the second axis must point at the same tool (`lane_setup.py`) the disjointness "
        "check already uses, not a new mechanism"
    )


def test_positive_control_old_wording_fails_the_axis_check():
    """The pre-#520 wording -- lane count only -- must not satisfy the second-axis test."""
    old_wording = (
        "each tick dispatches one developer per file-disjoint lane the board offers. "
        "Three states, computed rather than felt: `filled` -- one developer per available "
        "lane; `under-filled` -- with the count and the reason; and `could-not-tell`."
    )
    assert not re.search(
        r"every further open issue|further issue|second issue", old_wording, re.IGNORECASE
    ), "the positive control itself must fail -- otherwise the check above verifies nothing"
