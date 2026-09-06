"""#1157: seven call sites #1109 just taught to call `shutil.which("gh")`
with no `path=`, plus five pre-existing sites doing the identical thing for
`gh`/`git`, are all newly (or still) reachable by a `gh.cmd`/`git.cmd`
committed to the root of the repo being inspected. `shutil.which` inserts
`os.curdir` ahead of a real `PATH` entry on Windows whenever the queried
name has no directory component -- regardless of whether a `path=` argument
was supplied, which is why passing one is not the fix (see
`scripts/gh_which.py`'s own docstring for the mechanism).

A first version of `safe_which` (round 1) closed that gap by joining each
search directory onto the name before handing it to `shutil.which`, on the
theory that a candidate with a directory component always takes the branch
that skips curdir-insertion. That is true, but the round-1 fixtures in this
file pinned it against a HAND-WRITTEN FAKE `shutil.which`, never the real
one -- and the real one has a second, independent version-skew defect: on
Python 3.9-3.11, the directory-component branch is a single unextended
`_access_check` against the literal joined path, with NO re-application of
`PATHEXT` to the basename at all. Only 3.12+ splits the joined candidate
back apart and re-applies `PATHEXT`. Real CI on PR #1161 confirmed this
exactly: all four Windows legs (3.9-3.12) ran the round-1 fix, and the three
pre-3.12 legs failed at ~164-295 tests while 3.12 passed -- because the fake
`shutil.which` in this file's own fixtures could not distinguish "resolves
via the real stdlib's cross-version PATHEXT quirk" from "resolves because
the fix's own PATHEXT walk is correct". `safe_which` now performs the
directory-and-PATHEXT walk itself and never calls `shutil.which` at all, so
these fixtures exercise the real accessors (`os.path.exists`, `os.access`)
directly, with `sys.platform` monkeypatched to exercise the Windows-shaped
branch of `safe_which`'s OWN code on whatever platform this suite runs on --
never a synthetic resolver standing in for a wrong assumption about what
the real one does.

Fixtures use realistic, extensioned filenames (`gh.EXE`, `gh.CMD` --
see `_PINNED_PATHEXT` for why that case is load-bearing) rather
than a bare `gh` with no extension: a bare, unextended file is not
something Windows' own PATHEXT-driven resolution would ever treat as
resolvable in the first place (real `shutil.which`, `mode=os.F_OK |
os.X_OK`, only checks the bare name directly when it already ends with a
PATHEXT extension), so a fixture using one was pinning a fact about the
fixture, never about Windows. Every "must not prefer the cwd-shaped entry"
case is paired with a "must still resolve the real PATH entry" positive
control, per this repo's own rule that a check which only ever asserts
absence passes when nothing runs at all.
"""

import os
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gh_which  # noqa: E402


#: The `PATHEXT` every Windows-shaped test below pins, and the case its
#: fixture filenames are therefore created in. UPPERCASE deliberately, and
#: this is the whole of #1157's self-review finding: `safe_which` builds a
#: candidate by concatenating `name` with a `PATHEXT` entry VERBATIM, so a
#: fixture written as `gh.exe` is probed for as `gh.EXE`. That resolves on
#: a case-insensitive filesystem (macOS APFS by default, and real Windows
#: NTFS -- so production is unaffected) and does NOT resolve on a
#: case-sensitive one. This repo's CI runs four `ubuntu-latest` legs on
#: ext4, so lowercase fixtures here would have gone red on every one of
#: them, for a reason having nothing to do with the defect under test and
#: nothing to do with real Windows either. Confirmed by running this file
#: against a real case-sensitive APFS volume (`hdiutil create -fs
#: "Case-sensitive APFS"`, `pytest --basetemp=<that volume>`): 4 of 9
#: failed with lowercase fixtures, 9 of 9 pass with these.
_PINNED_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def _make_executable(path):
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _planted_name(name):
    """The three tests below run against the REAL platform (no `_force_
    windows` monkeypatch), so a fixture must be shaped for whatever
    platform actually executes it. On real Windows, `safe_which`'s own
    Windows-shaped branch applies the real `PATHEXT` and deliberately never
    probes a bare, unextended name -- see this module's own docstring and
    `_windows_candidate_names` -- so an extensionless `gh` fixture is
    unresolvable there by design and would make these three fail on real
    Windows CI while passing everywhere else. Elsewhere, a bare name is
    exactly what a real POSIX `gh` looks like. Return the name shaped for
    whichever platform is actually running the test, so the assertion
    keeps pinning exact resolution rather than being loosened to tolerate
    either shape."""
    return name + ".exe" if sys.platform == "win32" else name


def _force_windows(monkeypatch):
    """Exercise `safe_which`'s own Windows-shaped branch on whatever real
    platform this suite runs on. This is a REASONED claim about
    Windows-shaped behaviour, not an OBSERVED one: the `sys.platform ==
    "win32"` check itself is mocked, though the `PATHEXT`-walk logic
    running underneath it is real code, exercised for real (`os.path.
    exists`/`os.access` against real files created by the test), not
    re-implemented or faked for the test.

    `PATHEXT` is pinned rather than left ambient for the reason
    `test-fixture-pitfalls.md` gives about credentials: an environment
    variable the host happens to carry is a third axis beside OS and
    interpreter, and a real `windows-latest` runner DOES set `PATHEXT`
    (typically with `.PY`/`.PYW` appended). Pinning it makes the
    precedence assertion below a property of `safe_which` rather than of
    whichever runner picked the test up.
    """
    monkeypatch.setattr(gh_which.sys, "platform", "win32")
    monkeypatch.setenv("PATHEXT", _PINNED_PATHEXT)


def test_safe_which_never_prefers_the_cwd_shaped_entry_over_real_path(
    monkeypatch, tmp_path
):
    """The core #1157 property: a same-named binary planted in a directory
    that would be an implicit curdir search (never passed as `path`) must
    never be preferred over the real `PATH` entry. `safe_which` never
    performs an implicit curdir search at all -- every candidate is an
    explicit `os.path.join(directory, name)` -- so this is really pinning
    that `path` is the only search list ever consulted.
    """
    _force_windows(monkeypatch)
    cwd_dir = tmp_path / "repo_root"
    real_dir = tmp_path / "usr_local_bin"
    cwd_dir.mkdir()
    real_dir.mkdir()
    malicious = cwd_dir / "gh.CMD"
    malicious.write_text("echo malicious\n")
    _make_executable(malicious)
    real = real_dir / "gh.CMD"
    real.write_text("echo real gh\n")
    _make_executable(real)

    # `cwd_dir` is never passed as `path` -- it stands in for "whatever the
    # process's actual working directory happens to be", which `safe_which`
    # must never consult implicitly.
    resolved = gh_which.safe_which("gh", path=str(real_dir))

    assert resolved == str(real), resolved
    assert cwd_dir.name not in resolved, resolved


def test_safe_which_positive_control_still_resolves_from_real_path(
    monkeypatch, tmp_path
):
    """Must-fire pairing for the assertion above: when the real PATH entry
    is the ONLY place `gh.cmd` exists, `safe_which` must still find it --
    proving the prior test passes because of the fix, not because nothing
    ever resolves."""
    _force_windows(monkeypatch)
    real_dir = tmp_path / "usr_local_bin_2"
    real_dir.mkdir()
    real = real_dir / "gh.CMD"
    real.write_text("echo real gh\n")
    _make_executable(real)

    resolved = gh_which.safe_which("gh", path=str(real_dir))

    assert resolved == str(real), resolved


def test_safe_which_applies_pathext_when_queried_name_has_no_extension(
    monkeypatch, tmp_path
):
    """#1157 round 2: the defect real CI caught. On Python 3.9-3.11, the
    round-1 fix's reliance on `shutil.which`'s directory-component branch
    meant `PATHEXT` was never re-applied, so a bare `gh` query against a
    directory containing only `gh.exe` resolved to nothing on those three
    interpreters. `safe_which`'s own PATHEXT walk must resolve `gh` to
    `gh.exe` on every supported interpreter -- this fixture makes no
    reference to `sys.version_info`, so the assertion is either true of the
    implementation or it isn't."""
    _force_windows(monkeypatch)
    real_dir = tmp_path / "bin"
    real_dir.mkdir()
    target = real_dir / "gh.EXE"
    target.write_text("echo real gh\n")
    _make_executable(target)

    resolved = gh_which.safe_which("gh", path=str(real_dir))

    assert resolved == str(target), resolved


def test_safe_which_pathext_precedence_prefers_earlier_extension(monkeypatch, tmp_path):
    """When more than one `PATHEXT`-shaped candidate exists, `safe_which`
    must return the one earliest in `PATHEXT` order (`.COM;.EXE;.BAT;.CMD;
    ...`), matching real `shutil.which`'s own precedence -- never an
    arbitrary one, and never the last one a directory listing happens to
    produce."""
    _force_windows(monkeypatch)
    real_dir = tmp_path / "bin"
    real_dir.mkdir()
    earlier = real_dir / "gh.EXE"
    later = real_dir / "gh.CMD"
    for f in (earlier, later):
        f.write_text("echo\n")
        _make_executable(f)

    resolved = gh_which.safe_which("gh", path=str(real_dir))

    assert resolved == str(earlier), resolved


def test_safe_which_does_not_double_extend_an_already_extensioned_name(
    monkeypatch, tmp_path
):
    """A caller that already queries `gh.cmd` (an extensioned name) must
    resolve the bare `gh.cmd` file directly, never a doubly-extended
    `gh.cmd.exe` -- matching real `shutil.which`'s precedence rule that a
    name already ending in a `PATHEXT` extension is checked as-is.

    Deliberately the one Windows-shaped fixture here still spelled in
    LOWERCASE, against the pinned uppercase `PATHEXT`: the extension match
    in `_windows_candidate_names` is case-insensitive, so this is the case
    that pins that, and it is filesystem-case-safe regardless because
    `safe_which` returns the queried name verbatim rather than
    concatenating an extension onto it."""
    _force_windows(monkeypatch)
    real_dir = tmp_path / "bin"
    real_dir.mkdir()
    target = real_dir / "gh.cmd"
    target.write_text("echo\n")
    _make_executable(target)

    resolved = gh_which.safe_which("gh.cmd", path=str(real_dir))

    assert resolved == str(target), resolved


def test_safe_which_returns_none_when_nothing_resolves(monkeypatch, tmp_path):
    _force_windows(monkeypatch)
    empty_dir = tmp_path / "nothing_here"
    empty_dir.mkdir()
    assert gh_which.safe_which("gh", path=str(empty_dir)) is None


def test_safe_which_uses_real_path_env_when_path_argument_omitted(
    monkeypatch, tmp_path
):
    real_dir = tmp_path / "on_the_real_path"
    real_dir.mkdir()
    name = _planted_name("gh")
    target = real_dir / name
    target.write_text("#!/bin/sh\n")
    _make_executable(target)
    monkeypatch.setenv("PATH", str(real_dir))

    resolved = gh_which.safe_which(name)

    assert resolved == str(target), resolved


def test_safe_which_walks_past_empty_directories_to_a_later_path_entry(tmp_path):
    """#1157 self-review finding (Explore): every other test in this file
    calls `safe_which` with a single-directory `path`, so a regression that
    broke the `os.pathsep`-splitting loop entirely -- e.g. handing the whole
    joined `path` string to the accessor as one candidate directory --
    would still pass every one of them. This exercises a genuine multi-entry
    `PATH`: two directories that do not contain the binary, then one that
    does, joined with `os.pathsep` exactly as a real `PATH` environment
    variable would be. `safe_which` must walk past the first two and
    resolve the third."""
    empty_one = tmp_path / "empty_one"
    empty_two = tmp_path / "empty_two"
    real_dir = tmp_path / "the_real_one"
    for directory in (empty_one, empty_two, real_dir):
        directory.mkdir()
    name = _planted_name("gh")
    target = real_dir / name
    target.write_text("#!/bin/sh\necho gh\n")
    _make_executable(target)

    search_path = os.pathsep.join([str(empty_one), str(empty_two), str(real_dir)])
    resolved = gh_which.safe_which(name, path=search_path)

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
    name = _planted_name("gh")
    for directory in (first_dir, second_dir):
        candidate = directory / name
        candidate.write_text("#!/bin/sh\necho gh\n")
        _make_executable(candidate)

    search_path = os.pathsep.join([str(first_dir), str(second_dir)])
    resolved = gh_which.safe_which(name, path=search_path)

    assert resolved == str(first_dir / name), resolved
