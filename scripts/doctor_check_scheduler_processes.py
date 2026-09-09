"""``check_scheduler_processes`` -- one check, in its own module per the
#497/#630 convention.

#1350: a tick's sub-manager found the shared clone's `main` already checked
out to a branch it had never created. `ps aux` turned up two other live
`claude /oss:tick` processes sharing the same clone, one of them running for
two days -- a PR belonging to one of them (#1331) sat green and unmerged for
38 minutes, invisible to the tick that could see it on the board, because
nothing in this loop records which scheduler owns a lane or even that more
than one might be running against the same clone at once. Every rule this
repository has about lane ownership -- claim the issue, release the lane,
reap the worktree -- assumes one scheduler per clone, and that assumption was
neither stated nor checked anywhere.

The issue names three candidate mechanisms; this is the cheapest of the
three, and the only one implemented here (see the issue's own thread for why
the other two -- a scheduler recording its own pid in the state file, and a
tick's own step 1 comparing HEAD's branch against one it created itself --
are left for a follow-up: both need a persisted, cross-session record kept
current by every scheduler, in a state file (`scripts/oss_state.py`, 4,000+
lines) that concurrent lanes in the same tick as this one are also touching,
which is a wider, separately-reviewable change). This check answers a
narrower question that needs no new persisted state at all: **right now, how
many live processes shaped like a `claude ... oss:tick` scheduler are running
with their working directory inside this clone?**

Three states, never two, matching this repository's own convention for a
check that can fail to look rather than find nothing:

* ``"counted"`` -- `ps` ran, and every candidate process's cwd was either
  resolved (and could be compared against this clone) or there were no
  candidates to resolve in the first place. The payload is
  ``{"count": int, "candidates_seen": int}`` -- ``count`` is the number
  attributed to *this* clone specifically, which may be lower than
  ``candidates_seen`` if some matching processes belong to a different
  clone entirely (a maintainer running ticks against two repositories on the
  same machine must not see a scheduler on repo B reported as a sibling
  inside repo A's clone).
* ``"could-not-tell"`` -- `ps` is not on PATH (expected on Windows: no
  built-in analogue is spawned here, matching this repo's existing "no
  Windows shim" choices elsewhere in `doctor_check_*`), `ps` failed to run
  or exited non-zero, or a candidate process was found but its working
  directory could not be resolved on this platform/permission set (no
  `/proc/<pid>/cwd`, no `lsof`, or either denied). A found-but-unattributable
  candidate is reported as ``could-not-tell`` rather than silently excluded
  from the count or silently included -- excluding it renders exactly like
  the #1350 incident (a live sibling nobody could see), and including it
  unverified could false-positive a maintainer running unrelated ticks on
  the same box.

**The persistence failure mode this design deliberately avoids**: nothing
here is written to disk, so there is no stale pid file to misread. A crashed
scheduler simply has no live process, and `ps` will not find it -- there is
no "last known" state that could render a dead session as a live sibling.
The cost of that choice is the flip side: this check answers only "right
now", never "was a sibling here a moment ago" -- if the sibling scheduler
exits between this check running and its own decision being acted on, the
race still exists. Recording an intent (a pid, a claimed branch) in the
shared state file is what would close that race, and that is exactly the
piece left to the follow-up.

Every shared name is reached through `doctor` imported as a module, so a
test's `monkeypatch.setattr(doctor, ...)` still reaches this code, the same
convention `doctor_check_vanished_worktree.py` documents for its own checks.
"""

import os
import subprocess
import sys

import doctor  # noqa: F401 -- imported for the shared-name convention above
import gh_which  # #1175: `gh_which.safe_which`, never a bare `shutil.which` --
# see that module's own docstring for the Windows curdir-execution mechanism
# this closes, for every binary this module spawns (`ps`, `lsof`).

#: The two substrings a candidate process's command line must both contain.
#: Matched against the whole `ps` command column, not tokenised -- a scheduler
#: invoked as `claude /oss:tick ...`, `claude -p "/oss:tick ..."`, or with any
#: other flags between the two still matches; a bare `claude` chat session or
#: an unrelated `oss:tick`-mentioning grep does not, because it lacks the
#: other half.
_NEEDLE_A = "claude"
_NEEDLE_B = "oss:tick"


def _run_ps(run, ps_bin):
    try:
        done = run(
            [ps_bin, "-eo", "pid,command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, exc
    return done.returncode, done, None


def _matching_processes(ps_output):
    """Parse ``ps -eo pid,command`` output (header row included) for lines
    whose command column contains both needles. Returns a list of
    ``(pid, command)`` pairs. Tolerant of a short or malformed line -- one
    line this loop cannot parse must not abort the whole check."""
    matches = []
    lines = ps_output.splitlines()
    for line in lines[1:] if lines else []:
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, command = parts
        if not pid_str.isdigit():
            continue
        lowered = command.lower()
        if _NEEDLE_A in lowered and _NEEDLE_B in lowered:
            matches.append((int(pid_str), command))
    return matches


def _process_cwd(pid, run):
    """Resolve `pid`'s current working directory, or ``None`` when this
    platform/permission set cannot answer. Linux reads `/proc/<pid>/cwd`
    directly; macOS (no `/proc`) shells out to `lsof`; anywhere else
    (Windows, an unrecognised platform) is unsupported and answers ``None``
    without attempting a spawn that would only fail."""
    if sys.platform.startswith("linux"):
        try:
            return os.readlink("/proc/{}/cwd".format(pid))
        except OSError:
            return None
    if sys.platform == "darwin":
        lsof_bin = gh_which.safe_which("lsof")
        if lsof_bin is None:
            return None
        try:
            done = run(
                [lsof_bin, "-a", "-d", "cwd", "-p", str(pid), "-Fn"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:
            return None
        for line in done.stdout.splitlines():
            if line.startswith("n"):
                return line[1:]
        return None
    return None


def scheduler_process_state(project_dir, run=None):
    """How many live `claude ... oss:tick`-shaped processes have their
    working directory inside `project_dir`. See the module docstring for the
    two states and why a found-but-unattributable candidate is
    ``could-not-tell`` rather than folded into either an OK count or a
    silent exclusion.
    """
    run = subprocess.run if run is None else run
    ps_bin = gh_which.safe_which("ps")
    if ps_bin is None:
        return "could-not-tell", "ps is not on PATH (expected on Windows)"
    rc, done, exc = _run_ps(run, ps_bin)
    if exc is not None:
        return "could-not-tell", "ps -eo pid,command did not run ({})".format(exc)
    if rc != 0:
        return "could-not-tell", "ps -eo pid,command exited {} -- {}".format(
            rc, (done.stderr or "").strip()[:200]
        )
    matches = _matching_processes(done.stdout or "")
    if not matches:
        return "counted", {"count": 0, "candidates_seen": 0}

    project_real = os.path.realpath(str(project_dir))
    attributed = 0
    unresolved = 0
    for pid, _command in matches:
        cwd = _process_cwd(pid, run)
        if cwd is None:
            unresolved += 1
            continue
        if os.path.realpath(cwd) == project_real:
            attributed += 1
    if unresolved and attributed == 0:
        return (
            "could-not-tell",
            "{} candidate process(es) matching `claude ... oss:tick` were found, but "
            "{} of them could not be attributed to a clone (working directory "
            "unresolvable on this platform/permission set)".format(
                len(matches), unresolved
            ),
        )
    return "counted", {"count": attributed, "candidates_seen": len(matches)}


def check_scheduler_processes(project_dir, config, run=None):
    """Report `scheduler_process_state`. WARNs on 2+ live scheduler
    processes against this clone -- the #1350 shape itself -- and on the
    could-not-tell state, never silently as OK. A count of 0 or 1 is OK:
    zero means nothing is sharing this clone right now, and one is this
    tick's own scheduler (or a lone maintainer session), neither a finding.
    """
    state, detail = scheduler_process_state(project_dir, run=run)
    if state == "could-not-tell":
        doctor.report(
            "WARN",
            "scheduler processes: could not be checked -- {}. UNKNOWN, not clean: "
            "nothing here has been shown to be free of a sibling scheduler "
            "sharing this clone (#1350).".format(detail),
        )
        return
    count = detail["count"]
    if count <= 1:
        doctor.report(
            "OK",
            "scheduler processes: {} live `claude ... oss:tick` process(es) against "
            "this clone.".format(count),
        )
        return
    doctor.report(
        "WARN",
        "scheduler processes: {} live `claude ... oss:tick` processes against this "
        "clone -- see #1350: a second scheduler sharing this clone can move HEAD, "
        "occupy worktrees or merge without this tick's own knowledge. Do not touch "
        "a branch or worktree you did not create until you have confirmed, by "
        "hand, whether it belongs to one of these.".format(count),
    )
