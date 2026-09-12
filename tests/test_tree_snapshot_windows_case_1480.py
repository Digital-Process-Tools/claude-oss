"""#1480 (finding 2): `tree_snapshot._root_relative_path` did a
case-sensitive string-prefix compare between `--before`'s recorded root and
the live root -- reasoned, not observed on a real Windows box, to
mis-resolve when the drive-letter case (or a short-name spelling) differs
between the two, since Windows' own filesystem is case-insensitive but
nothing in this comparison ever folded case to match that. The confirmed
half here is the mechanism: `_root_relative_path` is a pure string function
with no OS call in it, so the exact defect is reproducible on any host by
constructing the two spellings directly and calling it -- what is NOT
independently confirmed (no Windows host was available) is that git or
Python actually hands this module two differently-cased spellings of the
same root in practice; that half stays reasoned, per this repo's own
`platform-controls` convention for a claim that cannot be run here.

Fixed defensively: `_platform_path_key` case-folds both sides of the
compare, but ONLY when `sys.platform` reports Windows -- `sys.platform` is
read fresh on every call rather than cached, so a test can monkeypatch it
and exercise the Windows branch on any host without needing one. A POSIX
filesystem is not guaranteed case-insensitive (ext4, most Linux setups
are case-sensitive), so folding case unconditionally would make two
genuinely different paths compare equal -- the paired must-not-fire case
below proves the POSIX branch is untouched.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tree_snapshot  # noqa: E402


def test_windows_drive_letter_case_mismatch_still_resolves(monkeypatch):
    """Must fire: on a platform tree_snapshot believes is Windows, a root
    recorded with a lowercase drive letter must still match a live path
    using an uppercase one (and vice versa) -- the exact shape a real
    Windows checkout can hand this module from two different call sites
    (one from `git rev-parse`, one from a caller-supplied `--root`)."""
    monkeypatch.setattr(tree_snapshot.sys, "platform", "win32")

    root = "c:/Users/dev/repo"
    path = "C:/Users/dev/repo/scripts/foo.py"

    assert tree_snapshot._root_relative_path(path, root) == "scripts/foo.py"


def test_windows_component_case_mismatch_still_resolves(monkeypatch):
    """Must fire, the other half of the same shape: a case difference
    inside a path component (not only the drive letter) must also resolve
    on the Windows branch -- the short-name-spelling case the issue names."""
    monkeypatch.setattr(tree_snapshot.sys, "platform", "win32")

    root = "C:/Users/Dev/Repo"
    path = "C:/users/dev/repo/scripts/foo.py"

    assert tree_snapshot._root_relative_path(path, root) == "scripts/foo.py"


def test_posix_case_mismatch_still_does_not_resolve(monkeypatch):
    """Must-not-fire control, the same fixture family: on a platform
    tree_snapshot does not believe is Windows, a case difference must NOT
    be folded away -- a POSIX filesystem is not guaranteed
    case-insensitive, and two differently-cased paths there are not
    necessarily the same file. Proves the fix is scoped to the Windows
    branch rather than folding case everywhere."""
    monkeypatch.setattr(tree_snapshot.sys, "platform", "linux")

    root = "/home/dev/repo"
    path = "/home/DEV/repo/scripts/foo.py"

    assert tree_snapshot._root_relative_path(path, root) is None


def test_posix_matching_case_still_resolves(monkeypatch):
    """Positive control for the POSIX branch: identical case, no folding
    needed, still resolves exactly as before this fix."""
    monkeypatch.setattr(tree_snapshot.sys, "platform", "linux")

    root = "/home/dev/repo"
    path = "/home/dev/repo/scripts/foo.py"

    assert tree_snapshot._root_relative_path(path, root) == "scripts/foo.py"
