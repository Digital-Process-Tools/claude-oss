"""#1157: the one place this repo DEFINES how an external binary is
resolved before spawning it, and the one copy every call site that can
import a module routes through -- #1325's own audit found this docstring
overclaiming past that: `scripts/statusline.py` is vendored standalone (see
its own module docstring -- "No third-party imports... installs nothing to
run it") and therefore CANNOT import this module, so it carries its own,
deliberately parallel copy of this exact walk (`_safe_which`,
`_win_candidate_names`) rather than a bypass of it. That copy is legitimate
and permanent, not a gap to close -- see
`tests/test_gh_git_resolution_arms_1295.py` for the direct parity checks
between the two, and this module's own docstring no longer claims there is
only one implementation, only that there is one DEFINITION every other
site (all of `scripts/*.py` except the vendored file) is required to route
through -- a claim `tests/test_bare_gh_git_spawn_sweep_1165.py`'s sweep
still checks live.

The round-1 release audit that opened #1157 found seven sites #1109 had
just taught to call ``shutil.which("gh")`` (with no ``path=``) ahead of a
spawn -- and five pre-existing sites doing the identical thing for ``gh`` or
``git``. On Windows, ``shutil.which`` inserts the current working directory
into the search path whenever the queried name has no directory component,
via ``_win_path_needs_curdir`` on Python 3.12+ (true unless the process
environment carries ``NoDefaultCurrentDirectoryInExePath``, unset by
default) and unconditionally on 3.9-3.11, three of this repo's four matrix
interpreters. **That insertion is not gated on whether a ``path=`` argument
was passed** -- it fires whenever ``os.path.split(cmd)`` finds no directory
part in ``cmd`` itself, regardless of what search path was supplied. So
``shutil.which("gh", path=os.environ.get("PATH", os.defpath))`` -- the fix
that looks obvious from the outside -- does NOT close the gap: a ``gh.cmd``
committed to the root of a repository this tool is pointed at is still
resolved and executed ahead of a real ``PATH`` entry, exactly as it was
before adding ``path=``.

A first version of ``safe_which`` (#1157, round 1) tried to close this by
joining each real search directory onto ``name`` and handing the joined
candidate to ``shutil.which`` -- reasoning that a candidate with a
directory component always takes the branch that skips curdir-insertion
entirely. That is true, but it is not the only place `shutil.which`'s
behaviour differs by CPython version. **On Python 3.9-3.11**, the
directory-component branch is a hard early return:

    if os.path.dirname(cmd):
        if _access_check(cmd, mode):
            return cmd
        return None

-- a single, unextended existence/access check against the literal joined
path, with no re-application of ``PATHEXT`` to the basename at all. Only on
3.12+ does ``shutil.which`` split ``dirname``/basename apart internally and
re-apply ``PATHEXT`` to the basename before rejoining. So the round-1
``safe_which``, on 3.9-3.11 (three of this repo's four matrix
interpreters), silently failed to find a real ``gh.exe``/``gh.cmd`` in ANY
directory on Windows -- confirmed by PR #1161's own CI: all four Windows
legs failed at ~164-295 tests on 3.9/3.10/3.11, and passed (module two
fixture-only failures, since fixed) on 3.12.

``safe_which`` now performs the directory-and-``PATHEXT`` walk itself,
using only accessors whose behaviour does not vary across this repo's
supported interpreters (``os.path.exists``, ``os.access``,
``os.path.isdir``, ``os.environ``) -- it never calls ``shutil.which`` at
all.
For each real search directory (``path`` if given, else
``os.environ.get("PATH", os.defpath)``) it builds one or more candidate
filenames from ``name``: on non-Windows platforms, just ``name`` itself;
on Windows, ``name`` plus each ``PATHEXT`` extension in turn, mirroring
``shutil.which``'s own precedence for its default mode (``os.F_OK |
os.X_OK``) exactly -- if ``name`` already ends with one of ``PATHEXT``'s
extensions, only the bare name is checked, otherwise the bare name is
never checked and only ``name`` plus each extension is. Every candidate is
built by joining an explicit search directory onto an explicit filename, so
there is nothing left for an implicit current-working-directory search to
reach: the curdir-safety property this module exists for is unchanged.
An empty ``PATH`` entry (POSIX and Windows both read one as "the current
directory") is normalised to ``os.curdir`` explicitly rather than left as
``""`` -- ``os.path.join("", name)`` is ``name`` again, which would
reintroduce the exact bare-name path this function exists to avoid -- so it
is searched only when the real ``PATH`` says to, never implicitly.
"""

import os
import sys

# Mirrors `shutil._WIN_DEFAULT_PATHEXT` (stable across this repo's 3.9-3.12
# matrix): the fallback used when the `PATHEXT` environment variable is
# unset. Hardcoded rather than read off the installed `shutil` module so
# this function never depends on a private stdlib attribute continuing to
# exist under that name.
_WIN_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD;.VBS;.JS;.WS;.MSC"


def _windows_candidate_names(name):
    """The filenames to probe for `name` on Windows, in the same order and
    by the same precedence real `shutil.which` applies for its default mode
    (`os.F_OK | os.X_OK`): if `name` already ends with one of `PATHEXT`'s
    extensions, only the bare name is checked. Otherwise the bare name is
    never checked, and `name` plus each `PATHEXT` extension is, in
    `PATHEXT` order.
    """
    # `PATHEXT` is a Windows environment-variable convention, always
    # ";"-delimited regardless of `os.pathsep` on the interpreter actually
    # running this code (real `shutil.which` gets away with `os.pathsep`
    # here only because that branch runs exclusively where `sys.platform ==
    # "win32"` is genuinely true, so `os.pathsep` is really ";" there too --
    # a test that mocks `sys.platform` without also being on real Windows
    # would otherwise split on the host's own `os.pathsep` instead).
    pathext_source = os.environ.get("PATHEXT") or _WIN_DEFAULT_PATHEXT
    pathext = [ext for ext in pathext_source.split(";") if ext]
    lowered = name.lower()
    if any(lowered.endswith(ext.lower()) for ext in pathext):
        return [name]
    return [name + ext for ext in pathext]


def _access_check(candidate):
    """Mirrors `shutil._access_check` exactly (identical across this
    repo's whole 3.9-3.12 matrix): exists, executable, and not a
    directory.
    """
    return (
        os.path.exists(candidate)
        and os.access(candidate, os.X_OK)
        and not os.path.isdir(candidate)
    )


def safe_which(name, path=None):
    """Resolve `name` on `path` (default: the real `PATH`) without ever
    letting an implicit current-working-directory search take priority over
    a real `PATH` entry, and without depending on a CPython-version-specific
    quirk of `shutil.which`'s own `PATHEXT` handling. Returns an absolute
    path, or `None` if nothing on the search path resolves -- the same
    contract `shutil.which` has.
    """
    search_path = path if path is not None else os.environ.get("PATH", os.defpath)
    if not search_path:
        return None
    is_windows = sys.platform == "win32"
    candidate_names = _windows_candidate_names(name) if is_windows else [name]
    seen = set()
    for directory in search_path.split(os.pathsep):
        candidate_dir = directory if directory else os.curdir
        normalised = os.path.normcase(os.path.abspath(candidate_dir))
        if normalised in seen:
            continue
        seen.add(normalised)
        for candidate_name in candidate_names:
            candidate = os.path.join(candidate_dir, candidate_name)
            if _access_check(candidate):
                return os.path.abspath(candidate)
    return None
