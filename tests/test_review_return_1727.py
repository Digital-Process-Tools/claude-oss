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
every back-reference the message carries sits inside the paragraph span of an
already-enumerated block -- confined to material the message demonstrably
does carry.

**The first draft of this fix checked only position** ("at or after the
first enumerated block's own start"), and self-review falsified it with two
reproductions: an unrelated trailing section inflating the block count past
what a real gesture should be shielded by, and a message enumerating exactly
`claimed` findings followed by a *separate paragraph* announcing an
undisclosed extra issue. Both are #392's own class, reopened. The fix checks
each block's own paragraph *span* (`_block_span` -- up to the next marker or
the next blank line) instead of a bare position bound; both reproductions are
pinned below as must-fire regressions.

Every "must fire" case here has a "must not fire" sibling in the same file,
per CLAUDE.md's own rule: a genuine dangling gesture (#392's own shape, one
past a block-count inflation, or one in its own trailing paragraph) must
still foreclose the good verdict, and only a gesture nested inside an
already-enumerated block's own span may not.
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


def test_a_backref_on_a_continuation_line_of_the_same_block_is_confined():
    """A genuine multi-line finding: the aside sits on a continuation line of
    the same block, with no blank line and no new marker between it and the
    block it continues -- still inside that block's own span."""
    message = """FINDINGS: 2

1. scripts/a.py:10 -- the retry loop is unbounded.
   As shown above in the diff, this repeats an old pattern.
2. scripts/b.py:20 -- the timeout default is never read from config.
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


def test_a_trailing_backref_after_the_last_block_still_forecloses():
    """A gesture in its own paragraph, past a blank line after the last
    enumerated block, is outside every block's own span -- a closing remark
    that reads exactly like a pointer at something not actually restated, so
    this must still foreclose. (First draft of this fix shielded this case
    purely because it sits after the first block's own start position --
    self-review finding, corrected by checking spans instead of a bare
    position bound.)"""
    message = """FINDINGS: 2

1. scripts/a.py:10 -- off-by-one.
2. scripts/b.py:20 -- unbounded retry.

Both mirror the pattern noted earlier in this review.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "referred-not-stated", verdict
    assert verdict["state"] != "states-findings"


def test_block_count_inflation_does_not_shield_a_dangling_gesture():
    """Self-review reproduction A: a claimed count of 1, a genuinely stated
    finding, and then an unrelated trailing section ("Files checked" plus a
    bullet list) that inflates the block count well past `claimed` -- with a
    dangling gesture positioned after all of it. The inflation must not
    manufacture room for a gesture that points at nothing the message
    actually carries."""
    message = """FINDINGS: 1

1. a.py -- bug.

## Files checked
- a.py
- b.py

As shown above, nothing else touched.
"""
    verdict = review_return.classify(message)
    assert verdict["state"] == "referred-not-stated", verdict
    assert verdict["state"] != "states-findings"


def test_exact_enumeration_with_a_dangling_trailing_paragraph_still_forecloses():
    """Self-review reproduction B: `claimed` matches the block count exactly
    (no inflation needed at all), and the message still announces an
    undisclosed extra issue in its own trailing paragraph -- the shape this
    whole module exists to catch, and no different for arriving after two
    real findings instead of zero."""
    message = """FINDINGS: 2

1. scripts/a.py -- real finding one.
2. scripts/b.py -- real finding two.

There is also a third issue, as noted earlier in this review, not detailed here.
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
