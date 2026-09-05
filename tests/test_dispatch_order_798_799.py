"""#798 and #799: the dispatch order, and how many issues a lane carries.

Two decisions taken by the maintainers on 2026-09-02 and recorded in
``docs/overview.md`` as wants 5 and 4. They are tested together because they
compose: #798 decides which issue is a lane's *top* issue, and #799 decides how
many companions join it and what a short lane must say for itself.

**#798 -- the order.** Selection used to be priority-only, which cannot separate
a maintainer's ask from the loop's own backlog. On a board where 98% of filings
are the loop's, that means a human ask waits behind them. The order is now two
axes, author before priority within a band -- and **#993 replaced the old
six-row table with nine computed rows, ranks 2-10** (rank 1 is a documented,
uncomputed "blocking-class defect" row): "human" split into "external" and
"maintainer", read from GitHub's own author association rather than a
declared label, because that axis was collapsing an outside reporter and the
maintainer into one band and sinking an untriaged external bug report -- see
``dispatch_rank.py``'s own module docstring for the current table.

"Loop" is still an issue carrying ``labels.filed_by_loop``'s label. An issue
without it is either external or maintainer, never a fallback "human" band.

**That default is only safe because the backlog was labelled.** The label's own
description on the tracker says "absence is not proof a human filed it", and
that was the whole objection to this rule: on 2026-09-02 the label sat on 8 of
47 open issues, so absence meant "nobody labelled it" far more often than it
meant "a human filed it", and the rule would have ranked essentially every
loop-filed issue above every labelled one. The maintainer resolved it by
labelling every open issue and pruning by hand, which makes absence a positive
act rather than a gap. Nothing here can verify that was done -- which is exactly
why ``rank`` refuses to rank at all when the repository declares no label, and
never quietly reads an unlabelled board as though every issue on it were
external or maintainer.

**#799 -- the size.** Measured across 237 lanes (#499): three issues in one lane
cost 16% less per issue than one alone, and four or more is a cliff at 141
median turns and 68% worse per issue. So three is the default rather than the
ceiling, and a lane dispatched short says why in one of three words.

Python 3.9 compatible.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import select_issues_rank as dispatch_rank  # noqa: E402
import manager_docs  # noqa: E402
from agent_budgets import repo_root  # noqa: E402


HIGH, MEDIUM, LOW = "priority-high", "priority-medium", "priority-low"
LOOP = "filed-by-loop"
EXTERNAL, MAINTAINER = "external", "maintainer"

#: The declared spellings a repository hands `rank`. Written out rather than
#: read from `.oss.json`, because a test that reads the config it is testing
#: against passes when both are wrong together.
DECLARED = {"priority": [HIGH, MEDIUM, LOW], "filed_by_loop": LOOP}


def _rank(labels, association=None):
    return dispatch_rank.rank(labels, DECLARED, association)


# --------------------------------------------------------------- #798: the order


def test_the_nine_rows_rank_in_the_order_993_states():
    """Every computed row, in order, as one assertion rather than nine -- an
    off-by-one between two adjacent rows is the failure this must catch, and
    testing each row against a literal number would pass a table that is
    internally consistent and shifted by one.

    #993 replaces #798's six-row table with nine computed rows (external /
    maintainer / loop, crossed with high / medium / low) plus a tenth,
    prose-only row -- 'any author, a blocking-class row in the findings
    table' -- that `rank()` never returns (see the module docstring). Rank
    numbering starts at 2 for exactly that reason: rank 1 is reserved for the
    row this module does not compute."""
    board = [
        ([HIGH], EXTERNAL, 2),
        ([HIGH], MAINTAINER, 3),
        ([LOOP, HIGH], None, 4),
        ([MEDIUM], EXTERNAL, 5),
        ([MEDIUM], MAINTAINER, 6),
        ([LOOP, MEDIUM], None, 7),
        ([LOW], EXTERNAL, 8),
        ([], EXTERNAL, 8),
        ([LOW], MAINTAINER, 9),
        ([], MAINTAINER, 9),
        ([LOOP, LOW], None, 10),
        ([LOOP], None, 10),
    ]
    got = [
        (labels, dispatch_rank.rank(labels, DECLARED, assoc)["rank"])
        for labels, assoc, _ in board
    ]
    want = [(labels, rank) for labels, _, rank in board]
    assert got == want, got


def test_an_external_or_maintainer_medium_outranks_every_loop_medium():
    """#798's own acceptance criterion, stated as it is written there: 'A board
    with one human priority-medium issue and ten loop priority-medium issues
    dispatches the human one first.' #993 splits that 'human' issue into
    external and maintainer; both still outrank the loop's own medium band."""
    non_loop = {"number": 1, "labels": [MEDIUM], "author_association": MAINTAINER}
    loop = [{"number": n, "labels": [LOOP, MEDIUM]} for n in range(2, 12)]
    ordered = dispatch_rank.order(loop + [non_loop], DECLARED)
    assert ordered[0]["number"] == 1, [i["number"] for i in ordered]


def test_a_loop_high_outranks_a_maintainer_medium():
    """The axes are not lexicographic on author alone. A blocking-class defect
    the loop found still beats an ordinary ask, which is why the table
    interleaves rather than putting every non-loop issue above every loop
    one."""
    assert _rank([LOOP, HIGH])["rank"] < _rank([MEDIUM], MAINTAINER)["rank"]


def test_no_priority_label_ranks_with_low_not_with_medium():
    """#993's rows 8-9 read 'low, or no label' the same way #798's did. An
    unprioritised issue must not drift upward into the medium band by being
    unlabelled."""
    assert _rank([], MAINTAINER)["rank"] == _rank([LOW], MAINTAINER)["rank"]
    assert _rank([LOOP])["rank"] == _rank([LOOP, LOW])["rank"]


def test_an_unreadable_author_association_cannot_rank_either():
    """The third state #993 asks for explicitly: GitHub's author association
    could not be read for a non-loop issue. Guessing 'external' would promote
    a stranger's ask above the maintainer's own; guessing 'maintainer' would
    quietly demote a genuine external report. Neither is safe, so `rank`
    refuses -- the same discipline it already applies to an undeclared
    `filed_by_loop` or an undeclared priority set."""
    answer = _rank([HIGH])
    assert answer["state"] == "could-not-rank", answer
    assert answer["rank"] is None, answer
    assert "association" in answer["why"], answer


def test_an_unrecognised_association_value_is_could_not_tell_too():
    """Must-fire control: a caller passing anything other than the two
    recognised spellings is the same fact as passing nothing -- it must not
    be silently accepted as a third, invented author."""
    answer = _rank([HIGH], "could-not-tell")
    assert answer["state"] == "could-not-rank", answer


def test_a_readable_association_does_rank_the_positive_control():
    """Positive control for the two tests above: a *readable* association
    does place the issue, so the refusal is about the specific unreadable
    case and not a blanket regression that never ranks a non-loop issue at
    all."""
    answer = _rank([HIGH], EXTERNAL)
    assert answer["state"] == "ranked", answer
    assert answer["rank"] == 2, answer


def test_an_unrankable_association_sorts_last_not_first_or_middle():
    """Paired with #798's own 'could-not-rank sorts last' discipline: an
    issue whose author association could not be read must not slip to the
    front of the board the way an unlabelled loop issue must not either."""
    unreadable = {"number": 1, "labels": [HIGH]}
    ranked = [{"number": n, "labels": [LOOP, LOW]} for n in (2, 3)]
    ordered = dispatch_rank.order(ranked + [unreadable], DECLARED)
    assert ordered[-1]["number"] == 1, [i["number"] for i in ordered]


def test_an_unrankable_issue_sorts_last_even_when_it_arrives_first_993():
    """Found by review (#993 self-review round): `order()`'s fallback sort
    key for an unrankable issue used to be `len(ROWS) + 1`, which was
    strictly above every real rank only while `ROWS` was numbered
    `1..len(ROWS)`. #993 renumbered `ROWS` to start at 2 (nine rows, ranks
    2-10), so `len(ROWS) + 1 == 10` collided with the real `loop`/`low`
    rank -- and `sorted()`'s own stability then let an unrankable issue
    keep whatever position it already held relative to a genuine rank-10
    issue, rather than being pushed after it. The test above never caught
    this because it always placed the unrankable issue *last* in its input,
    where stable-sort tie-breaking hides the collision; this one places it
    *first*, which is the arrangement the old formula got wrong."""
    unreadable = {"number": 1, "labels": [LOW]}
    loop_low = [{"number": n, "labels": [LOOP, LOW]} for n in (2, 3)]
    ordered = dispatch_rank.order([unreadable] + loop_low, DECLARED)
    assert ordered[-1]["number"] == 1, [i["number"] for i in ordered]


def test_a_loop_labelled_issue_ignores_whatever_association_it_carries():
    """A loop-filed issue is filed under the maintainer's own GitHub account,
    so its author association can never distinguish 'loop' from 'maintainer'
    -- `labels.filed_by_loop` settles the author axis first, and any
    association value passed alongside it (even 'external', which would be
    wrong for a loop-filed issue but is exactly what a stale caller might
    still send) must not override that."""
    answer = _rank([LOOP, HIGH], EXTERNAL)
    assert answer["author"] == "loop", answer
    assert answer["rank"] == 4, answer


def test_an_undeclared_filed_by_loop_label_cannot_rank_at_all():
    """The third state, and the reason it exists.

    With no declared label, every issue on the board is unlabelled. Reading
    that as 'every issue is external or maintainer' would rank the loop's
    entire backlog into every non-loop row -- confidently, and wrongly, with
    nothing reporting it. So the author axis is unavailable and `rank` says
    so."""
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
    assert (
        _rank([HIGH, MEDIUM], MAINTAINER)["rank"] == _rank([HIGH], MAINTAINER)["rank"]
    )


def test_an_unrecognised_priority_spelling_is_distinguished_from_no_priority():
    """#826. A label sharing the declared spellings' own prefix -- 'priority-'
    for this board -- but matching none of them is a renamed or mistyped
    priority label, not the absence of one. The two must not produce the same
    receipt, or a maintainer has no way to tell a typo from an unlabelled
    issue without re-deriving the board by hand."""
    unlabelled = _rank([], MAINTAINER)
    typo = _rank(["priority-critical"], MAINTAINER)
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
    answer = _rank([], MAINTAINER)
    assert answer["state"] == "ranked", answer
    assert answer["band"] == "low", answer
    assert answer["why"] is None, answer


def test_an_unrelated_label_is_not_mistaken_for_an_unrecognised_priority():
    """Must-not-fire control: a label that shares no prefix with any declared
    priority spelling is not a priority label at all, and must not be
    reported as an unrecognised one."""
    answer = _rank(["bug"], MAINTAINER)
    assert answer["why"] is None, answer


def test_no_common_prefix_means_no_unrecognised_detection():
    """If the declared spellings share no prefix, guessing that some other
    label is an unrecognised priority would be the same hardcoded-fact
    failure this module already refuses elsewhere -- there is no signal, so
    none is invented."""
    declared_no_prefix = {"priority": ["urgent", "later"], "filed_by_loop": LOOP}
    answer = dispatch_rank.rank(["priority-critical"], declared_no_prefix, "maintainer")
    assert answer["why"] is None, answer


def test_a_short_shared_prefix_does_not_flag_an_unrelated_word_838():
    """#838. `os.path.commonprefix(['p1', 'p2', 'p3'])` is `'p'`, one
    character -- so before the fix, `_band(['python', 'bug'], ['p1', 'p2',
    'p3'])` called `python` a probable typo of the declared spellings purely
    because it starts with the same letter. The bar: would this test still
    pass if `_band` did nothing? No -- the pre-fix code returns
    `('low', 'python')` here, which this asserts against directly."""
    declared_short = {"priority": ["p1", "p2", "p3"], "filed_by_loop": LOOP}
    answer = dispatch_rank.rank(["python", "bug"], declared_short, "maintainer")
    assert answer["why"] is None, answer


def test_a_plausible_typo_is_still_caught_with_short_spellings_838():
    """Must-fire control paired with the must-not-fire case above, in the
    same short-spelling fixture: a label that really does look like a typo
    of one of the declared short spellings -- same prefix, comparable
    length -- must still be reported. Otherwise the fix for #838 could have
    been 'stop detecting typos at all', which would silently regress #826."""
    declared_short = {"priority": ["p1", "p2", "p3"], "filed_by_loop": LOOP}
    answer = dispatch_rank.rank(["p9"], declared_short, "maintainer")
    assert answer["why"] is not None and "p9" in answer["why"], answer


def test_a_single_declared_spelling_still_catches_a_close_typo_838():
    """Found by review (#834/#838 self-review round): a repository declaring
    exactly one priority spelling has a prefix equal to that whole spelling,
    so its own suffix length is 0. An earlier version of the fix compared a
    candidate's suffix length against the *longest* declared suffix, which
    for a single spelling is that same 0 -- and 0 can never be exceeded by
    any candidate that reaches this code (every candidate here already has
    a non-empty suffix, by construction), so typo detection was silently
    disabled for every single-spelling repository. This is a must-fire
    control: a close typo of the one declared spelling must still be
    reported."""
    declared_one = {"priority": ["urgent"], "filed_by_loop": LOOP}
    answer = dispatch_rank.rank(["urgentx"], declared_one, "maintainer")
    assert answer["why"] is not None and "urgentx" in answer["why"], answer


def test_a_single_declared_spelling_does_not_flag_an_implausible_suffix_838():
    """Must-not-fire control paired with the test above, in the same
    single-spelling fixture: a label that shares the prefix but is far
    longer than the one declared spelling is not a plausible typo of it,
    and must not be reported -- otherwise the fix for the case above could
    have been 'always flag anything sharing the prefix', which is #838 all
    over again with an even shorter effective floor."""
    declared_one = {"priority": ["urgent"], "filed_by_loop": LOOP}
    answer = dispatch_rank.rank(["urgentlyneeded"], declared_one, "maintainer")
    assert answer["why"] is None, answer


def test_mixed_length_declared_spellings_do_not_let_a_short_one_over_match_838():
    """Found by review: comparing a candidate's suffix length against the
    *longest* declared suffix (rather than the nearest one) reintroduces
    #838's own defect the moment the declared spellings vary in length. With
    `p1` (suffix length 1) declared alongside a much longer spelling, the
    long spelling's suffix used to set a floor generous enough to let
    `python` back in -- the exact false positive #838 was filed against,
    now reachable through a second declared spelling rather than a short
    one alone."""
    declared_mixed = {
        "priority": ["p1", "priority-extremely-long-spelling-here"],
        "filed_by_loop": LOOP,
    }
    answer = dispatch_rank.rank(["python", "bug"], declared_mixed, "maintainer")
    assert answer["why"] is None, answer


def _run_main(issues, capsys, monkeypatch, declared=None):
    """`render_board_receipt` over a board, returning `(exit_code, stdout)`.

    #1069: this used to reach `dispatch_rank.py`'s own CLI (`main([])` over
    stdin) on purpose -- the two reviewers of #826 both found that `rank()`
    computed the unrecognised priority signal and `main()` then dropped it,
    so a test that only calls `rank()` cannot see the seam. `main()` is gone
    now (folded into `select_issues.py --board`, #1069); this calls the
    library function the CLI used to wrap, `render_board_receipt`, which is
    the one place that seam still exists -- `capsys`/`monkeypatch` are kept
    as unused parameters so every call site below is untouched."""
    del capsys, monkeypatch
    # #993: a non-loop issue now needs a readable author association to rank
    # at all. Tests in this file that are not about the association axis
    # itself do not care which value it carries, only that ranking succeeds
    # -- so a caller-supplied `author_association` is respected and an
    # absent one defaults to "maintainer" here, in the test fixture only.
    issues = [dict(item) for item in issues]
    for item in issues:
        item.setdefault("author_association", "maintainer")
    out = dispatch_rank.render_board_receipt(
        issues, declared if declared is not None else DECLARED
    )
    return 0, out


def test_the_cli_receipt_names_an_unrecognised_priority_label(capsys, monkeypatch):
    """#826, found by review. The receipt a maintainer actually reads is
    `main()`'s stdout -- the documented invocation in
    `skills/manager/phases/dispatch.md` pipes a board through it. Computing
    the signal in `rank()` and printing nothing is this repository's own
    defect class moved one layer out: the typo and the silence render
    identically to the only surface anybody looks at."""
    code, out = _run_main(
        [{"number": 123, "labels": ["priority-critical"]}], capsys, monkeypatch
    )
    assert code == 0, out
    assert "#123" in out, out
    assert "priority-critical" in out, out


def test_the_cli_receipt_stays_quiet_for_a_genuinely_unprioritised_issue(
    capsys, monkeypatch
):
    """Paired must-not-fire control for the assertion above: the fix must
    add a line to the receipt only for the unrecognised case, not decorate
    every ordinary issue."""
    code, out = _run_main([{"number": 124, "labels": []}], capsys, monkeypatch)
    assert code == 0, out
    assert "#124" in out, out
    assert "--" not in out.split("\n")[0], out


def test_the_cli_still_distinguishes_could_not_rank_from_a_ranked_issue(
    capsys, monkeypatch
):
    """The `could-not-rank` branch already printed its `why` and must keep
    doing so -- the new `why` on a ranked line must not have merged the two
    renderings into one."""
    code, out = _run_main(
        [{"number": 125, "labels": []}],
        capsys,
        monkeypatch,
        declared={"priority": [], "filed_by_loop": LOOP},
    )
    assert "?" in out and "could not rank" in out, out
    assert code == 0, out


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
    issue is never read as the loop's own under the rule this same change
    introduces -- so the loop's own filings would outrank the maintainer's
    and every external report."""
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
    r"^\s*\|\s*(\d+)\s*\|\s*(external|maintainer|loop)\s*\|\s*([^|]+?)\s*\|\s*$",
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


def test_the_dispatch_phase_states_the_table_dispatch_rank_computes():
    """#825, updated for #993's nine-row table. The dispatch table is a
    transcription of `dispatch_rank.ROWS` -- the module is the source, the
    table is prose copied from it -- and a transcription that drifts from
    its source is exactly what this can catch and a reader skimming the
    table cannot.

    This replaces `test_the_spine_and_dispatch_state_the_same_order`, which
    asserted only that the words 'human' and 'loop' occur somewhere in two
    thousand-word documents -- true of nearly any edit to either file, so it
    could not fail for the defect it claimed to guard against.

    #960 moved which document holds the copy, not how many there are: the
    selection rules went from the spine into `phases/dispatch.md`, where a lane
    is assembled, so a session that never dispatches does not load them. The
    invariant this pair enforces is unchanged -- exactly one copy, in the
    loop's prose, naming the module -- and the direction of the pair is
    flipped to match. Asserting the old direction after the move would have
    been a guard measuring where the table used to be."""
    root = repo_root()
    dispatch = (root / "skills/manager/phases/dispatch.md").read_text(encoding="utf-8")
    rows = _extract_dispatch_table_rows(dispatch)
    assert len(rows) == len(dispatch_rank.ROWS), rows
    assert rows == dispatch_rank.ROWS, rows
    assert "dispatch_rank.py" in dispatch, (
        "the table no longer names the module that computes it, so the "
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
        "| 2 | external | high |\n"
        "| 3 | maintainer | high |\n"
        "| 4 | loop | high |\n"
        "| 5 | external | medium |\n"
        "| 6 | maintainer | medium |\n"
        "| 7 | loop | medium |\n"
        "| 8 | external | low, or no priority label |\n"
        "| 9 | maintainer | low, or no priority label |\n"
        "| 10 | loop | medium |\n"
    )
    rows = _extract_dispatch_table_rows(contradicting)
    assert len(rows) == len(dispatch_rank.ROWS), rows
    assert rows != dispatch_rank.ROWS, rows


def test_the_spine_points_at_the_table_rather_than_restating_it():
    """The design the issue found sound, with the two documents swapped by
    #960: one document carries the table and the other deliberately does not
    restate it (#673, #547 -- a second copy is the copy that drifts).
    Asserting that absence is the real regression to guard, not a parity check
    between two copies that were never meant to both exist.

    The spine must still send a reader to the file that has it: a spine that
    neither carries the table nor names where it lives is not a smaller spine,
    it is an order nothing states."""
    spine = repo_root().joinpath(*manager_docs.SPINE_REL).read_text(encoding="utf-8")
    rows = _extract_dispatch_table_rows(spine)
    assert not rows, (
        "the spine now carries its own copy of the dispatch table -- that "
        "recreates the drift #673/#547 exist to avoid; point at "
        "phases/dispatch.md instead of restating it: {}".format(rows)
    )
    assert "skills/manager/phases/dispatch.md" in spine, (
        "the spine must name the phase file that carries the dispatch order"
    )


def test_tick_md_states_the_lane_size_bound():
    """#799 item 3. The bound belongs where step 5 dispatches, not only in the
    phase file, because a session can reach the dispatch step holding the
    command and not the phase.

    #1037: step 5 moved out of commands/tick.md into its own phase file, read
    by a sub-manager rather than injected into the scheduler on every tick."""
    text = (repo_root() / "skills" / "manager" / "phases" / "tick-order.md").read_text(
        encoding="utf-8"
    )
    assert "never 4" in text or "never four" in text, (
        "skills/manager/phases/tick-order.md step 5 does not state the lane size bound"
    )


def test_the_prose_check_fires_on_a_silent_instruction():
    """Must-fire control for `test_every_filing_instruction_names_the_label`.
    Without it, that assertion also passes when the label spelling changes and
    nothing matches any more."""
    silent = "Run `gh-issue-create:@FILE` to file the finding."
    assert "filed_by_loop" not in silent and "filed-by-loop" not in silent


# ---------------------------------------------------------- #834: encoding


def _select_issues_script():
    # #1069: dispatch_rank.py's own CLI (and the #834 stdin/stdout encoding
    # fixes that lived in it) is gone -- folded into select_issues.py's
    # `--board` mode, which carries the identical `_reconfigure_streams`/
    # `_read_stdin_json` guards. Every test below drives that script with
    # `--board` instead.
    return str(repo_root() / "scripts" / "select_issues.py")


def test_stdout_survives_an_unencodable_character_834():
    """#834's stdout half. A console codepage that cannot represent a
    character in an issue's label used to crash this CLI with
    `UnicodeEncodeError` at the `print` -- after the ranking had already
    been computed. `tests/test_dispatch_order_798_799.py`'s existing tests
    drive `main()` in-process with a monkeypatched `StringIO`, whose stdout
    is always UTF-8 capable and can never exercise this: the bar is 'would
    this test still pass if the code did nothing', and an in-process test
    would. This one goes through a real subprocess with
    `PYTHONIOENCODING=ascii`, which is what a narrow console codepage looks
    like from Python's point of view, and puts a non-ASCII character in a
    label that lands in the printed 'unrecognised priority' receipt."""
    payload = json.dumps(
        {
            "declared": DECLARED,
            "issues": [{"number": 1, "labels": ["priority-héllo"]}],
        }
    )
    env = dict(os.environ, PYTHONIOENCODING="ascii")
    result = subprocess.run(
        [sys.executable, _select_issues_script(), "--board"],
        input=payload.encode("utf-8"),
        capture_output=True,
        env=env,
    )
    stderr = result.stderr.decode("utf-8", errors="backslashreplace")
    assert result.returncode == 0, (result.returncode, stderr)
    assert "UnicodeEncodeError" not in stderr, stderr


def test_stdout_crashes_without_the_fix_positive_control_834():
    """Positive control for the test above, run against the file as it
    stood before #834's fix -- the case that establishes the harness can
    actually see the crash it is meant to catch, rather than a subprocess
    invocation that would pass even with the guard removed. Skips rather
    than asserting on a platform where `ascii` cannot be forced onto
    stdout, instead of silently passing."""
    script = repo_root() / "scripts" / "select_issues.py"
    original = script.read_text(encoding="utf-8")
    if "backslashreplace" not in original:
        pytest.skip("fix already absent -- nothing to prove a control against")
    broken = original.replace(
        "def _reconfigure_streams():\n"
        "    for stream in (sys.stdout, sys.stderr):\n"
        "        try:\n"
        '            stream.reconfigure(errors="backslashreplace")\n'
        "        except (AttributeError, ValueError):  # pragma: no cover - very old Python\n"
        "            pass\n",
        "def _reconfigure_streams():\n    pass\n",
        1,
    )
    assert broken != original, "the reconfigure block was not found to remove"
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(broken)
        broken_path = fh.name
    try:
        payload = json.dumps(
            {
                "declared": DECLARED,
                "issues": [{"number": 1, "labels": ["priority-héllo"]}],
            }
        )
        env = dict(
            os.environ,
            PYTHONIOENCODING="ascii",
            PYTHONPATH=str(repo_root() / "scripts"),
        )
        result = subprocess.run(
            [sys.executable, broken_path, "--board"],
            input=payload.encode("utf-8"),
            capture_output=True,
            env=env,
        )
        stderr = result.stderr.decode("utf-8", errors="backslashreplace")
        if result.returncode == 0 and "UnicodeEncodeError" not in stderr:
            pytest.skip(
                "this platform's ascii codec did not reproduce the crash -- "
                "UNTESTED here: the encode failure this control exists to show"
            )
        assert "UnicodeEncodeError" in stderr, (result.returncode, stderr)
    finally:
        os.unlink(broken_path)


def test_stdin_is_decoded_as_utf8_regardless_of_console_codepage_834():
    """#834's stdin half. `json.load(sys.stdin)` used to decode with
    whatever codepage the console reports. `UnicodeDecodeError` is a
    `ValueError`, so the existing `except ValueError` around the read
    caught it and told the caller 'stdin is not JSON' -- false: it was
    valid JSON, and the reader simply could not decode the bytes with the
    wrong codec. 'A' (U+00C1) UTF-8-encodes to the two bytes 0xC3 0x81, and
    0x81 is undefined in cp1252 -- decoding those bytes as cp1252 raises
    reliably, which is what makes this a real positive control rather than
    a guess at what might fail. Forcing UTF-8 on stdin regardless of the
    console codepage is the fix; this must decode cleanly under it."""
    payload = json.dumps(
        {
            "declared": DECLARED,
            "issues": [{"number": 1, "labels": ["priority-Á"]}],
        },
        ensure_ascii=False,
    )
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    result = subprocess.run(
        [sys.executable, _select_issues_script(), "--board"],
        input=payload.encode("utf-8"),
        capture_output=True,
        env=env,
    )
    out = result.stdout.decode("utf-8", errors="backslashreplace")
    assert result.returncode == 0, (result.returncode, out, result.stderr)
    assert "COULD NOT READ" not in out, out


def test_stdin_reads_as_malformed_without_the_fix_positive_control_834():
    """Positive control for the test above: with stdin decoded via the
    console codepage instead of UTF-8, valid UTF-8 JSON containing the same
    byte 0x81 that is undefined in cp1252 raises `UnicodeDecodeError`
    inside `json.load(sys.stdin)`, and the pre-fix `except ValueError` around
    it renders that as 'stdin is not JSON' -- proving the harness can see
    the exact defect #834 reports, not merely a plausible-sounding one."""
    script = repo_root() / "scripts" / "select_issues.py"
    original = script.read_text(encoding="utf-8")
    fixed_block = (
        "    try:\n"
        '        sys.stdin.reconfigure(encoding="utf-8")\n'
        "    except (AttributeError, ValueError):  # pragma: no cover - not a TextIOWrapper\n"
        "        pass\n"
        "    try:\n"
        "        return json.load(sys.stdin), None\n"
        "    except UnicodeDecodeError as exc:\n"
        "        return None, _could_not_select(\n"
        '            "stdin: could not be decoded as UTF-8 ({0})".format(exc)\n'
        "        )\n"
        "    except ValueError as exc:\n"
    )
    pre_fix_block = (
        "    try:\n"
        "        return json.load(sys.stdin), None\n"
        "    except ValueError as exc:\n"
    )
    assert fixed_block in original, "the fixed try/except block was not found to remove"
    broken = original.replace(fixed_block, pre_fix_block, 1)
    assert broken != original, "the stdin-reconfigure block was not found to remove"
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(broken)
        broken_path = fh.name
    try:
        payload = json.dumps(
            {
                "declared": DECLARED,
                "issues": [{"number": 1, "labels": ["priority-Á"]}],
            },
            ensure_ascii=False,
        )
        env = dict(
            os.environ,
            PYTHONIOENCODING="cp1252",
            PYTHONPATH=str(repo_root() / "scripts"),
        )
        result = subprocess.run(
            [sys.executable, broken_path, "--board"],
            input=payload.encode("utf-8"),
            capture_output=True,
            env=env,
        )
        out = result.stdout.decode("utf-8", errors="backslashreplace")
        if result.returncode != 2 or "COULD NOT READ" not in out:
            pytest.skip(
                "this platform's cp1252 decoding did not reproduce the "
                "defect -- UNTESTED here: the decode failure this control "
                "exists to show"
            )
        assert "not JSON" in out, out
    finally:
        os.unlink(broken_path)
