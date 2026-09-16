"""#1552: `commands/run/curate.md` opened a pull request every pass but never
said which branch of `pr_body.closes`'s three states its own payload is in.
A curate pass consumes fragments -- provenance, never subject -- so its PR
closes nothing by construction, every time. Without a stated convention, the
report-schema guard refuses the payload (no working `Closes #N`) and the pass
stops to ask a maintainer mid-pass -- the same human-in-the-loop failure
#1443's "the PR is the review" premise exists to remove.

The fix states the convention in `curate.md` itself, right beside the
existing `curate/<UTC timestamp>` branch-naming paragraph: set `no_close =
true` at the payload's top level, and say `Part of #N` in the body rather
than a closing keyword, if provenance is wanted visible.

Content-invariant checks, the same `_collapse` + substring pattern
`tests/test_curate_pr_never_auto_merge_1467.py` already uses over this file.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE = REPO_ROOT / "commands" / "run" / "curate.md"


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _curate_text():
    return CURATE.read_text(encoding="utf-8")


def test_curate_md_states_no_close_true():
    collapsed = _collapse(_curate_text())
    assert "no_close = true" in collapsed or "no_close=true" in collapsed, (
        "curate.md never states the no_close = true payload convention its "
        "own pull request has to carry -- without it, the report-schema "
        "guard refuses the payload and the pass stops to ask a maintainer"
    )


def test_curate_md_says_every_curate_pr_closes_nothing_by_construction():
    collapsed = _collapse(_curate_text())
    assert re.search(
        r"curate (pull request|pr).{0,60}closes nothing", collapsed, re.IGNORECASE
    ), (
        "curate.md does not say a curate PR closes nothing BY CONSTRUCTION -- "
        "without the 'every time' framing this reads as an edge case rather "
        "than the ordinary shape of every curate pass's own payload"
    )


def test_curate_md_says_issue_numbers_in_fragment_filenames_are_provenance():
    collapsed = _collapse(_curate_text())
    assert "provenance" in collapsed, (
        "curate.md does not say the issue numbers in a fragment's own "
        "filename are provenance rather than the subject of this pass -- "
        "without that distinction, Closes #N against one of them looks like "
        "the obviously right choice instead of the wrong one"
    )


def test_curate_md_names_part_of_n_for_visible_provenance():
    collapsed = _collapse(_curate_text())
    assert "Part of #N" in collapsed, (
        "curate.md never names the Part of #N phrasing for citing "
        "provenance without triggering a closing keyword"
    )


# Positive control: the pre-#1552 shape states the branch-naming convention
# but says nothing about the payload's own closing behaviour.
PRE_1552 = (
    "A head branch matching `^curate/` is what `skills/manager/phases/merge.md` "
    "gates on"
)


def test_pre_1552_branch_naming_text_is_still_present_as_context():
    assert PRE_1552 in _collapse(_curate_text())
