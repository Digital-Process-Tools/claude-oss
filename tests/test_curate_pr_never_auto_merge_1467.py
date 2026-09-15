"""#1467: `merge.md` had no arm for a loop-authored curate pull request, so
#1443's "the pull request is the review" premise -- `commands/run/curate.md`
opens one PR per pass and never asks a maintainer mid-pass -- had no reader.
Nothing distinguished that PR from any other loop-authored one: the same
account opens both, so `author_association` (the axis `inbound_triage.py`
already reads for an external contributor) cannot tell them apart on its own.

The fix: `commands/run/curate.md` cuts its branch as `curate/<timestamp>`
rather than the developer lane's `fix/{issue}`, and `merge.md` gains a
never-auto-merge row keyed on that head-branch prefix, with the same
held-for-the-maintainer treatment #1394 already gives an external
contributor's pull request.

These are content-invariant checks over the loop's own prose, the same shape
`tests/test_merge_and_fleet_content_445_446_448.py` already uses via
`manager_docs.ManagerLoop` -- the question is "does the loop say X", not
"does one file say X", so both checks read the whole assembled spine rather
than pinning line numbers in a single phase file.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_docs import ManagerLoop  # noqa: E402

SKILL = ManagerLoop(REPO_ROOT)
CURATE = REPO_ROOT / "commands" / "run" / "curate.md"


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _skill_text():
    return SKILL.read_text(encoding="utf-8")


def test_merge_never_auto_merges_a_curate_authored_pr():
    collapsed = _collapse(_skill_text())
    assert re.search(
        r"never\s+auto-merge.{0,200}?curate-authored", collapsed, re.IGNORECASE
    ), (
        "the loop's never-auto-merge list does not mention a curate-authored "
        "pull request -- #1467's whole fix is closing the gap between "
        "#1443's 'the PR is the review' premise and merge.md's silence"
    )


def test_merge_names_the_curate_branch_prefix_as_the_marker():
    collapsed = _collapse(_skill_text())
    assert "^curate/" in collapsed, (
        "merge.md never names the `^curate/` head-branch prefix it gates on -- "
        "without a stated marker, a curate-authored PR is indistinguishable "
        "from any other loop-authored PR at merge time"
    )


def test_merge_says_why_author_association_cannot_tell_it_apart():
    collapsed = _collapse(_skill_text())
    assert "author_association" in collapsed and "same account" in collapsed, (
        "merge.md's curate row does not say why the existing external-"
        "contributor classifier (author_association) cannot make this "
        "distinction on its own -- both PRs are opened by the same account"
    )


def test_curate_md_states_its_own_branch_marker_convention():
    text = CURATE.read_text(encoding="utf-8")
    collapsed = _collapse(text)
    assert "curate/<UTC timestamp>" in collapsed or "curate/" in collapsed, (
        "commands/run/curate.md never states the `curate/` branch-naming "
        "convention its own pull request has to carry"
    )
    assert "fix/{issue}" in collapsed, (
        "curate.md does not say its branch is never the developer lane's "
        "`fix/{issue}` pattern -- without the contrast, the convention "
        "reads as arbitrary rather than as the merge-time marker it is"
    )


def test_curate_md_points_at_merge_md_for_the_gate():
    text = CURATE.read_text(encoding="utf-8")
    assert "skills/manager/phases/merge.md" in text, (
        "curate.md's branch-naming paragraph does not point at merge.md, "
        "where the marker is actually read and acted on"
    )


# Positive control: the pre-#1467 shape names the PR-is-the-review premise
# but never a branch marker or a merge-time gate.
PRE_1467 = "The PR is the review: the maintainer reads it and can refuse any part of it"


def test_pre_1467_premise_text_is_still_present_as_context():
    """The premise #1467 builds a gate around was not deleted, only given a
    reader."""
    text = CURATE.read_text(encoding="utf-8")
    assert PRE_1467 in _collapse(text)
