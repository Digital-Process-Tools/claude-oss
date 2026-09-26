"""The code-level half of withholding release authority from a sub-manager (#695).

#695 splits the manager into a scheduler that never holds a tick's payload
and a sub-manager that runs exactly one tick and dies with its context. The
issue is explicit that tag-and-publish authority must stay with the
scheduler -- filed separately as the releaser agent, #696, since built and
wired as `agents/releaser.md` -- and that the withholding has to be "in the
code, not only in prose".

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
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402 -- #1175: `gh_which.safe_which`, not a bare
# `subprocess.run(["git", ...])` with no resolution gate at all -- see
# `gh_which`'s own docstring for the Windows curdir-execution mechanism
# this closes.

#: The environment variable a caller may set to declare its own role,
#: inline on the same command line that needs it. See the module docstring
#: for why this alone is not relied on.
ROLE_ENV = "OSS_AGENT_ROLE"

#: The one role this module knows to forbid for release. Everything else --
#: absent, `maintainer`, an unrecognised string -- passes through
#: unforbidden: this is a denylist of exactly one entry, not an allowlist,
#: because the set of roles legitimately entitled to release authority is
#: `.oss.json`'s own `release.authority` question
#: (`oss_config.release_authority`) and this module does not duplicate that
#: answer.
SUB_MANAGER = "sub-manager"

#: #1690: a second, independent role this module knows to forbid, for a
#: second, independent action -- `scaffold.py --apply` -- never folded into
#: `role_forbids_release`'s own `SUB_MANAGER`-only check: the two are
#: different roles forbidden from different actions for different reasons,
#: and a shared denylist would let a fix to one silently widen the other.
#: `agents/doctor.md` is the one caller expected to declare this role.
DOCTOR = "doctor"

#: The marker's filename inside the resolved git directory.
MARKER_NAME = "oss-agent-role"

#: How long a marker is trusted before it is treated as though it were
#: never written. See the module docstring's "residue problem" section for
#: why this number is a judgement call, not a measurement.
MARKER_TTL_SECONDS = 4 * 60 * 60

#: The five states `_read_marker` can report. `live` is the only one
#: `current_role` treats as a declaration; the other four all resolve as
#: "nothing declared" for the *forbid* decision, but are reported
#: separately because "nobody ever wrote a marker", "somebody wrote one
#: and it expired", "somebody wrote one and this tool cannot parse it" and
#: "something is there and this process cannot even read it" are four
#: different facts a maintainer investigating a refusal -- or a
#: non-refusal -- may need to tell apart. `unreadable` in particular must
#: never collapse into `absent`: a permission-denied read and a genuine
#: miss are different facts about the world (one says "check what wrote
#: this and who can read it", the other says "nothing has run yet"), and
#: reporting a confident absence about a file nothing was able to look at
#: is this repository's own named trap (`doctor._dir_state`,
#: `lane_setup.worktree_occupancy`, #380) -- a classification an `except`
#: arm decided rather than one the caller actually established.
MARKER_STATE_LIVE = "live"
MARKER_STATE_STALE = "stale"
MARKER_STATE_MALFORMED = "malformed"
MARKER_STATE_UNREADABLE = "unreadable"
MARKER_STATE_ABSENT = "absent"


def _git_dir(root: str = ".") -> Path | None:
    """The repository's own git directory for `root`, or ``None``.

    Uses `git rev-parse --git-dir` rather than assuming `<root>/.git` is a
    directory: inside a worktree it is a file containing a `gitdir:`
    pointer, and asking git resolves that correctly with no special-casing
    here. `None` covers every way this can fail to answer -- `git` missing
    from PATH, `root` not inside a repository, or the call erroring -- so a
    caller never has to guess which.

    Deliberately does NOT pass `text=True` (#707): that decodes under
    `errors="strict"` using this platform's own preferred text codec
    (`locale.getpreferredencoding(False)`, not necessarily UTF-8), and a
    `UnicodeDecodeError` there is a `ValueError` -- a subclass of neither
    `OSError` nor `subprocess.SubprocessError` below, so it escaped this
    function entirely on the ordinary no-role-declared publish path, which
    calls this three times before any of `release_publish.main()`'s six
    documented states are reached. Bytes are requested instead and decoded
    explicitly as UTF-8 -- `git` writes paths in UTF-8 (confirmed against a
    real accented worktree path during review), so this is the codec that
    is actually correct here, unlike the platform-dependent default
    `text=True` used before.

    A decode failure returns `None` rather than substituting with
    `errors="replace"`: this function's own contract is that `None` covers
    every way it can fail to answer, and `doctor.dependency_diagnostic_state`'s
    `errors="replace"` convention is right for a diagnostic *log line* a
    human reads, not for a path this module goes on to read from or write
    to. Substituting U+FFFD here would fabricate a plausible-looking but
    almost-certainly-nonexistent `Path`, which `_marker_path` and
    `write_role_marker`/`_read_marker` would then read from -- or WRITE
    to -- at a location nobody actually computed from `git`'s real answer,
    silently rendering a genuinely live marker as `absent` (this same
    module's own documented trap, reintroduced by the very fix that closes
    #707's crash) rather than reporting the "could not determine" this
    function already has a state for.
    """
    git_bin = gh_which.safe_which("git")
    if git_bin is None:
        return None
    try:
        result = subprocess.run(
            [git_bin, "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    stdout = result.stdout
    if isinstance(stdout, bytes):
        try:
            stdout = stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None
    raw = (stdout or "").strip()
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


#: `_write_role_marker_detail`/`_clear_role_marker_detail`'s own three states
#: (#1137). `write_role_marker`/`clear_role_marker` collapse all of this to a
#: bool for every existing caller -- that contract is unchanged below -- but
#: the CLI's own message used to print "not inside a git repository" for
#: NOT_A_REPO and OS_ERROR alike, so a real write/unlink failure inside a
#: perfectly good repository (permissions, a full disk, a read-only mount)
#: was reported with a cause that was not the one that happened. That is
#: this repository's own named defect class -- an absence rendered as a
#: different, wrong, but confident answer -- one level down from where #1137
#: itself was filed (a harness-level permission denial neither script can
#: see at all): once the process *is* running, a real disk failure inside it
#: must not be reported as if the repository were not there.
_MARKER_OK = "ok"
_MARKER_CLEARED = "cleared"
_MARKER_NOT_A_REPO = "not-a-repo"
_MARKER_ABSENT = "absent"
_MARKER_OS_ERROR = "os-error"
#: #1716: a `--write` that would overwrite a LIVE marker naming a
#: DIFFERENT role -- most commonly a doctor run sharing a clone with a
#: live tick's own `sub-manager` marker -- refuses rather than clobbering
#: it, since `role_forbids_release` would then silently read the wrong
#: role for the rest of that tick. `force=True` is the deliberate
#: override, for a caller that has actually confirmed the old marker is
#: dead rather than merely inconvenient.
_MARKER_CONFLICT = "conflict"
#: #1752: an unconditional `--clear` can race a still-running holder of the
#: marker -- most commonly a sub-manager's own #1740 forced retry having
#: already overwritten a doctor's marker with `sub-manager` by the time the
#: doctor that originally wrote it reaches its own end-of-run clear.
#: `expect_role` makes that clear conditional on the marker still naming the
#: caller's own role; `_MARKER_OWNER_MISMATCH` is what a LIVE mismatch
#: reports, `detail` is the role actually found. A stale or absent marker is
#: not a rival, so only a LIVE mismatch refuses -- the same fail-open
#: direction #695's own staleness fix already takes.
_MARKER_OWNER_MISMATCH = "owner-mismatch"


def _write_role_marker_detail(role, root=".", written_at=None, force=False):
    """`write_role_marker`'s own work, plus which of four things happened.

    Returns `(state, detail)`: `_MARKER_OK` (written, `detail` is `None`),
    `_MARKER_NOT_A_REPO` (`root` is not inside a git repository this
    process can ask about, `detail` is `None`), `_MARKER_CONFLICT` (a LIVE
    marker already names a different role and `force` was not passed,
    `detail` is that other role, #1716), or `_MARKER_OS_ERROR` (the
    repository was found and the write itself failed, `detail` is the
    `OSError`). Only this function's caller -- the CLI -- reads the
    distinction; every other caller uses `write_role_marker`'s bool.
    """
    path = _marker_path(root)
    if path is None:
        return _MARKER_NOT_A_REPO, None
    if not force:
        existing = _read_marker(root)
        if (
            existing["state"] == MARKER_STATE_LIVE
            and existing["role"].strip().lower() != role.strip().lower()
        ):
            return _MARKER_CONFLICT, existing["role"]
    if written_at is None:
        written_at = time.time()
    payload = {"role": role.strip(), "written_at": written_at}
    try:
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    except OSError as exc:
        return _MARKER_OS_ERROR, exc
    return _MARKER_OK, None


def write_role_marker(
    role: str, root: str = ".", written_at: float | None = None, force: bool = False
) -> bool:
    """Write `role` to the marker file for the repository at `root`.

    `written_at` is an epoch-seconds override, exposed for tests that need
    to construct an already-stale marker deterministically rather than
    sleeping past `MARKER_TTL_SECONDS`; a real caller never passes it.
    `force` (#1716) overrides the live-different-role refusal below; a
    real caller never passes it either -- the refusal exists precisely so
    nothing overwrites a live marker by accident.

    Returns whether the write happened -- `False` for "`root` is not
    inside a git repository this process can ask about", "a live marker
    already names a different role" (#1716), and "the write itself
    failed", rather than raising, so a caller in a plain (non-git)
    directory gets a value to check instead of a crash on a release path.
    The CLI tells the three `False` causes apart via
    `_write_role_marker_detail`; this function's own contract -- a plain
    bool -- is unchanged.
    """
    state, _detail = _write_role_marker_detail(
        role, root=root, written_at=written_at, force=force
    )
    return state == _MARKER_OK


def _clear_role_marker_detail(root=".", expect_role=None):
    """`clear_role_marker`'s own work, plus which of four things happened.

    Returns `(state, exc)`: `_MARKER_CLEARED` (a file was removed, `exc` is
    `None`), `_MARKER_ABSENT` (no marker was there, or `root` is not inside
    a git repository -- the two `clear_role_marker` itself does not tell
    apart either, `exc` is `None`), `_MARKER_OWNER_MISMATCH` (`expect_role`
    was given, the marker is LIVE, and it names a different role -- `exc` is
    that role, #1752), or `_MARKER_OS_ERROR` (a marker was found and the
    removal itself failed, `exc` is the `OSError`). Only this function's
    caller -- the CLI -- reads the distinction.

    `expect_role`, when given, refuses to remove a LIVE marker that names a
    role other than `expect_role` rather than clobbering someone else's live
    declaration (#1752): a `doctor` marker forcibly overwritten mid-run by a
    sub-manager's own #1740 retry must not be deleted by the doctor's own
    end-of-run clear once it no longer names `doctor` at all. A stale or
    absent marker is never a rival, so the check only fires on `live` -- with
    one exception: `unreadable` cannot be told apart from `live-and-mine` any
    more than it can from `live-and-someone-else's`, so it is treated as
    inconclusive and refused too (`exc` is `None` in that case, since no role
    was ever read), rather than falling through to an unconditional unlink
    the way `MARKER_STATE_UNREADABLE` would if this only checked for `live`.
    A self-review of this same fix found exactly that gap in an earlier
    draft: the check as first written only excluded `absent`, so an
    unreadable-but-present marker (permission denied, mid-write) sailed
    through to `path.unlink()` regardless of `expect_role` -- the one state
    this whole feature exists to guard against, reached by construction
    rather than by oversight in the condition's phrasing.
    """
    path = _marker_path(root)
    if path is None or not path.is_file():
        return _MARKER_ABSENT, None
    if expect_role is not None:
        marker = _read_marker(root)
        if marker["state"] == MARKER_STATE_UNREADABLE:
            return _MARKER_OWNER_MISMATCH, None
        if (
            marker["state"] == MARKER_STATE_LIVE
            and marker["role"].strip().lower() != expect_role.strip().lower()
        ):
            return _MARKER_OWNER_MISMATCH, marker["role"]
    try:
        path.unlink()
    except OSError as exc:
        return _MARKER_OS_ERROR, exc
    return _MARKER_CLEARED, None


def clear_role_marker(root: str = ".", expect_role: str | None = None) -> bool:
    """Remove the marker file for `root`, if one exists.

    Returns whether a file was actually removed -- `False` for "no marker
    was there", "root is not inside a git repository", and, when
    `expect_role` is given, "a live marker names a different role" (#1752),
    so a caller cannot tell those apart from the return value alone, but a
    caller that only wants "is a marker gone now" gets exactly that. A
    fourth cause -- a marker was found and the removal itself failed --
    also renders `False` here; the CLI tells all of these apart via
    `_clear_role_marker_detail`.
    """
    state, _exc = _clear_role_marker_detail(root=root, expect_role=expect_role)
    return state == _MARKER_CLEARED


def _read_marker(root: str = ".") -> dict:
    """The marker's own classification: `live`, `stale`, `malformed`,
    `unreadable` or `absent`, plus whatever role and age it carries when
    it has one.

    Asks the filesystem ONE question, not two. An earlier version checked
    `path.is_file()` and then called `path.read_text()` -- but `is_file()`
    is the same family as this repository's own documented `Path.exists()`
    prohibition: it swallows `OSError` and answers `False` for a path that
    exists and cannot be `stat()`'d, so a permission-denied marker read
    `absent` at that line even before the read below got a chance to. The
    fix removes the redundant question rather than adding a matching guard
    to it: `read_text()` alone tells the whole story, and the exception it
    raises -- `FileNotFoundError` for a genuine miss, anything else for
    "there and unreadable" -- decides which arm runs. That is the same
    pattern `scripts/review_return.py`'s own `_read_source` already uses
    in this repository, for the identical reason.

    This is the one place staleness is decided, so `current_role` and any
    future caller that wants the raw classification both read it from
    here rather than each re-deriving "is this marker current" on its own.
    """
    path = _marker_path(root)
    if path is None:
        return {"state": MARKER_STATE_ABSENT, "role": None, "age_seconds": None}
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"state": MARKER_STATE_ABSENT, "role": None, "age_seconds": None}
    except OSError:
        return {"state": MARKER_STATE_UNREADABLE, "role": None, "age_seconds": None}
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
            "permanently withheld from the per-tick sub-manager by #695 "
            "and stays with the scheduler, which may spawn agents/"
            "releaser.md (#696) for it".format(resolved_role, action)
        ),
        "marker_state": marker_state,
    }


def role_forbids_scaffold_apply(role: str | None = None, root: str = ".") -> bool:
    """Does this role forbid running `scaffold.py --apply` without the
    `--i-was-asked` escape hatch? #1690: a `doctor` spawn was observed
    running `--apply`, committing the result to the default branch and
    pushing it, in a run whose own prompt explicitly said not to -- the
    same "sentence is not a mechanism" shape #695 closed for release
    authority, applied to a second role and a second action.

    `role` defaults to `current_role(root=root)`; pass it explicitly to
    check a role other than the one resolved for `root`.
    """
    resolved = role if role is not None else current_role(root=root)
    if resolved is None:
        return False
    return resolved.strip().lower() == DOCTOR


def scaffold_apply_refusal(
    role: str | None = None, root: str = ".", i_was_asked: bool = False
) -> dict:
    """A structured refusal for `scaffold.py --apply`, mirroring
    `release_refusal`'s own shape.

    `i_was_asked` is the one escape hatch, and it wins outright: #1690 is
    about an UNBIDDEN apply, not about `--apply` itself, which is the
    doctor's own documented, scripted repair path for an owned-file gap
    (`agents/doctor.md`'s "Ours to repair" step). A caller that was
    genuinely told to run this passes the flag; a caller running on its
    own initiative, or under an instruction that says NOT to, does not.

    Always returns a dict with a `forbidden` key, the same shape
    `release_refusal` uses, so a caller can act on it the same way:
    `if scaffold_apply_refusal(...)["forbidden"]:`.
    """
    resolved_role = role if role is not None else current_role(root=root)
    if i_was_asked:
        return {"forbidden": False, "role": resolved_role, "reason": None}
    forbidden = role_forbids_scaffold_apply(resolved_role, root=root)
    if not forbidden:
        return {"forbidden": False, "role": resolved_role, "reason": None}
    return {
        "forbidden": True,
        "role": resolved_role,
        "reason": (
            "role {0!r} may not run scaffold.py --apply without "
            "--i-was-asked (#1690): a doctor spawn's own repair path is "
            "scripted and legitimate, but an apply nobody explicitly asked "
            "for -- or one an instruction explicitly declined -- is exactly "
            "the shape this refuses.".format(resolved_role)
        ),
    }


#: #1690's third ask: a receipt that the one file a doctor run must never
#: silently gain a rule in did not change out from under it. `sha256`
#: rather than a full diff -- the ask is "did this change at all", not
#: "what changed", and a hash never risks echoing a credential a rule's
#: own comment might carry (this repository's own no-echo-a-credential
#: rule, applied to a settings file instead of a diagnostic finding).
def settings_local_digest(root: str = ".") -> dict:
    """The state of `.claude/settings.local.json` for `root`, for a
    before/after comparison around one doctor run.

    Three states: `present` (payload is the sha256 hex digest of the
    file's bytes), `absent` (payload is `None` -- the file genuinely does
    not exist, a legitimate state on a fresh clone), `unreadable`
    (payload is the reason -- exists but could not be read). `absent` and
    `unreadable` must never collapse into each other: a caller comparing
    two digests needs to know whether "nothing to compare" means "there
    was never a file" or "something is wrong reading it", the same
    three-state shape every other check in this project uses.
    """
    path = Path(root) / ".claude" / "settings.local.json"
    try:
        exists = path.is_file()
    except OSError as exc:
        return {"state": "unreadable", "digest": str(exc)}
    if not exists:
        return {"state": "absent", "digest": None}
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"state": "unreadable", "digest": str(exc)}
    return {"state": "present", "digest": hashlib.sha256(data).hexdigest()}


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
    parser.add_argument(
        "--force",
        action="store_true",
        help="#1716: overwrite a live marker naming a different role, "
        "instead of refusing. A real caller passes this only once it has "
        "actually confirmed the old marker is dead, never on the ordinary "
        "path.",
    )
    parser.add_argument(
        "--expect-role",
        metavar="ROLE",
        default=None,
        help="with --clear, refuse to remove a LIVE marker that names a "
        "role other than ROLE, instead of clobbering it (#1752): protects "
        "a still-running holder of the marker -- most commonly a doctor "
        "run whose marker a sub-manager's own #1740 forced retry has "
        "already overwritten -- from having its role dropped by another "
        "agent's own end-of-run clear.",
    )
    args = parser.parse_args(argv)

    if args.write is not None and args.clear:
        print("--write and --clear are mutually exclusive")
        return 2

    if args.clear:
        state, exc = _clear_role_marker_detail(
            root=args.root, expect_role=args.expect_role
        )
        if state == _MARKER_OWNER_MISMATCH:
            if exc is None:
                print(
                    "refusing to clear the role marker for {0!r}: it could "
                    "not be read to confirm it still names the expected "
                    "{1!r} -- leaving it alone rather than risk dropping "
                    "someone else's live declaration (#1752)".format(
                        args.root, args.expect_role.strip()
                    )
                )
            else:
                print(
                    "refusing to clear the role marker for {0!r}: a live "
                    "marker names role {1!r}, not the expected {2!r} -- "
                    "leaving it alone rather than dropping someone else's "
                    "live declaration (#1752)".format(
                        args.root, exc, args.expect_role.strip()
                    )
                )
            return 4
        if state == _MARKER_OS_ERROR:
            print(
                "could not clear the role marker for {0!r}: {1} -- the "
                "marker may still be on disk".format(args.root, exc)
            )
            return 1
        print(
            "cleared"
            if state == _MARKER_CLEARED
            else "nothing to clear for {0!r}".format(args.root)
        )
        return 0

    if args.write is not None:
        state, detail = _write_role_marker_detail(
            args.write, root=args.root, force=args.force
        )
        if state == _MARKER_NOT_A_REPO:
            print(
                "could not write the role marker for {0!r} -- not inside a "
                "git repository this process can ask about".format(args.root)
            )
            return 1
        if state == _MARKER_CONFLICT:
            print(
                "refusing to write role {0!r} for {1!r}: a live marker "
                "already names role {2!r} -- pass --force to overwrite it "
                "(#1716)".format(args.write.strip(), args.root, detail)
            )
            return 3
        if state == _MARKER_OS_ERROR:
            print(
                "could not write the role marker for {0!r}: {1}".format(
                    args.root, detail
                )
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
