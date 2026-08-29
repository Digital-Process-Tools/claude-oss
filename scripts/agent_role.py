"""The code-level half of withholding release authority from a sub-manager (#695).

#695 splits the manager into a scheduler that never holds a tick's payload
and a sub-manager that runs exactly one tick and dies with its context. The
issue is explicit that tag-and-publish authority must stay with the
scheduler -- filed separately as the releaser agent, #696 -- and that the
withholding has to be "in the code, not only in prose".

Prose alone was already tried and named as insufficient for a related
boundary in this repository: `CLAUDE.md`'s section on agent tool grants
argues "prose is a request, frontmatter is the boundary" and then shows the
frontmatter half is not enough either once a grant reaches `Bash` (#251, an
audit spawn whose own definition said "annotates, never blocks" and then ran
a write op anyway). The lesson generalises past tool grants: a sentence in
`agents/sub-manager.md` telling it never to run the release phase is exactly
that kind of request, and this module is what makes it a fact a release
script checks for itself instead.

## Two mechanisms, because one of them was measured and found empty

The first version of this module read the role from one place:
`OSS_AGENT_ROLE` in the environment, set by `export` in the sub-manager's
first shell call. **That mechanism provides no defense at all**, and this
was not assumed -- it was measured directly, in this repository's own
session: `export OSS_AGENT_ROLE=sub-manager` in one `Bash` tool call,
followed by a bare `echo "[$OSS_AGENT_ROLE]"` in the *next* call, printed
`[]`. Each `Bash` invocation in this harness is its own process; nothing
exported in one survives to the next. An agent's "declare your role" call
and its later call into `release_publish.py` are two different processes,
so `current_role()` reading only the environment would return `None` at
exactly the moment it needs to return `sub-manager` -- silently, with no
signal distinguishing it from a maintainer's ordinary release run. That is
this repository's own defect class (an absence rendered as clean) landing
inside the one gate this issue was filed to make code-level rather than
prose-level.

So the role is also written to a **marker file under the repository's own
git directory** -- `git rev-parse --git-dir`, resolved fresh each time
rather than assumed to be `<root>/.git`, because `.git` is a *file* rather
than a directory inside a worktree (the shape every lane in this repository
actually runs in) and a bare `<root> / ".git" / MARKER_NAME` would try to
create a file inside a file. A git directory is local to the repository, not
to one shell process, so it is readable from a wholly separate `python3`
invocation -- which is what an agent's later call into `release_publish.py`
actually is. The environment variable is kept as a second, faster path for a
caller that can genuinely set it inline on the same command line that needs
it (`OSS_AGENT_ROLE=sub-manager python3 release_publish.py ...`); it is
checked first and the marker file is the fallback, not the other way
around, so nothing about the original mechanism's intended fast path is
lost -- only its status as the *only* mechanism.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

#: The environment variable a caller may set to declare its own role,
#: inline on the same command line that needs it. See the module docstring
#: for why this alone is not relied on.
ROLE_ENV = "OSS_AGENT_ROLE"

#: The one role this module knows to forbid. Everything else -- absent,
#: `maintainer`, an unrecognised string -- passes through unforbidden: this
#: is a denylist of exactly one entry, not an allowlist, because the set of
#: roles legitimately entitled to release authority is `.oss.json`'s own
#: `release.authority` question (`oss_config.release_authority`) and this
#: module does not duplicate that answer.
SUB_MANAGER = "sub-manager"

#: The marker's filename inside the resolved git directory.
MARKER_NAME = "oss-agent-role"


def _git_dir(root: str = ".") -> Path | None:
    """The repository's own git directory for `root`, or ``None``.

    Uses `git rev-parse --git-dir` rather than assuming `<root>/.git` is a
    directory: inside a worktree it is a file containing a `gitdir:`
    pointer, and asking git resolves that correctly with no special-casing
    here. `None` covers every way this can fail to answer -- `git` missing
    from PATH, `root` not inside a repository, or the call erroring -- so a
    caller never has to guess which.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(root) / path
    return path.resolve()


def _marker_path(root: str = ".") -> Path | None:
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    return git_dir / MARKER_NAME


def write_role_marker(role: str, root: str = ".") -> bool:
    """Write `role` to the marker file for the repository at `root`.

    Returns whether the write happened -- `False` when `root` is not inside
    a git repository this process can ask about, rather than raising, so a
    caller in a plain (non-git) directory gets a value to check instead of
    a crash on a release path.
    """
    path = _marker_path(root)
    if path is None:
        return False
    try:
        path.write_text(role.strip() + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def current_role(role: str | None = None, root: str = ".") -> str | None:
    """The declared role: an explicit `role` argument, else the environment,
    else the marker file for `root`, else ``None``.
    """
    if role is not None:
        return role if role else None
    env_value = os.environ.get(ROLE_ENV)
    if env_value:
        return env_value
    path = _marker_path(root)
    if path is None or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def role_forbids_release(role: str | None = None, root: str = ".") -> bool:
    """Does this role forbid release (tag, publish) authority?

    `role` defaults to `current_role(root=root)`; pass it explicitly to
    check a role other than the one resolved for `root`.
    """
    resolved = role if role is not None else current_role(root=root)
    if resolved is None:
        return False
    return resolved.strip().lower() == SUB_MANAGER


def release_refusal(action: str, role: str | None = None, root: str = ".") -> dict:
    """A structured refusal for `action`, or a structured non-refusal.

    Always returns a dict with a `forbidden` key so a caller can act on the
    shape without a second branch: `if release_refusal(...)["forbidden"]:`.
    """
    resolved_role = role if role is not None else current_role(root=root)
    forbidden = role_forbids_release(resolved_role, root=root)
    if not forbidden:
        return {"forbidden": False, "role": resolved_role, "reason": None}
    return {
        "forbidden": True,
        "role": resolved_role,
        "reason": (
            "role {0!r} may not {1}: release (tag, publish) authority is "
            "withheld from the per-tick sub-manager by #695 and stays with "
            "the scheduler until #696 (the releaser agent) gives it a "
            "spawn of its own".format(resolved_role, action)
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write or read the role marker used to withhold release "
            "authority from the per-tick sub-manager (#695)."
        )
    )
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument(
        "--write",
        metavar="ROLE",
        default=None,
        help="write ROLE to this repository's role marker",
    )
    args = parser.parse_args(argv)

    if args.write is not None:
        ok = write_role_marker(args.write, root=args.root)
        if not ok:
            print(
                "could not write the role marker for {0!r} -- not inside a "
                "git repository this process can ask about".format(args.root)
            )
            return 1
        print("wrote role {0!r} for {1!r}".format(args.write.strip(), args.root))
        return 0

    role = current_role(root=args.root)
    print(role if role is not None else "(none declared)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
