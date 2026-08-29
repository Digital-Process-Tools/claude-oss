"""#656: `bash-check-launcher` and `actionlint` are path-anchored globs, and

a leading literal in an fnmatch pattern is not crossed by `*` the way a
suffix glob (`*.sh`, `*.py`) is. `_match_glob` in claude-supertool is plain
`fnmatch` on whatever raw string `_OP_TARGETS[op](parts)` extracted -- the op
argument exactly as the caller typed it, never normalized against the repo
root or the caller's cwd. So `"bin/oss-workspace"` matches a caller who typed
the canonical relative spelling and misses one who typed `./bin/oss-workspace`
or an absolute path -- the two spellings an agent working inside a worktree is
most likely to produce, and the file it fails to guard is the one #588 broke.

Read directly (`_supertool.py:322`, `_supertool.py:21259-21266`,
`_supertool.py:24013-24024`): no normalization step exists anywhere between
extracting the op's path argument and calling `_match_glob`. Every documented
`"match"` example in claude-supertool's own `docs/validators.md` is an
unanchored extension glob (`*.json`, `*.php`, `*.{py,php,js,ts,jsx,tsx}`) --
never a path-anchored literal -- which is consistent with `match` being
matched against the raw, un-normalized op argument by design: the burden of
covering spelling variance sits with the config author, not with supertool
normalizing paths before the match. So the fix in #656 belongs here, in this
repo's own `.supertool.json`, not upstream in `_match_glob`.

This is measured against the REAL matcher, not a reimplementation of it: the
two spellings this repo can be edited under (`./bin/oss-workspace`, and the
absolute worktree path) are false negatives against unmodified
`_match_glob`/`_applicable_validators`, called directly out of the installed
supertool checkout resolved off `PATH`. Where that checkout cannot be found
(any machine without a local claude-supertool clone -- ordinary in CI, which
never checks it out), the real-matcher assertions skip loudly rather than
falling back to a hand-rolled fnmatch stand-in, which would measure the copy
and not the dependency.
"""

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".supertool.json"


def _load_real_matcher():
    """Locate and import claude-supertool's own `_supertool.py`, the module

    `supertool` on PATH is a symlink into. Returns None (never raises) when
    it cannot be found -- that is a real "could not look" state, distinct
    from "looked and it matched", and callers must skip loudly on it rather
    than substitute a reimplementation.
    """
    exe = shutil.which("supertool")
    if not exe:
        return None
    target = Path(os.path.realpath(exe))
    core = target.parent / "_supertool.py"
    if not core.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_supertool_656", core)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    if not hasattr(module, "_match_glob"):
        return None
    return module


REAL_MATCHER = _load_real_matcher()

SKIP_REASON = (
    "no claude-supertool checkout found off PATH's `supertool` symlink -- "
    "cannot reach the real _match_glob, and a hand-rolled fnmatch stand-in "
    "would measure the copy rather than the dependency; untested here"
)

#: Three spellings a caller working inside a worktree can type for the same
#: file. `abs` is built at collection time from this repo's own root, since
#: the real absolute path is what an agent actually produces, not a fixture
#: string.
SPELLINGS = {
    "bin/oss-workspace": {
        "rel": "bin/oss-workspace",
        "dot_rel": "./bin/oss-workspace",
        "abs": str(REPO_ROOT / "bin" / "oss-workspace"),
    },
    ".github/workflows/oss-changelog.yml": {
        "rel": ".github/workflows/oss-changelog.yml",
        "dot_rel": "./.github/workflows/oss-changelog.yml",
        "abs": str(REPO_ROOT / ".github" / "workflows" / "oss-changelog.yml"),
    },
}


def _load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _match(entry_name, target, spelling_key):
    """Whether the configured `match` for `entry_name` matches one spelling,

    read fresh from `.supertool.json` and run through the real matcher.
    """
    validators = _load_config()["validators"]
    pattern = validators[entry_name]["match"]
    path = SPELLINGS[target][spelling_key]
    return REAL_MATCHER._match_glob(path, pattern)


@pytest.mark.skipif(REAL_MATCHER is None, reason=SKIP_REASON)
@pytest.mark.parametrize(
    "entry_name,target",
    [
        ("bash-check-launcher", "bin/oss-workspace"),
        ("actionlint", ".github/workflows/oss-changelog.yml"),
    ],
)
def test_the_canonical_relative_spelling_still_matches(entry_name, target):
    """The must-fire positive control: the spelling that has always worked

    keeps working. Without this, a fix that over-corrects (e.g. a pattern
    that only matches the `./`-prefixed or absolute forms) would pass the
    two regression assertions below and still break every existing caller.
    """
    assert _match(entry_name, target, "rel") is True


@pytest.mark.skipif(REAL_MATCHER is None, reason=SKIP_REASON)
@pytest.mark.parametrize(
    "entry_name,target",
    [
        ("bash-check-launcher", "bin/oss-workspace"),
        ("actionlint", ".github/workflows/oss-changelog.yml"),
    ],
)
def test_the_dot_relative_spelling_matches(entry_name, target):
    """#656's first missed spelling: `./bin/oss-workspace`. This is RED

    against the unmodified `.supertool.json` -- a leading literal in an
    fnmatch pattern is not crossed by `*`, so `"bin/oss-workspace"` never
    matches a path prefixed `./`.
    """
    assert _match(entry_name, target, "dot_rel") is True


@pytest.mark.skipif(REAL_MATCHER is None, reason=SKIP_REASON)
@pytest.mark.parametrize(
    "entry_name,target",
    [
        ("bash-check-launcher", "bin/oss-workspace"),
        ("actionlint", ".github/workflows/oss-changelog.yml"),
    ],
)
def test_the_absolute_spelling_matches(entry_name, target):
    """#656's second missed spelling: an absolute path. RED against the

    unmodified config for the same reason as the `./`-prefixed case above.
    """
    assert _match(entry_name, target, "abs") is True


@pytest.mark.skipif(REAL_MATCHER is None, reason=SKIP_REASON)
def test_a_completely_unrelated_path_still_does_not_match():
    """Negative control for the fix itself: widening the two globs to cross

    `/` must not turn them into a match-everything pattern. A sibling file
    that merely ends the same way (`notbin/oss-workspace`) must stay clear
    of `bash-check-launcher`, and an unrelated top-level yml must stay clear
    of `actionlint`.
    """
    validators = _load_config()["validators"]
    assert REAL_MATCHER._match_glob(
        "notbin/oss-workspace", validators["bash-check-launcher"]["match"]
    ) is False
    assert REAL_MATCHER._match_glob(
        "CHANGELOG.yml", validators["actionlint"]["match"]
    ) is False
