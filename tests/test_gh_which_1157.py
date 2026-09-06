"""#1157: seven call sites #1109 just taught to call `shutil.which("gh")`
with no `path=`, plus five pre-existing sites doing the identical thing for
`gh`/`git`, are all newly (or still) reachable by a `gh.cmd`/`git.cmd`
committed to the root of the repo being inspected. `shutil.which` inserts
`os.curdir` ahead of a real `PATH` entry on Windows whenever the queried
name has no directory component -- regardless of whether a `path=` argument
was supplied, which is why passing one is not the fix (see
`scripts/gh_which.py`'s own docstring for the mechanism).

The real Windows curdir-insertion code is gated on `sys.platform == "win32"`
and (on 3.12+) on `_winapi.NeedCurrentDirectoryForExePath`, neither of which
this suite can exercise directly on the platform running it. So the fixture
below stands in a fake, `shutil.which`-shaped resolver that reproduces the
one documented property that matters here: it always prefers a same-named
entry in the directory passed as `path[0]` (standing in for the implicit
cwd) over one further down the search path, REGARDLESS of what `path` it is
given -- exactly `shutil.which`'s real behaviour on Windows when `cmd` has
no directory component. `safe_which` must defeat that preference by never
handing the fake resolver a bare name; a real `shutil.which` receiving a
joined `directory/name` candidate takes the branch that skips the
insertion entirely (real stdlib code, not faked), so exercising the fake
resolver this way pins the actual mechanism `safe_which` relies on.

Every "must not prefer the cwd-shaped entry" case is paired with a "must
still resolve the real PATH entry" positive control in the same fixture,
per this repo's own rule that a check which only ever asserts absence
passes when nothing runs at all.
"""

import os
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gh_which  # noqa: E402


def _win_like_which_factory(cwd_dir, real_dir, name):
    """A `shutil.which(cmd, path=None)`-shaped fake that reproduces the one
    property under test: when `cmd` carries no directory component, it
    always resolves the `cwd_dir` copy first, no matter what `path` is
    passed in (mirroring the unconditional-on-3.9-3.11 / default-on-3.12+
    curdir insertion). When `cmd` DOES carry a directory component (the
    shape `safe_which` always constructs), it resolves within that
    directory only -- the real stdlib branch that never inserts curdir.
    """

    def fake_which(cmd, path=None):
        dirname, base = os.path.split(cmd)
        if not dirname:
            # No directory component: the vulnerable branch. The cwd-shaped
            # copy always wins here, regardless of `path`.
            cwd_candidate = os.path.join(cwd_dir, base)
            if os.path.exists(cwd_candidate):
                return cwd_candidate
            real_candidate = os.path.join(real_dir, base)
            return real_candidate if os.path.exists(real_candidate) else None
        # Directory component present: search only that directory, exactly
        # like the real `shutil.which`'s `if dirname: path = [dirname]`
        # branch -- no curdir insertion, ever.
        candidate = os.path.join(dirname, base)
        return candidate if os.path.exists(candidate) else None

    return fake_which


def test_safe_which_never_prefers_the_cwd_shaped_entry_over_real_path(
    monkeypatch, tmp_path
):
    cwd_dir = tmp_path / "repo_root"
    real_dir = tmp_path / "usr_local_bin"
    cwd_dir.mkdir()
    real_dir.mkdir()
    (cwd_dir / "gh.cmd").write_text("echo malicious\n")
    (real_dir / "gh.cmd").write_text("echo real gh\n")

    monkeypatch.setattr(
        gh_which.shutil, "which", _win_like_which_factory(cwd_dir, real_dir, "gh.cmd")
    )

    resolved = gh_which.safe_which("gh.cmd", path=str(real_dir))

    assert resolved == str(real_dir / "gh.cmd"), resolved
    assert cwd_dir.name not in resolved, resolved


def test_safe_which_positive_control_still_resolves_from_real_path(
    monkeypatch, tmp_path
):
    """Must-fire pairing for the assertion above: when the real PATH entry
    is the ONLY place `gh.cmd` exists, `safe_which` must still find it --
    proving the prior test passes because of the fix, not because nothing
    ever resolves."""
    empty_cwd = tmp_path / "empty_repo_root"
    real_dir = tmp_path / "usr_local_bin_2"
    empty_cwd.mkdir()
    real_dir.mkdir()
    (real_dir / "gh.cmd").write_text("echo real gh\n")

    monkeypatch.setattr(
        gh_which.shutil,
        "which",
        _win_like_which_factory(empty_cwd, real_dir, "gh.cmd"),
    )

    resolved = gh_which.safe_which("gh.cmd", path=str(real_dir))

    assert resolved == str(real_dir / "gh.cmd"), resolved


def test_safe_which_returns_none_when_nothing_resolves(monkeypatch, tmp_path):
    empty_dir = tmp_path / "nothing_here"
    empty_dir.mkdir()
    monkeypatch.setattr(gh_which.shutil, "which", lambda cmd, path=None: None)
    assert gh_which.safe_which("gh", path=str(empty_dir)) is None


def test_safe_which_uses_real_path_env_when_path_argument_omitted(
    monkeypatch, tmp_path
):
    real_dir = tmp_path / "on_the_real_path"
    real_dir.mkdir()
    (real_dir / "gh").write_text("#!/bin/sh\n")
    monkeypatch.setenv("PATH", str(real_dir))
    monkeypatch.setattr(
        gh_which.shutil,
        "which",
        _win_like_which_factory(tmp_path / "nonexistent_cwd", real_dir, "gh"),
    )
    resolved = gh_which.safe_which("gh")
    assert resolved == str(real_dir / "gh"), resolved


def test_safe_which_walks_past_empty_directories_to_a_later_path_entry(tmp_path):
    """#1157 self-review finding (Explore): every other test in this file
    calls `safe_which` with a single-directory `path`, so a regression that
    broke the `os.pathsep`-splitting loop entirely -- e.g. handing the whole
    joined `path` string to `shutil.which` as one candidate directory --
    would still pass every one of them. This exercises the REAL
    `shutil.which` (unpatched) against a genuine multi-entry `PATH`: two
    directories that do not contain the binary, then one that does,
    joined with `os.pathsep` exactly as a real `PATH` environment variable
    would be. `safe_which` must walk past the first two and resolve the
    third."""
    empty_one = tmp_path / "empty_one"
    empty_two = tmp_path / "empty_two"
    real_dir = tmp_path / "the_real_one"
    for directory in (empty_one, empty_two, real_dir):
        directory.mkdir()
    target = real_dir / "gh"
    target.write_text("#!/bin/sh\necho gh\n")
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    search_path = os.pathsep.join([str(empty_one), str(empty_two), str(real_dir)])
    resolved = gh_which.safe_which("gh", path=search_path)

    assert resolved == str(target), resolved


def test_safe_which_stops_at_the_first_real_path_entry_that_resolves(tmp_path):
    """Positive-control pairing for the walk above, in the other direction:
    when TWO real `PATH` entries both carry the binary, `safe_which` must
    return the FIRST one in `PATH` order -- the same precedence a real
    `PATH` search gives -- never the last one it happens to find."""
    first_dir = tmp_path / "first_on_path"
    second_dir = tmp_path / "second_on_path"
    for directory in (first_dir, second_dir):
        directory.mkdir()
    for directory in (first_dir, second_dir):
        candidate = directory / "gh"
        candidate.write_text("#!/bin/sh\necho gh\n")
        candidate.chmod(
            candidate.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
        )

    search_path = os.pathsep.join([str(first_dir), str(second_dir)])
    resolved = gh_which.safe_which("gh", path=search_path)

    assert resolved == str(first_dir / "gh"), resolved
