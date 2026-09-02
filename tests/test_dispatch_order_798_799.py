"""#798 and #799: the dispatch order, and how many issues a lane carries.

Two decisions taken by the maintainers on 2026-09-02 and recorded in
``docs/overview.md`` as wants 5 and 4. They are tested together because they
compose: #798 decides which issue is a lane's *top* issue, and #799 decides how
many companions join it and what a short lane must say for itself.

**#798 -- the order.** Selection used to be priority-only, which cannot separate
a maintainer's ask from the loop's own backlog. On a board where 98% of filings
are the loop's, that means a human ask waits behind them. The order is now two
axes, author before priority within a band:

    1  human, high
    2  loop,  high
    3  human, medium
    4  human, low or no priority label
    5  loop,  medium
    6  loop,  low or no priority label

"Loop" is an issue carrying ``labels.filed_by_loop``'s label. An issue without
it is a human issue.

**That default is only safe because the backlog was labelled.** The label's own
description on the tracker says "absence is not proof a human filed it", and
that was the whole objection to this rule: on 2026-09-02 the label sat on 8 of
47 open issues, so absence meant "nobody labelled it" far more often than it
meant "a human filed it", and the rule would have ranked essentially every
loop-filed issue above every labelled one. The maintainer resolved it by
labelling every open issue and pruning by hand, which makes absence a positive
act rather than a gap. Nothing here can verify that was done -- which is exactly
why ``rank`` refuses to rank at all when the repository declares no label, and
never quietly reads an unlabelled board as a board full of human issues.

**#799 -- the size.** Measured across 237 lanes (#499): three issues in one lane
cost 16% less per issue than one alone, and four or more is a cliff at 141
median turns and 68% worse per issue. So three is the default rather than the
ceiling, and a lane dispatched short says why in one of three words.

Python 3.9 compatible.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dispatch_rank  # noqa: E402
import manager_docs  # noqa: E402
from agent_budgets import repo_root  # noqa: E402


HIGH, MEDIUM, LOW = "priority-high", "priority-medium", "priority-low"
LOOP = "filed-by-loop"

#: The declared spellings a repository hands `rank`. Written out rather than
#: read from `.oss.json`, because a test that reads the config it is testing
#: against passes when both are wrong together.
DECLARED = {"priority": [HIGH, MEDIUM, LOW], "filed_by_loop": LOOP}


def _rank(labels):
    return dispatch_rank.rank(labels, DECLARED)


# --------------------------------------------------------------- #798: the order


def test_the_six_rows_rank_in_the_order_798_states():
    """Every row, in order, as one assertion rather than six -- an off-by-one
    between two adjacent rows is the failure this must catch, and testing each
    row against a literal number would pass a table that is internally
    consistent and shifted by one."""
    board = [
        ([HIGH], 1),
        ([LOOP, HIGH], 2),
        ([MEDIUM], 3),
        ([LOW], 4),
        ([], 4),
        ([LOOP, MEDIUM], 5),
        ([LOOP, LOW], 6),
        ([LOOP], 6),
    ]
    got = [(labels, _rank(labels)["rank"]) for labels, _ in board]
    assert got == board, got


def test_a_human_medium_outranks_every_loop_medium():
    """#798's own acceptance criterion, stated as it is written there: 'A board
    with one human priority-medium issue and ten loop priority-medium issues
    dispatches the human one first.'"""
    human = {"number": 1, "labels": [MEDIUM]}
    loop = [{"number": n, "labels": [LOOP, MEDIUM]} for n in range(2, 12)]
    ordered = dispatch_rank.order(loop + [human], DECLARED)
    assert ordered[0]["number"] == 1, [i["number"] for i in ordered]


def test_a_loop_high_outranks_a_human_medium():
    """The axes are not lexicographic on author alone. A blocking-class defect
    the loop found still beats an ordinary human ask, which is why the table
    interleaves rather than putting every human issue above every loop one."""
    assert _rank([LOOP, HIGH])["rank"] < _rank([MEDIUM])["rank"]


def test_no_priority_label_ranks_with_low_not_with_medium():
    """#798's rows 4 and 6 read 'low, or no label'. An unprioritised issue must
    not drift upward into the medium band by being unlabelled."""
    assert _rank([])["rank"] == _rank([LOW])["rank"]
    assert _rank([LOOP])["rank"] == _rank([LOOP, LOW])["rank"]


def test_an_undeclared_filed_by_loop_label_cannot_rank_at_all():
    """The third state, and the reason it exists.

    With no declared label, every issue on the board is unlabelled. Reading
    that as 'every issue is a human issue' would rank the loop's entire backlog
    into rows 1, 3 and 4 -- confidently, and wrongly, with nothing reporting it.
    So the author axis is unavailable and `rank` says so."""
    answer = dispatch_rank.rank([MEDIUM], {"priority": [HIGH, MEDIUM, LOW]})
    assert answer["state"] == "could-not-rank", answer
    assert answer["rank"] is None, answer
    assert "filed_by_loop" in answer["why"], answer


def test_an_undeclared_priority_set_cannot_rank_either():
    """The same refusal one axis over. A repository that declares no priority
    spellings has no bands, and inventing `priority-high` for it is the
    hardcoded-fact failure this codebase forbids."""
    answer = dispatch_rank.rank([LOOP], {"filed_by_loop": LOOP})
    assert answer["state"] == "could-not-rank", answer
    assert answer["rank"] is None, answer


def test_a_ranked_answer_says_which_band_and_which_author_it_used():
    """A bare integer cannot be argued with. The receipt names both axes so a
    maintainer reading a dispatch decision can check it without re-deriving
    the table."""
    answer = _rank([LOOP, HIGH])
    assert answer["state"] == "ranked", answer
    assert answer["author"] == "loop", answer
    assert answer["band"] == "high", answer


def test_two_priority_labels_on_one_issue_take_the_stronger():
    """Observed on this board: a triage sweep and a second writer both wrote a
    priority onto #754 within the same window. An issue carrying two bands is a
    real state, and taking the stronger is the safe direction -- the alternative
    is an issue silently sinking because somebody added a lower label."""
    assert _rank([HIGH, MEDIUM])["rank"] == _rank([HIGH])["rank"]


def test_an_unrecognised_priority_spelling_is_distinguished_from_no_priority():
    """#826. A label sharing the declared spellings' own prefix -- 'priority-'
    for this board -- but matching none of them is a renamed or mistyped
    priority label, not the absence of one. The two must not produce the same
    receipt, or a maintainer has no way to tell a typo from an unlabelled
    issue without re-deriving the board by hand."""
    unlabelled = _rank([])
    typo = _rank(["priority-critical"])
    assert typo != unlabelled, (unlabelled, typo)
    # Still usable for ordering -- the trap #826 names explicitly is a fix
    # that stops ranking the issue at all.
    assert typo["state"] == "ranked", typo
    assert typo["rank"] == unlabelled["rank"], typo
    assert typo["band"] == "low", typo
    assert typo["why"] is not None and "priority-critical" in typo["why"], typo


def test_the_genuinely_unprioritised_case_still_ranks_low():
    """Paired control for the assertion above: the fix must not become
    'refuse everything'. An issue that truly carries no priority label keeps
    the old, quiet answer."""
    answer = _rank([])
    assert answer["state"] == "ranked", answer
    assert answer["band"] == "low", answer
    assert answer["why"] is None, answer


def test_an_unrelated_label_is_not_mistaken_for_an_unrecognised_priority():
    """Must-not-fire control: a label that shares no prefix with any declared
    priority spelling is not a priority label at all, and must not be
    reported as an unrecognised one."""
    answer = _rank(["bug"])
    assert answer["why"] is None, answer


def test_no_common_prefix_means_no_unrecognised_detection():
    """If the declared spellings share no prefix, guessing that some other
    label is an unrecognised priority would be the same hardcoded-fact
    failure this module already refuses elsewhere -- there is no signal, so
    none is invented."""
    declared_no_prefix = {"priority": ["urgent", "later"], "filed_by_loop": LOOP}
    answer = dispatch_rank.rank(["priority-critical"], declared_no_prefix)
    assert answer["why"] is None, answer


def test_order_is_stable_within_a_rank():
    """Issues of equal rank keep the order they arrived in, so a caller can
    pre-sort by age or number and have that survive."""
    same = [{"number": n, "labels": [LOOP, MEDIUM]} for n in (7, 3, 9)]
    assert [i["number"] for i in dispatch_rank.order(same, DECLARED)] == [7, 3, 9]


# ---------------------------------------------------------------- #799: the size


def test_three_is_the_normal_lane_and_needs_no_reason():
    answer = dispatch_rank.check_lane([1, 2, 3], None)
    assert answer["state"] == "ok", answer
    assert answer["size"] == 3, answer


def test_a_lane_of_four_is_refused():
    """#799's acceptance criterion: refused by lane setup, before the spawn.
    Four or more is the measured cliff, not a preference."""
    answer = dispatch_rank.check_lane([1, 2, 3, 4], None)
    assert answer["state"] == "refused", answer
    assert "4" in answer["why"], answer


def test_a_short_lane_without_a_reason_is_a_defect():
    """'A single-issue lane with no reason is a defect in the tick', in #799's
    own words. The refusal is what makes the reason load-bearing rather than
    decorative."""
    answer = dispatch_rank.check_lane([1], None)
    assert answer["state"] == "short-unexplained", answer


@pytest.mark.parametrize("reason", ["board-exhausted", "no-adjacent", "could-not-tell"])
def test_a_short_lane_with_one_of_the_three_reasons_is_accepted(reason):
    answer = dispatch_rank.check_lane([1, 2], reason)
    assert answer["state"] == "ok", answer
    assert answer["short_reason"] == reason, answer


def test_an_invented_reason_is_refused():
    """The three words are a closed set. A free-text reason would make the
    handback field unreadable by anything but a human, which is the same defect
    #773 filed against a `completed` state carrying only prose."""
    answer = dispatch_rank.check_lane([1], "busy")
    assert answer["state"] == "short-unexplained", answer


def test_an_empty_lane_is_refused_rather_than_called_short():
    """Zero issues is not a short lane, it is not a lane. Rendering it as
    `short-unexplained` would invite a reason for something that should never
    have been dispatched."""
    answer = dispatch_rank.check_lane([], "board-exhausted")
    assert answer["state"] == "refused", answer


def test_could_not_tell_is_not_board_exhausted():
    """The three reasons are three facts, and the third is the absence of a
    measurement rather than a measurement that came back empty. Collapsing them
    would be this repository's own defect class landing on its own dispatch
    accounting."""
    exhausted = dispatch_rank.check_lane([1], "board-exhausted")
    unknown = dispatch_rank.check_lane([1], "could-not-tell")
    assert exhausted["short_reason"] != unknown["short_reason"]


# ------------------------------------------------------- the shipped prose


def _loop_documents():
    """Every document the loop reads, derived from disk rather than listed --
    `scripts/manager_docs.py` exists for exactly this, and a hardcoded list
    goes narrower than its subject the moment a phase file is added.

    Returns `(paths, unreadable)`. The second half is not decoration: a phases
    directory this process could not enter narrows the set silently, and a
    document that was never read carries no filing instruction to complain
    about -- so an unreadable set would report as fully compliant. #571 records
    that exact narrowing happening to `documents()` itself."""
    root = repo_root()
    paths, unreadable = manager_docs.documents(root)
    paths = list(paths)
    paths.extend(sorted((root / "agents").glob("*.md")))
    tick = root / "commands" / "tick.md"
    if tick.is_file():
        paths.append(tick)
    return [p for p in paths if p.is_file()], list(unreadable)


def _filing_instructions():
    """(path, text) for every loop document that tells somebody to file an
    issue. Found by the op name, because that is what a filing instruction
    always contains and a prose paraphrase is not."""
    paths, unreadable = _loop_documents()
    assert not unreadable, (
        "part of the loop's prose could not be read, so a document that omits "
        "the label would be invisible to this check: {}".format(unreadable)
    )
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if "gh-issue-create" in text:
            found.append((path, text))
    return found


def test_the_filing_instructions_are_findable():
    """The positive control for the check below. An extractor that matches
    nothing reports every document as compliant, which is the failure this
    whole repository is named after."""
    found = _filing_instructions()
    assert found, "no document mentions gh-issue-create -- the extractor is broken"


def test_every_filing_instruction_names_the_label():
    """#798 item 1: every issue the loop opens carries the label from creation,
    so every place that tells an agent to file must say so. A filing
    instruction that omits it produces an unlabelled issue, and an unlabelled
    issue is a human issue under the rule this same change introduces -- so the
    loop's own filings would outrank the maintainer's."""
    silent = [
        str(path.relative_to(repo_root()))
        for path, text in _filing_instructions()
        if "filed_by_loop" not in text and "filed-by-loop" not in text
    ]
    assert not silent, (
        "these documents instruct filing without naming labels.filed_by_loop: "
        "{}".format(silent)
    )


#: One markdown table row: a rank digit, then `human` or `loop`, then a
#: priority cell. Anchored per-line rather than across the whole table, so it
#: finds a row wherever one sits rather than assuming a fixed block shape.
_TABLE_ROW_RE = re.compile(
    r"^\s*\|\s*(\d+)\s*\|\s*(human|loop)\s*\|\s*([^|]+?)\s*\|\s*$",
    re.MULTILINE,
)


def _normalize_band(cell_text):
    """'low, or no priority label' -> 'low'. `None` for a cell that names none
    of `dispatch_rank.BANDS`, so a caller can tell a real row from a stray
    table elsewhere in the document that happens to match the row shape."""
    lowered = cell_text.strip().lower()
    for band in dispatch_rank.BANDS:
        if lowered.startswith(band):
            return band
    return None


def _extract_dispatch_table_rows(text):
    """Every table row in `text` shaped like the dispatch table, as
    `((rank, (author, band)), ...)` -- the same shape `dispatch_rank.ROWS`
    is in, so the two can be compared directly rather than through a second
    translation that could itself disagree with either one."""
    rows = []
    for match in _TABLE_ROW_RE.finditer(text):
        band = _normalize_band(match.group(3))
        if band is None:
            continue
        rows.append((int(match.group(1)), (match.group(2), band)))
    return tuple(rows)


def test_the_spine_states_the_table_dispatch_rank_computes():
    """#825. The six-row table in `SKILL.md` is a transcription of
    `dispatch_rank.ROWS` -- the module is the source, the table is prose
    copied from it -- and a transcription that drifts from its source is
    exactly what this can catch and a reader skimming the table cannot.

    This replaces `test_the_spine_and_dispatch_state_the_same_order`, which
    asserted only that the words 'human' and 'loop' occur somewhere in two
    thousand-word documents -- true of nearly any edit to either file, so it
    could not fail for the defect it claimed to guard against."""
    root = repo_root()
    spine = root.joinpath(*manager_docs.SPINE_REL).read_text(encoding="utf-8")
    rows = _extract_dispatch_table_rows(spine)
    assert len(rows) == len(dispatch_rank.ROWS), rows
    assert rows == dispatch_rank.ROWS, rows
    assert "dispatch_rank.py" in spine, (
        "the spine table no longer names the module that computes it, so the "
        "order reads as a thing an agent feels rather than one it can call"
    )


def test_the_table_extractor_catches_a_table_that_disagrees_with_the_module():
    """Positive control for the assertion above. Without this, a comparison
    that always saw two empty tuples would look identical to one that
    genuinely compared six rows -- the same shape #825 filed against the
    check this replaces."""
    contradicting = (
        "| Rank | Who filed | Priority |\n"
        "| --- | --- | --- |\n"
        "| 1 | human | high |\n"
        "| 2 | loop | high |\n"
        "| 3 | human | medium |\n"
        "| 4 | human | low, or no priority label |\n"
        "| 5 | loop | medium |\n"
        "| 6 | loop | medium |\n"
    )
    rows = _extract_dispatch_table_rows(contradicting)
    assert len(rows) == len(dispatch_rank.ROWS), rows
    assert rows != dispatch_rank.ROWS, rows


def test_dispatch_md_points_at_the_table_rather_than_restating_it():
    """The design the issue found sound: `SKILL.md` carries the table,
    `dispatch.md` deliberately does not restate it (#673, #547 -- a second
    copy is the copy that drifts). Asserting that absence is the real
    regression to guard, not a parity check between two copies that were
    never meant to both exist."""
    dispatch = (repo_root() / "skills/manager/phases/dispatch.md").read_text(
        encoding="utf-8"
    )
    rows = _extract_dispatch_table_rows(dispatch)
    assert not rows, (
        "dispatch.md now carries its own copy of the dispatch table -- that "
        "recreates the drift #673/#547 exist to avoid; point at the spine "
        "instead of restating it: {}".format(rows)
    )
    assert "dispatch_rank.py" in dispatch, (
        "dispatch.md must still name the module that computes the order"
    )


def test_tick_md_states_the_lane_size_bound():
    """#799 item 3. The bound belongs where step 5 dispatches, not only in the
    phase file, because a session can reach the dispatch step holding the
    command and not the phase."""
    text = (repo_root() / "commands" / "tick.md").read_text(encoding="utf-8")
    assert "never 4" in text or "never four" in text, (
        "commands/tick.md step 5 does not state the lane size bound"
    )


def test_the_prose_check_fires_on_a_silent_instruction():
    """Must-fire control for `test_every_filing_instruction_names_the_label`.
    Without it, that assertion also passes when the label spelling changes and
    nothing matches any more."""
    silent = "Run `gh-issue-create:@FILE` to file the finding."
    assert "filed_by_loop" not in silent and "filed-by-loop" not in silent
