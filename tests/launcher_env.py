"""The PATH a launcher suite hands the shell, in one place.

Four suites spawn `bin/oss-workspace` under a shell with a deliberately minimal PATH,
and each of them had its own copy of the entry list. #1177 is what a second copy costs:
the list named no directory a Windows install of git is in, and fixing the copy in
`test_workspace_launcher.py` would have left three suites still failing for a reason
already understood.

Why minimal at all: with the real `claude` reachable, the "missing claude" case found it
and EXECUTED it -- a suite that launches a live agent session in a temp directory.

The entries, and why each one is here:

* **the stub directory**, which is the point of the fixture;
* **the interpreter's own directory**, because the launcher needs a python to read the
  channel name and find the consumer. `/usr/bin` and `/bin` are Git Bash's on Windows
  and hold no python at all, so pinning to those alone starved the launcher of one -- it
  then said so correctly, and the channel assertions failed against a fixture problem
  wearing a product bug's clothes;
* **git's own directory (#1177)**, which is what the earlier lists left to the ambient
  environment. The launcher's first act is `command -v git`, and none of the other three
  entries names a directory a Windows install of git is in. Serially those tests passed
  anyway, so something outside the list was supplying it; under `pytest-xdist` they did
  not, and every test in the four suites failed on a Windows leg with `oss-workspace: git
  is not on PATH` while POSIX stayed green. Whatever the ambient mechanism was, a fixture
  that depends on it is asserting on a condition it did not establish;
* **`/usr/bin` and `/bin`**, for the system utilities the script itself calls.

`GIT` can be None -- a machine with no git -- so it is filtered rather than assumed. The
suites' own `_require_git` skips the tests that build a repository; the rest still run,
and exercise the launcher's real `git is not on PATH` arm rather than a fixture failure.

Python 3.9 compatible.
"""

import os
import shutil
import sys
from pathlib import Path

#: Resolved in THIS process, the same resolution the suites use to `git init` a fixture
#: repository, so the child is handed exactly the git the test itself is using.
GIT = shutil.which("git")


def entries(bindir):
    """The PATH entries, in order, as a list of strings."""
    found = [str(bindir), str(Path(sys.executable).parent)]
    if GIT:
        found.append(str(Path(GIT).parent))
    found.extend(["/usr/bin", "/bin"])
    return found


def pinned_path(bindir):
    """The PATH value itself, joined with this platform's separator."""
    return os.pathsep.join(entries(bindir))
