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

## The marker's own residue problem, and the asymmetry that made it a bug

The first version of the marker was write-only: nothing ever cleared it, no
`--clear`, no expiry, no process identity attached to it. A sub-manager
that dies mid-tick -- crashes, is killed, its harness dies -- leaves the
marker on disk forever. A later, wholly legitimate `/oss:release` from the
same clone would then resolve `sub-manager` from that residue and refuse to
publish, with a confident reason citing this very issue. The asymmetry is
this repository's own defect class pointed at the direction that blocks
work rather than the one that permits it: an *absent* marker fails open
(deliberate, and fine -- a maintainer's ordinary run has no marker), but a
*stale* marker failed closed forever, with nothing to tell a live
sub-manager from a dead one's leftover file.

Two mechanisms close this, and only one of them is sufficient on its own:

  * **every marker carries `written_at` and expires after
    `MARKER_TTL_SECONDS`.** This alone closes the crash path, because it
    requires nothing from the process that wrote it -- an expired marker
    stops mattering on its own, with no cooperation needed from whatever
    died. `MARKER_TTL_SECONDS` is a judgement call (four hours): long
    enough that an ordinary tick's own later release-adjacent calls do not
    race past their own marker's expiry mid-tick, short enough that a
    crash's residue does not block releases for a genuinely long time.
    Nothing in this repository yet measures a real tick's duration to tune
    this against -- see #694, the per-tick context accounting issue -- so
    this number should be revisited once that measurement exists rather
    than trusted as calibrated.
  * `clear_role_marker()` (`--clear` on the CLI) gives the *success* path
    an immediate release rather than making it wait out the TTL. This does
    NOT cover the crash path by itself -- nothing runs a process's own
    cleanup code when that process never reaches its last line -- which is
    exactly why the TTL exists independently of it, not as a backstop to
    it.

A marker that has expired, or that this module cannot parse at all (the
very first, pre-JSON marker format included -- a bare role string with no
timestamp reads as unparsable now, and must fail open rather than crash or
silently grant `sub-manager`), is **not** the same thing as "nothing was
ever declared", and collapsing the two into one silent `None` would hide
exactly the fact a maintainer investigating an unexpected refusal -- or an
unexpectedly clean release -- would need. So `_read_marker()` gives it its
own state, `stale` or `malformed`, distinct from `live` and `absent`.
`current_role()`'s two-state (`str | None`) public contract does not
change: `stale` and `malformed` both resolve through it exactly the way
`absent` does, towards *permitting* the release. That is a decision, not
an accident -- treating "cannot classify" as "therefore block" would
silently reintroduce the residue bug wearing a more defensible-sounding
name. `release_refusal()` still surfaces the underlying `marker_state` for
whichever caller wants to log or inspect it, so the classification is not
lost even though the forbid decision does not depend on it.

If a stale marker is blocking a release before its TTL has elapsed and a
maintainer wants it gone immediately rather than waiting:
`python3 scripts/agent_role.py --clear --root <repo>`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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

#: How long a marker is trusted before it is treated as though it were
#: never written. See the module docstring's "residue problem" section for
#: why this number is a judgement call, not a measurement.
MARKER_TTL_SECONDS = 4 * 60 * 60

#: The four states `_read_marker` can report. `live` is the only one
#: `current_role` treats as a declaration; the other three all resolve as
#: "nothing declared" for the *forbid* decision, but are reported
#: separately because "nobody ever wrote a marker" and "somebody wrote one
#: and this tool no longer trusts it" are different facts a maintainer
#: investigating a refusal may need to tell apart.
MARKER_STATE_LIVE = "live"
MARKER_STATE_STALE = "stale"
MARKER_STATE_MALFORMED = "malformed"
MARKER_STATE_ABSENT = "absent"


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


def write_role_marker(role: str, root: str = ".", written_at: float | None = None) -> bool:
    """Write `role` to the marker file for the repository at `root`.

    `written_at` is an epoch-seconds override, exposed for tests that need
    to construct an already-stale marker deterministically rather than
    sleeping past `MARKER_TTL_SECONDS`; a real caller never passes it.

    Returns whether the write happened -- `False` when `root` is not inside
    a git repository this process can ask about, rather than raising, so a
    caller in a plain (non-git) directory gets a value to check instead of
    a crash on a release path.
    """
    path = _marker_path(root)
    if path is None:
        return False
    if written_at is None:
        written_at = time.time()
    payload = {"role": role.strip(), "written_at": written_at}
    try:
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def clear_role_marker(root: str = ".") -> bool:
    """Remove the marker file for `root`, if one exists.

    Returns whether a file was actually removed -- `False` for both "no
    marker was there" and "root is not inside a git repository", so a
    caller cannot tell those apart from the return value alone, but a
    caller that only wants "is a marker gone now" gets exactly that.
    """
    path = _marker_path(root)
    if path is None or not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _read_marker(root: str = ".") -> dict:
    """The marker's own classification: `live`, `stale`, `malformed` or
    `absent`, plus whatever role and age it carries when it has one.

    This is the one place staleness is decided, so `current_role` and any
    future caller that wants the raw classification both read it from
    here rather than each re-deriving "is this marker current" on its own.
    """
    path = _marker_path(root)
    if path is None or not path.is_file():
        return {"state": MARKER_STATE_ABSENT, "role": None, "age_seconds": None}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {"state": MARKER_STATE_ABSENT, "role": None, "age_seconds": None}
    try:
        data = json.loads(raw)
        role = data["role"]
        written_at = float(data["written_at"])
        if not isinstance(role, str) or not role.strip():
            raise ValueError("empty or non-string role")
    except (ValueError, KeyError, TypeError):
        # Covers the pre-JSON marker format (a bare role string, no
        # timestamp) as well as genuine corruption -- both are "this tool
        # cannot classify it", and both must fail open rather than crash
        # or silently grant sub-manager. See the module docstring.
        return {"state": MARKER_STATE_MALFORMED, "role": None, "age_seconds": None}
    age = time.time() - written_at
    if age < 0 or age > MARKER_TTL_SECONDS:
        # A negative age (a future timestamp -- clock skew, or a marker
        # this tool did not write) is exactly as untrustworthy as one that
        # is too old: neither can be relied on to mean "written recently
        # by a live sub-manager", so both fail open the same way.
        return {"state": MARKER_STATE_STALE, "role": role, "age_seconds": age}
    return {"state": MARKER_STATE_LIVE, "role": role, "age_seconds": age}


def current_role(role: str | None = None, root: str = ".") -> str | None:
    """The declared role: an explicit `role` argument, else the environment,
    else a *live* marker file for `root`, else ``None``.

    A `stale` or `malformed` marker resolves the same as `absent` here --
    deliberately, per the module docstring's "residue problem" section.
    Use `_read_marker(root)` directly to see the underlying classification.
    """
    if role is not None:
        return role if role else None
    env_value = os.environ.get(ROLE_ENV)
    if env_value:
        return env_value
    marker = _read_marker(root)
    if marker["state"] == MARKER_STATE_LIVE:
        return marker["role"]
    return None


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

    Also always carries `marker_state` (one of the four `MARKER_STATE_*`
    values) so a `stale`/`malformed` marker that was silently ignored for
    the forbid decision is still visible to whatever reads this dict --
    otherwise a maintainer investigating a release that unexpectedly went
    through, or one that unexpectedly did not, has no way to see that a
    residue marker was there at all.
    """
    resolved_role = role if role is not None else current_role(root=root)
    forbidden = role_forbids_release(resolved_role, root=root)
    marker_state = _read_marker(root)["state"]
    if not forbidden:
        return {
            "forbidden": False,
            "role": resolved_role,
            "reason": None,
            "marker_state": marker_state,
        }
    return {
        "forbidden": True,
        "role": resolved_role,
        "reason": (
            "role {0!r} may not {1}: release (tag, publish) authority is "
            "withheld from the per-tick sub-manager by #695 and stays with "
            "the scheduler until #696 (the releaser agent) gives it a "
            "spawn of its own".format(resolved_role, action)
        ),
        "marker_state": marker_state,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write, clear or read the role marker used to withhold release "
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
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove this repository's role marker, if one exists",
    )
    args = parser.parse_args(argv)

    if args.write is not None and args.clear:
        print("--write and --clear are mutually exclusive")
        return 2

    if args.clear:
        removed = clear_role_marker(root=args.root)
        print("cleared" if removed else "nothing to clear for {0!r}".format(args.root))
        return 0

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

    marker = _read_marker(root=args.root)
    role = current_role(root=args.root)
    print(role if role is not None else "(none declared)")
    if marker["state"] != MARKER_STATE_ABSENT:
        print("  marker state: {0}".format(marker["state"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
