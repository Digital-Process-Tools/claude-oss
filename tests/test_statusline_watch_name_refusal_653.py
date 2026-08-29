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
