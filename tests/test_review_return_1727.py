"""#1727: `review_return.classify` forecloses `states-findings` on a fully
enumerated `FINDINGS: N` message that also happens to use a back-reference
phrase ("shown above", "given ... earlier") somewhere inside one of the
already-stated blocks -- describing a detail of that finding, not pointing at
material the message does not carry. Three independently dispatched lanes in
one tick each reported the same false trigger.

#392's own defended shape is unchanged and stays a `referred-not-stated`: the
gesture there is a *preamble* sentence ("Findings reported above (3 total)")
sitting before the first counted marker, with the markers themselves an
unrelated trailing list (file names). What changes is only the case where
every back-reference the message carries sits at or after the first
enumerated block's own start -- confined to material the message
demonstrably does carry.

Every "must fire" case here has a "must not fire" sibling in the same file,
per CLAUDE.md's own rule: a genuine dangling gesture (#392's own shape, or one
that survives outside the enumerated region) must still foreclose the good
verdict, and only a gesture nested inside an already-enumerated block may not.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import review_return  # noqa: E402


# -- must not fire: the false positive #1727 reports -----------------------


def test_a_backref_inside_an_enumerated_block_does_not_foreclose_the_good_verdict():
    """The exact shape #1727 reports: full enumeration, and the only
    back-reference phrase in the message describes a detail already inside
    one of the counted blocks, not a pointer at missing content."""
    message = """FINDINGS: 2

1. scripts/a.py:10 -- the retry loop is unbounded; as shown above in the \
diff, the same call site had the identical bug in the previous revision.
2. scripts/b.py:20 -- the timeout default is never read from config.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "states-findings", verdict


def test_a_trailing_backref_after_the_last_block_does_not_foreclose_either():
    """A gesture after the last enumerated block is still inside the
    enumerated region by this function's own bar (at or after the first
    block's start) -- a closing remark about the findings just stated, not a
    pointer at something absent."""
    message = """FINDINGS: 2

1. scripts/a.py:10 -- off-by-one.
2. scripts/b.py:20 -- unbounded retry.

Both mirror the pattern noted earlier in this review.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "states-findings", verdict


# -- must fire: a real dangling gesture still forecloses --------------------


def test_a_backref_before_the_first_block_still_forecloses():
    """#392's own defended shape, restated with the gesture the same distance
    from the header but real block markers this time -- still decisive,
    because the gesture sits in the preamble, before any enumerated block."""
    message = """FINDINGS: 2

As shown above, both issues are the same root cause.

1. scripts/a.py:10 -- off-by-one.
2. scripts/b.py:20 -- unbounded retry.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "referred-not-stated", verdict
    assert verdict["state"] != "states-findings"


def test_one_unshielded_backref_among_several_still_forecloses():
    """Every back-reference must be confined, not merely one of several --
    a dangling gesture in the preamble, before the first enumerated block,
    must still be caught even when a second gesture later in the same
    message is safely nested inside a block."""
    message = """FINDINGS: 1

As noted earlier, this repeats.

1. scripts/a.py:10 -- as shown above, a genuine detail of the same bug.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "referred-not-stated", verdict
    assert verdict["state"] != "states-findings"


def test_a_backref_with_partial_enumeration_still_reports_the_gap():
    """The shielding rule only ever applies inside the `blocks >= claimed`
    branch -- a header claiming more than the message enumerates, with a
    gesture trailing it, must still report the gap rather than silently
    passing."""
    message = """FINDINGS: 3

1. scripts/a.py:10 -- one bug, as shown above in the diff.

Two more are noted earlier in this review.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "referred-not-stated", verdict
    assert verdict["stated_blocks"] < verdict["claimed"]


# -- #392's own pinned fixture, unchanged --------------------------------


def test_392_own_gesture_beats_trailing_bullet_list_is_unchanged():
    """Byte-for-byte the fixture `test_a_gesture_beats_a_trailing_bullet_list`
    in tests/test_review_return_392.py already pins -- the preamble-gesture
    shape must still be decisive after this fix."""
    message = """FINDINGS: 3

Findings reported above (3 total).

## Files checked
- fileA.py
- fileB.py
- fileC.py
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "referred-not-stated", verdict
    assert verdict["state"] != "states-findings"
