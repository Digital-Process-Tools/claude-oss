"""#763: written directly into its own module, per the per-check module
convention (#497, #630) that a new check does not go into `doctor.py` at all
-- see the convention block at the top of doctor.py for the rule and
scripts/doctor_modules.py for the ratchet that enforces it. (This is a new
check, not a relocation of pre-existing inline code -- self-review finding:
an earlier draft of this docstring said "moved out of scripts/doctor.py",
which was true of `doctor_check_merge_permission.py`'s own move and false
here.)

Is the clone's current HEAD on `.oss.json`'s `default_branch`? The existing
`clone` check (`check_directory`, still in doctor.py) only ever reports the
CONFIGURED PATH; this asks the question that path never answers -- whether the
clone actually sitting there is on the branch it is supposed to be on, or was
left behind by `gh-pr-merge`'s own declined worktree/branch cleanup.

`doctor.py` imports `clone_head_state` and `check_clone_head` back out of this
module immediately after this docstring's own code is defined, the same
pattern `doctor_check_merge_permission.py` documents for its own checks --
so `doctor.check_clone_head` answers exactly as it does here, and a test's
`monkeypatch.setattr(doctor, ...)` reaches this module's code.
"""

import shutil
import subprocess

import doctor


def _git_run(project_dir, args, run):
    """``git -C <project_dir> <args>``, returning ``(returncode, stdout, stderr,
    exc)`` -- the same shape ``_gh_api`` uses, for the identical reason: a
    process that never started (`git` uninstalled mid-call, a permission
    error) must not be confused with an ordinary non-zero exit (no upstream
    configured, a branch that does not exist)."""
    try:
        done = run(
            ["git", "-C", str(project_dir)] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", "", exc
    return done.returncode, done.stdout, done.stderr, None


def clone_head_state(project_dir, config, run=None):
    """Is the clone's current HEAD on `.oss.json`'s `default_branch`? #763: the
    existing `clone` check (`check_directory`) only ever reports the configured
    PATH, so a clone `gh-pr-merge`'s own declined cleanup left sitting on a
    merged branch -- or simply behind -- renders identically to a healthy one.

    Three states, never two -- ``"on-default"`` / ``"on-other"`` /
    ``"could-not-tell"`` -- and the third is load-bearing for the reason it is
    everywhere else in this file: a detached HEAD is not on the default branch
    and is also not a stale feature branch, so a run that could not read HEAD
    at all must render neither OK nor a WARN naming a branch it never read.

    ``on-default``'s payload is a dict, not a string, because the caller needs
    both counts separately: ``{"branch": str, "ahead": int|None, "behind":
    int|None}``. Both are ``None`` -- not ``0`` -- when no upstream is
    configured at all (a repo that has never been pushed): that is a different
    fact from "even with an upstream", and defaulting it to 0 would print a
    stale clone's own detached history as confidently caught up.

    ``on-other``'s payload is ``{"branch": str, "remote": "exists"|"gone"|
    "unknown"}``. ``"gone"`` is the post-merge signature named in the issue --
    `gh-pr-merge`'s own cleanup declines to delete a branch a worktree still
    holds, and deletes the remote ref regardless, so a local branch whose
    remote is gone very likely already merged. ``"unknown"`` covers both "no
    `origin` remote at all" and "the remote read itself failed" -- a
    network-dependent `ls-remote` failing is not the same claim as a confirmed
    absence, so it is never collapsed into ``"gone"``.
    """
    run = subprocess.run if run is None else run
    if shutil.which("git") is None:
        return "could-not-tell", "git is not on PATH"
    default_branch = config.get("default_branch") if config else None
    if default_branch is not None and not isinstance(default_branch, str):
        return "could-not-tell", "the default_branch value in .oss.json is not a string"
    if not default_branch:
        return "could-not-tell", "no default_branch configured, so there is nothing to compare against"

    # `git symbolic-ref --short HEAD` rather than `rev-parse --abbrev-ref HEAD`:
    # the latter FAILS on an unborn branch (a repo with no commits yet -- "fatal:
    # ambiguous argument 'HEAD': unknown revision"), measured directly while
    # writing this check, which would have rendered a brand-new repo on the
    # correct branch as could-not-tell. `symbolic-ref` answers the branch name
    # with no commits required, and fails with a distinct, matchable message
    # ("HEAD is not a symbolic ref") specifically on a detached HEAD -- the one
    # case this function needs to name rather than lump in with "git failed".
    rc, out, err, exc = _git_run(project_dir, ["symbolic-ref", "--short", "HEAD"], run)
    if exc is not None:
        return "could-not-tell", "git symbolic-ref --short HEAD did not run ({})".format(exc)
    if rc != 0:
        if "not a symbolic ref" in (err or ""):
            return "could-not-tell", "HEAD is detached, so there is no branch to compare"
        return "could-not-tell", "git symbolic-ref --short HEAD failed -- {}".format(
            (err or out).strip()[:200] or "not a git repository"
        )
    branch = out.strip()
    if not branch:
        return "could-not-tell", "git symbolic-ref --short HEAD returned nothing"

    if branch == default_branch:
        ahead, behind = None, None
        rc_u, out_u, _err_u, exc_u = _git_run(
            project_dir, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], run
        )
        if exc_u is None and rc_u == 0 and out_u.strip():
            upstream = out_u.strip()
            rc_c, out_c, _err_c, exc_c = _git_run(
                project_dir,
                ["rev-list", "--left-right", "--count", "{}...HEAD".format(upstream)],
                run,
            )
            if exc_c is None and rc_c == 0:
                parts = out_c.split()
                if len(parts) == 2 and all(p.isdigit() for p in parts):
                    behind, ahead = int(parts[0]), int(parts[1])
        return "on-default", {"branch": branch, "ahead": ahead, "behind": behind}

    remote = "unknown"
    rc_r, out_r, _err_r, exc_r = _git_run(
        project_dir, ["remote", "get-url", "origin"], run
    )
    if exc_r is None and rc_r == 0 and out_r.strip():
        rc_ls, out_ls, _err_ls, exc_ls = _git_run(
            project_dir, ["ls-remote", "--exit-code", "--heads", "origin", branch], run
        )
        if exc_ls is None:
            if rc_ls == 0 and out_ls.strip():
                remote = "exists"
            elif rc_ls == 2:
                remote = "gone"
            # any other exit -- a network failure, a hung remote -- stays "unknown"
    return "on-other", {"branch": branch, "remote": remote}


def check_clone_head(project_dir, config, run=None):
    """Report `clone_head_state`. Deliberately WARNs on ANY positive `behind`
    count rather than past some staleness threshold -- #763's own author leaves
    this open, and the observed cost (a stale `.supertool.json` misread for two
    hours) came from staleness nobody had a chance to notice, not from a large
    count. A threshold would need an elapsed-time measurement this repo does
    not have across more than the one observed incident, and the WARN itself is
    cheap: it never fires when up to date, and no `--apply` remedy line is
    printed either, so a maintainer legitimately mid-branch reads exactly one
    extra line naming a fact they already know.
    """
    state, detail = clone_head_state(project_dir, config, run=run)
    if state == "on-default":
        branch, ahead, behind = detail["branch"], detail["ahead"], detail["behind"]
        if ahead is None or behind is None:
            doctor.report(
                "OK",
                "clone HEAD: on {} (no upstream configured, so ahead/behind counts "
                "are unavailable)".format(branch),
            )
            return
        if behind:
            doctor.report(
                "WARN",
                "clone HEAD: on {} but {} commit(s) behind {}@{{u}} -- config read "
                "from this clone may be stale ({} ahead)".format(
                    branch, behind, branch, ahead
                ),
            )
            return
        doctor.report(
            "OK",
            "clone HEAD: on {}, up to date ({} ahead, {} behind)".format(branch, ahead, behind),
        )
        return
    if state == "on-other":
        branch, remote = detail["branch"], detail["remote"]
        if remote == "gone":
            doctor.report(
                "WARN",
                "clone HEAD: on {} (not {}) -- its remote ref is gone, which very "
                "likely means the branch's pull request already merged and this "
                "clone was never moved back".format(branch, config.get("default_branch")),
            )
            return
        doctor.report(
            "WARN",
            "clone HEAD: on {} (not {}), remote ref {}".format(
                branch, config.get("default_branch"), remote
            ),
        )
        return
    doctor.report("WARN", "clone HEAD: could not tell -- {}".format(detail))

