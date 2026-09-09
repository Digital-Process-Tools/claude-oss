"""#1270 -- `_BACKREF` false-positives on ordinary English near
"already"/"above"/"earlier"/"previously".

Found by an `oss:developer` lane (claude-supertool #2375) during self-review:
a reviewer's final message noted a tool "found already installed" in a
scratch venv -- nothing to do with a prior finding -- and `_BACKREF` matched
`found already`, classifying a fully-stated review as `referred-not-stated`.

Root cause: the pattern paired a report verb with a trailing direction word
("above"/"earlier"/"previously"/"already") up to three words apart, with no
requirement that the direction word actually CLOSE the sentence's gesture at
a genuine back-reference. Ordinary English uses the identical words to
continue the same predicate -- "found already installed", "noted above 90%",
"flagged an earlier draft", "identified previously unknown users" -- and in
every one of those a bare word or digit immediately follows the direction
word, where a genuine back-reference gesture ("reported above", "found
already", "noted previously") has nothing left to say and is followed only
by punctuation, whitespace-then-non-alphanumeric, or the end of the message.

Every "must not fire" case below is paired with a "must fire" case built from
the identical verb/direction-word pair, per CLAUDE.md's "a negative
assertion needs a positive control" rule -- a classifier that stopped
matching entirely would pass every case in the first list.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import review_return  # noqa: E402


def _classify(body):
    return review_return.classify("FINDINGS: 1\n\n1. " + body)


# -- must NOT fire: ordinary English near the trigger words -----------------


def test_found_already_installed_is_not_a_backref():
    """#1270's own reproduction, verbatim in shape."""
    verdict = _classify(
        "The venv tool was found already installed, which was surprising but harmless."
    )
    assert verdict["state"] == "states-findings", verdict


def test_noted_above_a_number_is_not_a_backref():
    verdict = _classify(
        "Coverage was noted above 90% for this module, which is healthy."
    )
    assert verdict["state"] == "states-findings", verdict


def test_flagged_an_earlier_draft_is_not_a_backref():
    verdict = _classify(
        "This flagged an earlier draft of the config that is no longer relevant."
    )
    assert verdict["state"] == "states-findings", verdict


def test_identified_previously_unknown_users_is_not_a_backref():
    verdict = _classify(
        "We identified previously unknown users in the fixture, unrelated "
        "to any prior review."
    )
    assert verdict["state"] == "states-findings", verdict


# -- must fire: genuine back-references, same verb/word pairs ---------------


def test_found_above_is_still_a_backref():
    """Positive control for the "found already installed" test above --
    same verb, a genuine gesture, must still be caught."""
    verdict = _classify("See the details found above; nothing new to add.")
    assert verdict["state"] == "referred-not-stated", verdict


def test_noted_above_at_a_clause_boundary_is_still_a_backref():
    """Positive control for the "noted above 90%" test -- the identical
    verb/word pair, but the direction word actually closes the gesture."""
    verdict = _classify("This is noted above, and needs no repeating here.")
    assert verdict["state"] == "referred-not-stated", verdict


def test_flagged_earlier_at_a_clause_boundary_is_still_a_backref():
    """Positive control for the "flagged an earlier draft" test -- the
    identical verb/word pair, but the direction word closes the gesture
    (a comma follows) instead of introducing a noun ("an earlier draft")."""
    verdict = _classify("This was flagged earlier, so no need to repeat it.")
    assert verdict["state"] == "referred-not-stated", verdict


def test_identified_previously_at_a_clause_boundary_is_still_a_backref():
    """Positive control for the "identified previously unknown users" test."""
    verdict = _classify("This bug was identified previously.")
    assert verdict["state"] == "referred-not-stated", verdict


def test_found_already_at_a_clause_boundary_is_still_a_backref():
    """Positive control proving "already" itself is not disabled outright --
    only the case where a bare word or digit immediately follows it."""
    verdict = _classify("This was found already, in the earlier pass.")
    assert verdict["state"] == "referred-not-stated", verdict


def test_reported_above_continuing_into_its_own_clause_is_still_a_backref():
    """#1327: a genuine back-reference gesture followed by a continuing
    clause ("reported above in section 2") was swallowed by the same
    lookahead that correctly refuses "noted above 90%" -- both have a bare
    word immediately after the direction word, but only one is ordinary
    English continuing the SAME predicate. Every positive control above
    ends its gesture on a comma, semicolon or period; none covers a
    gesture that continues into its own clause. Losing this case is the
    direction that silently DROPS a finding, which is worse than
    over-signalling one (the issue's own stated priority)."""
    verdict = _classify("This was reported above in section 2 of the review.")
    assert verdict["state"] == "referred-not-stated", verdict


def test_noted_previously_in_this_review_is_still_a_backref():
    """The issue's second worked example of the same continuing-clause
    shape, with a different verb/direction-word pair."""
    verdict = _classify("This bug was noted previously in this review.")
    assert verdict["state"] == "referred-not-stated", verdict
