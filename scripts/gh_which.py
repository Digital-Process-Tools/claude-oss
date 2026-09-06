"""#1157: the one place this repo resolves an external binary before
spawning it, so there is exactly one copy of "how gh/git gets resolved" to
keep in sync rather than one per call site.

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

``safe_which`` closes it by never handing ``shutil.which`` a bare name. It
walks the real search path itself -- ``path`` if given, else
``os.environ.get("PATH", os.defpath)`` -- and for each directory joins that
directory onto ``name`` before calling ``shutil.which`` on the joined
candidate. A joined candidate always carries a directory component, so
``shutil.which`` takes the branch that sets ``path = [dirname]`` directly
and never reaches the curdir-insertion code at all, while still getting
``shutil.which``'s own cross-platform ``PATHEXT`` handling for each
candidate in turn. An empty ``PATH`` entry (POSIX and Windows both read one
as "the current directory") is normalised to ``os.curdir`` explicitly rather
than left as ``""`` -- ``os.path.join("", name)`` is ``name`` again, which
would reintroduce the exact bare-name path this function exists to avoid --
so it is searched only when the real ``PATH`` says to, never implicitly.
"""

import os
import shutil


def safe_which(name, path=None):
    """Resolve `name` on `path` (default: the real `PATH`) without ever
    letting an implicit current-working-directory search take priority over
    a real `PATH` entry. Returns an absolute path, or `None` if nothing on
    the search path resolves -- the same contract `shutil.which` has.
    """
    search_path = path if path is not None else os.environ.get("PATH", os.defpath)
    if not search_path:
        return None
    seen = set()
    for directory in search_path.split(os.pathsep):
        candidate_dir = directory if directory else os.curdir
        normalised = os.path.normcase(os.path.abspath(candidate_dir))
        if normalised in seen:
            continue
        seen.add(normalised)
        resolved = shutil.which(os.path.join(candidate_dir, name))
        if resolved:
            return os.path.abspath(resolved)
    return None
