"""A symlink -- or, on Windows, a directory junction -- as a measurement.

Symlink creation needs a privilege or Developer Mode on an unelevated Windows
runner, so `Path.symlink_to` raises `OSError [WinError 1314]` there, and the
correct response is the one this repo already uses everywhere else: attempt
the exact operation the case needs, and when it does not take, skip carrying
the platform, the exception type, `errno`, `winerror` and a sentence naming
what went untested. Never assert against a table of platform error codes, and
never let the skip read as a pass.

For a *directory* target there is a second mechanism worth trying first: a
Windows directory junction, made with `cmd /c mklink /J <link> <target>`.
Unlike a symlink it needs no privilege, and `Path.resolve()` follows a
junction exactly the way it follows a symlink, so a case built on "the link
resolves to something outside the base" still exercises the real property.
There is no file-shaped equivalent -- `mklink /H` makes a hard link, which is
not a reparse point and gives `resolve()` nothing new to follow -- so a
file-kind case still has only the one mechanism and skips exactly as before
when it fails.

Both mechanisms are measured the same way: created, then confirmed to
*resolve* to the target rather than merely to exist, because a link or
junction that resolved to itself would leave the caller's assertion passing
for a reason nobody chose.

Nothing here has been observed against an actual Windows runner from THIS
machine -- there is none on it. But this module has since been run on one:
`windows-latest`/3.10 in CI exercised the directory-target case for real and
the junction landed, so two of the three claims below moved from *reasoned* to
*observed* -- not by this authoring machine, by that CI leg. What that one
run establishes, and what it does not:

- **observed** (windows-latest/3.10): `mklink /J` needs no elevated privilege
  on an unprivileged runner -- it did not raise there.
- **observed** (windows-latest/3.10): `Path.resolve()` follows the junction it
  created, the same way it follows a symlink -- `_junction`'s own internal
  `landed` check passed there.
- **still reasoned, not observed**: the three *failure* arms of `_junction`
  (the subprocess failing to spawn, `mklink` exiting non-zero, or a created
  junction that does not resolve to the target) have not been exercised by any
  CI run so far -- the one Windows leg that has run this took the success
  path. A failed junction attempt never raises out of this module regardless
  -- it is folded into the skip reason next to the symlink failure, so a wrong
  guess about any of those three arms costs a slightly less precise skip
  message, never a red leg.
"""

import subprocess
import sys
from pathlib import Path

import pytest


def _junction(link, target):
    """Best-effort Windows directory junction. Never raises.

    Returns (True, None) once the junction measurably resolves to `target`, or
    (False, reason) naming what happened -- including "not windows" on every
    other platform -- so a caller can report this alongside a prior
    `symlink_to` failure without either mechanism going unnamed.
    """
    if sys.platform != "win32":
        return False, "not windows"
    try:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return False, "mklink could not be spawned ({}: {})".format(type(exc).__name__, exc)
    if proc.returncode != 0:
        return False, "mklink /J exited {} ({})".format(
            proc.returncode, (proc.stderr or proc.stdout or "").strip()
        )
    try:
        landed = link.resolve() == Path(target).resolve()
    except OSError as exc:
        return False, "junction created but would not resolve ({}: {})".format(
            type(exc).__name__, exc
        )
    if not landed:
        return False, "junction created but resolves to {} rather than {}".format(
            link.resolve(), Path(target).resolve()
        )
    return True, None


def symlink_or_skip(link, target, target_is_directory=False, what="this case"):
    """Create a symlink -- or, for a directory target, fall back to a Windows
    junction -- or skip carrying what this platform actually said.

    `what` names the property under test, quoted into the skip reason, so a
    reader of `-rs` output sees which behaviour went untested rather than a
    generic "the fixture failed".
    """
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        symlink_reason = "symlink_to raised {} (errno {!r}, winerror {!r})".format(
            type(exc).__name__, getattr(exc, "errno", None), getattr(exc, "winerror", None)
        )
        if target_is_directory:
            landed, junction_reason = _junction(link, target)
            if landed:
                return link
            pytest.skip(
                "{}: neither a symlink ({}) nor a directory junction ({}) could be made "
                "to resolve to the target here, so {} went untested".format(
                    sys.platform, symlink_reason, junction_reason, what
                )
            )
        pytest.skip(
            "{}: this platform would not create the symlink ({}), so {} went "
            "untested here".format(sys.platform, symlink_reason, what)
        )
    try:
        landed = link.resolve() == Path(target).resolve()
    except OSError as exc:
        pytest.skip(
            "{}: the link was created but would not resolve ({}, errno {!r}), so {} "
            "went untested here".format(
                sys.platform, type(exc).__name__, getattr(exc, "errno", None), what
            )
        )
    if not landed:
        pytest.skip(
            "{}: {} was created but resolves to {} rather than to {}, so the escape "
            "{} needs does not exist here and went untested".format(
                sys.platform, link, link.resolve(), Path(target).resolve(), what
            )
        )
    return link
