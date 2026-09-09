"""Classifying what arrived from outside the loop -- #1394.

Every negative assertion here (a case that must not be flagged inbound, must
not be refused, must not be green-and-mergeable) carries its positive control
(the neighbouring case that must) in the same fixture -- the same discipline
`test_gate3_disposition_1043.py` uses for gate 3's own decision function.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import inbound_triage  # noqa: E402


# --------------------------------------------------------------------- reasons


def test_all_six_documented_reasons_validate():
    for reason in inbound_triage.REFUSAL_REASONS:
        assert inbound_triage.validate_refusal_reason(reason)


def test_unrecognised_reason_is_rejected():
    """Negative case."""
    assert not inbound_triage.validate_refusal_reason("because")


def test_near_miss_casing_is_rejected_not_folded():
    """Positive control for the exact-match rule: `duplicate` itself must
    still pass, so the near-miss rejection above is not "everything fails"."""
    assert inbound_triage.validate_refusal_reason("duplicate")
    assert not inbound_triage.validate_refusal_reason("Duplicate")


def test_empty_reason_is_rejected():
    assert not inbound_triage.validate_refusal_reason("")


def test_cli_accepts_a_real_reason(capsys):
    rc = inbound_triage.main(["--check-refusal", "wontfix"])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_cli_refuses_an_unrecognised_reason(capsys):
    """Negative case, paired with the positive control immediately above."""
    rc = inbound_triage.main(["--check-refusal", "spam"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


# --------------------------------------------------------------- inbound issues


def test_issue_without_loop_label_is_inbound():
    declared = {"filed_by_loop": "filed-by-loop"}
    assert inbound_triage.is_inbound_issue(["priority-high"], declared) is True


def test_issue_with_loop_label_is_not_inbound():
    """Positive control: the loop's own filing must read False, not True."""
    declared = {"filed_by_loop": "filed-by-loop"}
    assert (
        inbound_triage.is_inbound_issue(["filed-by-loop", "priority-high"], declared)
        is False
    )


def test_undeclared_loop_label_is_unknown_not_false():
    """An absence produced by the config (no filed_by_loop declared) must
    never render the same as a measured False."""
    assert inbound_triage.is_inbound_issue(["priority-high"], {}) is None
    assert inbound_triage.is_inbound_issue(["priority-high"], None) is None


# ------------------------------------------------------------------- pull requests


def test_maintainer_pr_is_not_inbound():
    pr = {"author_association": "MEMBER", "ci_state": "green", "mergeable": True}
    assert inbound_triage.classify_pr(pr) == "not-inbound"


def test_external_pr_green_and_mergeable_is_green_and_mergeable():
    pr = {"author_association": "CONTRIBUTOR", "ci_state": "green", "mergeable": True}
    assert inbound_triage.classify_pr(pr) == "green-and-mergeable"


def test_external_pr_red_needs_answer():
    """Negative case for green-and-mergeable, paired with the positive control above."""
    pr = {"author_association": "CONTRIBUTOR", "ci_state": "red", "mergeable": True}
    assert inbound_triage.classify_pr(pr) == "needs-answer"


def test_external_pr_green_but_not_mergeable_needs_answer():
    pr = {"author_association": "NONE", "ci_state": "green", "mergeable": False}
    assert inbound_triage.classify_pr(pr) == "needs-answer"


def test_pr_with_unrecognised_association_is_could_not_tell():
    pr = {"author_association": "MANNEQUIN", "ci_state": "green", "mergeable": True}
    assert inbound_triage.classify_pr(pr) == "could-not-tell"


def test_pr_accepts_already_translated_association():
    pr = {"author_association": "external", "ci_state": "green", "mergeable": True}
    assert inbound_triage.classify_pr(pr) == "green-and-mergeable"


# ----------------------------------------------------------------------- comments


def test_comment_after_watermark_from_outsider_needs_answer():
    comments = [
        {"created_at": "2026-09-09T10:00:00Z", "author_association": "CONTRIBUTOR"}
    ]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z"
    )
    assert result == comments


def test_comment_before_watermark_is_excluded():
    """Negative case for the same fixture shape as the positive control above."""
    comments = [
        {"created_at": "2026-09-01T10:00:00Z", "author_association": "CONTRIBUTOR"}
    ]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z"
    )
    assert result == []


def test_maintainer_comment_is_excluded():
    comments = [{"created_at": "2026-09-09T10:00:00Z", "author_association": "OWNER"}]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z"
    )
    assert result == []


def test_own_login_comment_is_excluded_by_author():
    comments = [
        {
            "created_at": "2026-09-09T10:00:00Z",
            "author": "our-bot",
            "author_association": "CONTRIBUTOR",
        }
    ]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z", own_login="our-bot"
    )
    assert result == []


def test_no_watermark_is_none_not_empty_list():
    """A watermark that was never established must not render the same as
    'compared, and nothing is new'."""
    comments = [
        {"created_at": "2026-09-09T10:00:00Z", "author_association": "CONTRIBUTOR"}
    ]
    assert inbound_triage.comments_needing_answer(comments, since_iso=None) is None
    assert inbound_triage.comments_needing_answer(comments, since_iso="") is None


def test_unclassifiable_author_is_included_not_dropped():
    """An author this module cannot classify must not be silently treated as
    ours -- dropping it would understate what is waiting on an answer."""
    comments = [
        {"created_at": "2026-09-09T10:00:00Z", "author_association": "MANNEQUIN"}
    ]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z"
    )
    assert result == comments


def test_maintainer_comment_excluded_even_with_own_login_and_different_author():
    """Self-review finding (#1394): both spawned reviewers independently found
    that passing `own_login` used to short-circuit the association check for
    any comment whose author differed from it -- so a human maintainer
    replying under their own account, not the bot's `own_login`, was reported
    as still needing an answer. Both filters must apply together."""
    comments = [
        {
            "created_at": "2026-09-09T10:00:00Z",
            "author": "the-human-maintainer",
            "author_association": "OWNER",
        }
    ]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z", own_login="oss-bot"
    )
    assert result == []


def test_external_comment_kept_with_own_login_and_different_author():
    """Positive control for the fix above: an external author who is neither
    `own_login` nor a maintainer association must still be kept."""
    comments = [
        {
            "created_at": "2026-09-09T10:00:00Z",
            "author": "some-outsider",
            "author_association": "CONTRIBUTOR",
        }
    ]
    result = inbound_triage.comments_needing_answer(
        comments, since_iso="2026-09-08T00:00:00Z", own_login="oss-bot"
    )
    assert result == comments


def test_comments_none_is_none_not_empty_list():
    """Self-review finding (audit spawn, #1394): `comments or []` used to fold
    'the fetch never ran' into the same `[]` a genuinely empty, successfully
    fetched list produces -- the same could-not-tell-versus-zero collapse
    `since_iso=None` is already guarded against, just on the other argument."""
    assert (
        inbound_triage.comments_needing_answer(None, since_iso="2026-09-08T00:00:00Z")
        is None
    )


def test_comments_empty_list_is_empty_list_not_none():
    """Positive control: a fetch that actually ran and found nothing must
    still render as a real, measured `[]`, not fold into the `None` above."""
    assert (
        inbound_triage.comments_needing_answer([], since_iso="2026-09-08T00:00:00Z")
        == []
    )
