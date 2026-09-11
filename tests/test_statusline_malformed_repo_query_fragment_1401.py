"""#1401: `_malformed_repo`'s `_REPO_RE` allows `?` and `#` inside a repo
segment -- both legal to that regex, both able to truncate or redirect the
`gh api repos/{repo}/...` path `_malformed_repo`'s own callers build by
plain string substitution (never URL-encoded). `_BRANCH_UNSAFE_RE` already
refuses `?` for `branch` for the identical reason (#1035); this closes the
same gap on `repo`, plus `#`, which that regex never checked either.

Must-fire (`?`, `#`) paired with must-not-fire controls (a well-formed slug,
and a slug carrying two adjacent dots that are not a traversal segment) in
the same fixture, per this repo's own "pair every must-not-fire with a
must-fire" convention.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def test_query_string_in_repo_is_malformed():
    assert statusline._malformed_repo("o/n?x") is True


def test_fragment_in_repo_is_malformed():
    assert statusline._malformed_repo("o/n#x") is True


def test_ordinary_slug_is_not_malformed():
    """Must-not-fire control: a real, well-formed slug must still pass."""
    assert statusline._malformed_repo("owner/name") is False


def test_adjacent_dots_within_a_segment_are_not_a_traversal():
    """Must-not-fire control, carried over from the existing `..`-segment
    guard: a legitimate `owner/na..me` shape must not be caught by this
    new check either."""
    assert statusline._malformed_repo("owner/na..me") is False
