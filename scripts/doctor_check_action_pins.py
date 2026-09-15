"""``check_action_pins`` -- doctor compares the two GitHub Action commit SHAs
pinned inside `scaffold.CHANGELOG_WORKFLOW` against the live tip of the major
tag they claim to track (#1519).

`scaffold.CHANGELOG_WORKFLOW` pins `actions/checkout` and `actions/setup-python`
to a commit SHA rather than a moving tag (#1462) -- correct, because a moving
tag lets a publisher repoint it under a receiving repository's own token with
no review anywhere in that repo. But the pin lives inside a Python string
literal, not a real `.github/workflows/*.yml` file in *this* repository, so
`.github/dependabot.yml`'s `github-actions` watch (confirmed by reading it:
`directory: /`) never sees it -- Dependabot only parses real workflow YAML it
finds on disk, never YAML embedded in a `.py` source string. The two SHAs rot
with nothing here to notice, and every repository this template scaffolds
into inherits whatever multi-majors-old commit the plugin happened to ship
with. This check is the comparison #1519 asks for: read the pin, read the
live tip of its own major tag, and say when they have drifted.

Third state, load-bearing: a live GitHub API read can fail for reasons that
have nothing to do with the pin -- no `gh` on PATH, no auth, rate-limited, the
network unreachable in a sandboxed test run. That must never render as
agreement. `doctor.unmeasured` is the one that says so out loud.

Follows the #497 relocation convention: reaches every shared name through
`import doctor` rather than `from doctor import name`, so a test that
monkeypatches `doctor.<name>` still reaches code called from here, and this
module is imported back into `doctor.py` immediately after its own
definition. Not a relocation -- there was never an inline version of this
check -- but the same module shape as every other `scripts/doctor_check_*.py`.

Must never repair. `doctor`'s contract is diagnose, exit 0, one VERDICT line --
nothing below writes to `scaffold.py` or anywhere else; the remedy is a
sentence telling a maintainer to re-pin the template by hand.
"""

import re
import subprocess

import doctor
import gh_which

#: (action, major tag) pairs this check watches -- named directly out of
#: CHANGELOG_WORKFLOW's own `uses:` lines, not a third copy of the tag chosen
#: independently of what the template actually pins.
WATCHED_ACTIONS = (
    ("actions/checkout", "v7"),
    ("actions/setup-python", "v7"),
)

#: Matches a `uses: owner/repo@<40-hex-sha> # vX.Y.Z` line the way
#: CHANGELOG_WORKFLOW writes one. The trailing comment is not optional here --
#: a bare 40-hex ref carries no evidence of what it was pinned to.
_USES_RE = re.compile(r"uses:\s*([\w./-]+)@([0-9a-f]{40})\s*#\s*(v[\w.]+)")


def _pinned_shas(workflow_text):
    """``{action: (sha, tag_comment)}`` parsed out of a workflow template's own
    `uses:` lines. Later matches for the same action win, matching the plain
    top-to-bottom read a maintainer re-pinning by hand would do."""
    pinned = {}
    for match in _USES_RE.finditer(workflow_text):
        action, sha, tag = match.groups()
        pinned[action] = (sha, tag)
    return pinned


def _live_commit_sha(gh_bin, action, ref):
    """The commit SHA `ref` (a tag or branch name) currently resolves to in
    `action`'s repository, read live via `gh api repos/{action}/commits/{ref}`.
    `None` if the call could not answer -- never raises. This endpoint answers
    for a tag or a branch alike, so it needs no branch on whether `ref` is an
    annotated or a lightweight tag, unlike the `git/refs/tags/{ref}` endpoint."""
    try:
        done = subprocess.run(
            [
                gh_bin,
                "api",
                "repos/{}/commits/{}".format(action, ref),
                "--jq",
                ".sha",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    sha = done.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    return sha


def check_action_pins():
    """Compare `scaffold.CHANGELOG_WORKFLOW`'s two pinned action SHAs against
    the live tip of the major tag each one's own trailing comment names.

    States:

    * ``OK`` -- every watched action's pinned SHA matches the live tip of its
      major tag.
    * ``WARN`` -- at least one has drifted. Named individually, with the
      remedy (re-pin `scaffold.CHANGELOG_WORKFLOW` by hand) spelled out,
      since nothing automated -- Dependabot included -- will ever catch this
      on its own.
    * ``WARN`` (via `doctor.unmeasured`) -- the template's `uses:` lines
      could not be found in the shape this check expects, so the comparison
      itself could not be attempted.
    * ``not-checked`` (via `doctor.unmeasured`) -- `scaffold.py` could not be
      imported, `gh` is not on PATH, or the live read did not answer for
      every watched action. Never folded into `OK`: an unread pin is not an
      agreeing one.
    """
    if doctor.scaffold is None:
        doctor.unmeasured("action pins", doctor.NO_SCAFFOLD)
        return
    workflow_text = getattr(doctor.scaffold, "CHANGELOG_WORKFLOW", None)
    if not isinstance(workflow_text, str):
        doctor.unmeasured(
            "action pins",
            "not checked -- scaffold.CHANGELOG_WORKFLOW is not a string in "
            "this install",
        )
        return
    pinned = _pinned_shas(workflow_text)
    missing = [action for action, _ in WATCHED_ACTIONS if action not in pinned]
    if missing:
        doctor.report(
            "WARN",
            "action pins: could not find a pinned `uses:` line for {} inside "
            "CHANGELOG_WORKFLOW -- the template may have changed shape since "
            "this check was written; it needs updating alongside it.".format(
                ", ".join(missing)
            ),
        )
        return
    gh_bin = gh_which.safe_which("gh")
    if gh_bin is None:
        doctor.unmeasured(
            "action pins",
            "not checked -- gh is not on PATH, so the live tag tip could not be read",
        )
        return
    drifted = []
    unresolved = []
    for action, major in WATCHED_ACTIONS:
        sha, tag_comment = pinned[action]
        live = _live_commit_sha(gh_bin, action, major)
        if live is None:
            unresolved.append(action)
            continue
        if live != sha:
            drifted.append(
                "{} is pinned to {} (# {}) but the live tip of {} is {}".format(
                    action, sha[:12], tag_comment, major, live[:12]
                )
            )
    if drifted:
        doctor.report(
            "WARN",
            "action pins: CHANGELOG_WORKFLOW's template has drifted from the "
            "live tag tip -- {}. Dependabot cannot see this: the pin lives "
            "inside a .py string, not a real workflow file. Re-pin "
            "scaffold.CHANGELOG_WORKFLOW by hand.".format("; ".join(drifted)),
        )
        return
    if unresolved:
        doctor.unmeasured(
            "action pins",
            "not checked for {} -- the GitHub API did not answer (no `gh` "
            "auth, rate-limited, or unreachable)".format(", ".join(unresolved)),
        )
        return
    doctor.report(
        "OK",
        "action pins: CHANGELOG_WORKFLOW's pinned SHAs for {} match the live "
        "tip of their major tag.".format(
            ", ".join(action for action, _ in WATCHED_ACTIONS)
        ),
    )
