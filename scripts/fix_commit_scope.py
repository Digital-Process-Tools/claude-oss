"""Whether a fix-for-a-finding commit needs a second review pass (#1047).

An audit's subject is a diff at an instant; the fix for its own findings is
a later diff, and no mechanism makes that later diff a subject again by
default. On PR #921 a two-round re-audit found two real bugs in exactly
that unreviewed fix commit -- one where the earlier fix had *moved* the
defect rather than closed it, one a prose ambiguity introduced while
cutting bytes to stay under a budget ceiling. Nothing decided this fix
commit was worth a second look; the scheduler happened to choose to look.

This is deliberately not "review everything twice" -- most fix commits are
one line, and re-auditing them is waste #1047's own issue names explicitly.
What made PR #921's fix commit worth it was **scope**: seven files, a guard
changed, and prose rewritten under a byte ceiling.

Two of those three are checkable from a file list alone, and are mechanized
here:

- **file count** -- `FILE_COUNT_THRESHOLD` or more files touched by the fix
  commit. The threshold is a judgement call this module states rather than
  hides: three is chosen as a floor comfortably above a one-line fix and
  comfortably below "seven", not measured from any distribution.
- **a byte-budgeted file touched** -- the fix lands inside a file this repo
  already governs with its own ceiling (`agent_budgets.BUDGETS`,
  `command_budgets.BUDGETS`, `developer_phases.DOCUMENTS`,
  `skill_phases.DOCUMENTS`). A rewrite squeezed for bytes is exactly where
  PR #921's own second finding -- a sentence that parsed two ways -- came
  from, so any touch to one of these files crosses the line regardless of
  count.

**"A guard changed" is not mechanized, and this module does not pretend to
guess it.** Whether a touched function is a guard or a validator is a
judgement about behaviour, not something a file list can answer, so
`agents/developer/review-return.md` and `skills/manager/phases/review.md`
still ask for that half in prose.

Three states, never two, the same shape as every other checker in this
plugin: `needs-second-pass` (crossed a threshold below), `within-scope`
(checked and did not cross), `could-not-determine` (the file list itself
could not be read -- never folded into `within-scope`; an absence produced
by this tool must never render as an absence in the world).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_budgets  # noqa: E402
import command_budgets  # noqa: E402
import developer_phases  # noqa: E402
import gh_which  # noqa: E402
import skill_phases  # noqa: E402

#: See the module docstring's "file count" bullet for why 3, not a measured
#: value.
FILE_COUNT_THRESHOLD = 3


def budgeted_paths(root=None):
    """The union of every file this repo already governs with its own
    byte-budget table -- `root` is accepted for a future per-repo derivation
    and unused today, since every table above is this plugin's own, not a
    fact re-derived per checkout."""
    paths = set(agent_budgets.BUDGETS)
    paths.update(command_budgets.BUDGETS)
    paths.update(developer_phases.DOCUMENTS)
    paths.update(skill_phases.DOCUMENTS)
    return paths


def check(files, root=None):
    """`files` is an iterable of repo-relative paths the fix commit
    touched. Returns a dict with `state`, `reason`, `file_count` and
    `budgeted_files_touched`."""
    files = list(files)
    budgeted = sorted(set(files) & budgeted_paths(root))
    crosses_count = len(files) >= FILE_COUNT_THRESHOLD

    if crosses_count or budgeted:
        reasons = []
        if crosses_count:
            reasons.append(
                "touches {0} files (>= {1})".format(len(files), FILE_COUNT_THRESHOLD)
            )
        if budgeted:
            reasons.append(
                "touches a byte-budgeted file: {0}".format(", ".join(budgeted))
            )
        return {
            "state": "needs-second-pass",
            "reason": "; ".join(reasons),
            "file_count": len(files),
            "budgeted_files_touched": budgeted,
        }

    return {
        "state": "within-scope",
        "reason": "touches {0} file(s), none byte-budgeted".format(len(files)),
        "file_count": len(files),
        "budgeted_files_touched": [],
    }


def files_from_git(repo, base, head):
    """`git diff --name-only base..head` inside `repo`. Returns
    `(files, error)` -- `error` is `None` on success, a message otherwise.
    Never returns `([], None)` for a call that could not actually run: a
    quiet empty list here would render a broken repo identically to a fix
    commit that touched nothing.

    Resolves `git` via `gh_which.safe_which` rather than spawning the bare
    argv literal (#1157, #1165's own repo-wide sweep) -- a bare name reaches
    `CreateProcess` on Windows, which only auto-appends `.exe` and never
    `.cmd`/`.bat`, so a `git.cmd` shim on `PATH` is invisible to it.

    Decodes stdout with `encoding="utf-8", errors="replace"` (#1251) rather
    than bare `text=True`, which decodes under the runner's own locale
    codec at `errors="strict"` -- a path git prints that codec cannot
    represent would otherwise raise `UnicodeDecodeError`, escaping this
    function's own `except (OSError, subprocess.TimeoutExpired)` clause and
    this module's documented `(files, error)` contract entirely. Matches
    the same fix already applied at `tree_snapshot.py`, `batch_hint.py`,
    `ruff_ratchet.py`, `lane_setup.py` and `release_delta.py`."""
    git_bin = gh_which.safe_which("git")
    if git_bin is None:
        return None, "git not found on PATH"
    try:
        result = subprocess.run(
            [
                git_bin,
                "diff",
                "--name-only",
                # `--end-of-options` (git >= 2.24) closes option parsing
                # before the revision range is read, so a `base`/`head`
                # beginning with `-` (e.g. `--output=<path>`) is refused by
                # git as a bad option rather than reinterpreted as one --
                # unlike a trailing `--`, which only disambiguates a
                # pathspec section and does nothing for an option-shaped
                # token that comes before it (#1254).
                "--end-of-options",
                "{0}..{1}".format(base, head),
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or "git diff failed").strip()
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return files, None


def _build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Does a fix-for-a-finding commit cross the re-review threshold? (#1047)"
        )
    )
    parser.add_argument(
        "--repo", default=".", help="local repository to run `git diff` in"
    )
    parser.add_argument("--base", default=None, help="the commit the fix answers")
    parser.add_argument("--head", default=None, help="the fix commit itself")
    parser.add_argument(
        "--file",
        action="append",
        dest="files",
        default=None,
        metavar="PATH",
        help="a touched file, repeatable -- bypasses --base/--head entirely",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()

    if args.files is not None:
        files = args.files
    elif args.base and args.head:
        files, error = files_from_git(root, args.base, args.head)
        if error is not None:
            print("VERDICT: could-not-determine -- {0}".format(error))
            return 2
    else:
        print("VERDICT: could-not-determine -- neither --file nor --base/--head given")
        return 2

    result = check(files, root=root)
    print("VERDICT: {0} -- {1}".format(result["state"], result["reason"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
