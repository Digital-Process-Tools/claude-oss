"""`_expected_watch_name` must carry oss_config's refusal, not only its fold (#653).

`oss_config.watch_channel_name` routes a candidate `repo` through `repo_problem`
*before* folding it into a channel name -- that ordering is the entire point of
the comment above `WATCH_NAME_UNSAFE_RE` in `oss_config.py`, which argues the
result "can never be `.` or `..` exactly" because a refused value never reaches
the fold at all. `statusline._expected_watch_name` used to skip straight to the
fold, so `'..'` and `'../../etc'` -- both refused by `oss_config` -- still
produced a channel name from the copy.

`tests/test_statusline_channel_613.py::test_expected_watch_name_matches_oss_configs_own_derivation`
only ever fed both functions slugs that `oss_config` accepts, so it could not
have caught this: agreement was guaranteed on that fixture regardless of
whether the refusal travelled. This file adds the positive control that issue
requires -- a slug `oss_config` rejects, paired with one it accepts, exercised
through the same assertion.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402
import oss_config  # noqa: E402


REFUSED_SLUGS = ("..", "../../etc", ".", "no-slash-at-all", "too/many/slashes")
ACCEPTED_SLUGS = ("owner/name", "Digital-Process-Tools/claude-oss")


def test_expected_watch_name_agrees_with_oss_config_on_refused_slugs():
    """The positive control #653 asks for: slugs oss_config REJECTS.

    Before the fix, `oss_config.watch_channel_name('..')` returns
    `(None, "repo: expected 'owner/name', got '..'")` while
    `statusline._expected_watch_name('..')` returns `'..'` -- the fold
    travelled to the copy without the refusal in front of it. Both must
    now return `None` for a slug oss_config refuses.
    """
    for repo in REFUSED_SLUGS:
        expected, problem = oss_config.watch_channel_name(repo)
        assert problem is not None, repo
        assert expected is None, repo
        assert statusline._expected_watch_name(repo) is None, repo


def test_expected_watch_name_still_agrees_with_oss_config_on_accepted_slugs():
    """The must-fire half of the same fixture -- accepted slugs must still fold."""
    for repo in ACCEPTED_SLUGS:
        expected, problem = oss_config.watch_channel_name(repo)
        assert problem is None, repo
        assert statusline._expected_watch_name(repo) == expected


# ------------------------------------------------------------- _REPO_RE pin (review)
#
# A maintainer review of this issue's own fix found the gap one level up: the two
# fixture lists above pin AGREEMENT on a fixed set of slugs, but nothing pins the
# PATTERN each copy is built from. If `oss_config.REPO_RE` is ever tightened or
# loosened, `statusline._REPO_RE` silently stops agreeing with it, and the tests
# above keep passing regardless -- they exercise statusline against a hardcoded
# slug list, not against oss_config's current definition. That is #653 restated
# one level up: the VALUE travelled (both copies fold and refuse today), the thing
# that keeps it correct did not.
#
# `tests/test_supertool_rule_sync_577.py` is this repository's own shape for
# exactly this problem -- two copies of one fact that must not diverge, pinned by
# a direct comparison, with a control proving the comparison actually catches a
# one-sided edit and does not also fire on an edit made identically to both.
# #577's own reasoning for a comparison test over derivation applies verbatim: a
# comparison test costs one file and answers the same question a build-time
# derivation would, without changing how either module is assembled.
#
# Importing `oss_config` here, in the test, is not the vendoring violation --
# `scripts/statusline.py` itself still imports nothing (verified above by every
# other test in this file exercising it as a standalone module). The constraint
# is on the shipped module, not on what a test may reach for to check it.


def _patterns_match(a, b):
    return a == b


def test_repo_re_pattern_matches_oss_configs_own_pattern():
    """The pin itself: the two `.pattern` strings, not just their behaviour on a
    fixed slug list, must be identical."""
    assert _patterns_match(statusline._REPO_RE.pattern, oss_config.REPO_RE.pattern), (
        "scripts/statusline.py's _REPO_RE and scripts/oss_config.py's REPO_RE have "
        "diverged -- _REPO_RE is the standalone-vendored copy statusline.py must "
        "agree with to keep the #653 refusal correct, and nothing else pins them "
        "together (#653 review)"
    )


def test_control_an_edit_to_both_patterns_the_same_way_still_matches():
    """Half of the positive control, driven against synthetic patterns so it does
    not depend on today's actual regex text (#577's own shape)."""
    a = r"\A[^/\s]+/[^/\s]+\Z"
    b = r"\A[^/\s]+/[^/\s]+\Z"
    assert _patterns_match(a, b)


def test_control_an_edit_to_exactly_one_pattern_is_caught():
    """The other half: a one-sided tightening or loosening must be caught, not
    silently pass because the comparison itself is vacuous."""
    a = r"\A[^/\s]+/[^/\s]+\Z"
    b = r"\A[^/\s]+/[^/\s]+/[^/\s]+\Z"  # tightened to require two slashes
    assert not _patterns_match(a, b)
