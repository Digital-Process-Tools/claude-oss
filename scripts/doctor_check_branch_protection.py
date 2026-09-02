"""#759: written directly into its own module, per the per-check module
convention (#497, #630) that a new check does not go into `doctor.py` at all
-- see the convention block at the top of doctor.py for the rule and
scripts/doctor_modules.py for the ratchet that enforces it. (This is a new
check, not a relocation of pre-existing inline code -- self-review finding:
an earlier draft of this docstring said "moved out of scripts/doctor.py",
which was true of `doctor_check_merge_permission.py`'s own move and false
here.)

Is the default branch actually protected, or is "merge on green" advisory?
Gated on the same local facts `check_label_vocabulary` (still in doctor.py)
already gates on -- `gh` on PATH, `origin`/config naming the repo. Report only:
no `--apply`, per the issue's own reasoning that an administrative setting with
no preview, no diff and no revert is not something a diagnostic should write.

`doctor.py` imports the names below back out of this module immediately after
this docstring's own code is defined, the same pattern
`doctor_check_merge_permission.py` documents for its own checks -- so
`doctor.check_branch_protection` answers exactly as it does here, and a test's
`monkeypatch.setattr(doctor, ...)` reaches this module's code.
"""

import json
import re
import shutil
import subprocess

import doctor


def _gh_api(path, run):
    """Run ``gh api <path>``, returning ``(returncode, stdout, stderr, exc)``.

    ``exc`` is set only when the process itself failed to start -- the shape
    ``label_vocabulary_state`` already uses for its own ``gh`` calls. A non-zero
    ``returncode`` with ``exc`` still ``None`` is an ordinary HTTP error response,
    which the caller classifies from ``stderr`` rather than treating as a failure
    to run.
    """
    try:
        done = run(
            ["gh", "api", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", "", exc
    return done.returncode, done.stdout, done.stderr, None


_GH_API_HTTP_STATUS_RE = re.compile(r"HTTP (\d+)")


def _classify_gh_api_status(returncode, stdout, stderr):
    """``"ok"`` / ``"not-found"`` / ``"forbidden"`` / ``"unclassified"``.

    #759's own comment: a 404 and a 403 from a GitHub settings endpoint answer
    two different questions -- "this does not exist" versus "you may not look" --
    and `gh api` reports both as a non-zero exit with the HTTP status folded into
    its error text (``gh: <message> (HTTP <status>)``), never as a distinct
    field this function can read structurally. So the status code is recovered
    from that text. Anything that is not 404 or 403 -- a 401, a 5xx, a network
    error with no HTTP status at all -- is ``unclassified`` rather than guessed
    at either way; the caller folds every non-``ok``, non-``not-found`` answer
    into `could-not-tell`.
    """
    if returncode == 0:
        return "ok"
    match = _GH_API_HTTP_STATUS_RE.search((stderr or "") + " " + (stdout or ""))
    if not match:
        return "unclassified"
    if match.group(1) == "404":
        return "not-found"
    if match.group(1) == "403":
        return "forbidden"
    return "unclassified"


SETTINGS_PAGE_URL = "https://github.com/{}/settings/branches"


def branch_protection_state(project_dir, config=None, run=None):
    """Is the default branch actually protected? ``"protected"`` /
    ``"not-protected"`` / ``"could-not-tell"``, gated on the same local facts
    `check_label_vocabulary` already gates on (`gh` on PATH, `origin`/config
    naming the repo) -- #759.

    Both the classic protection endpoint and `rulesets` are read before
    concluding `not-protected`: a repo can be covered by a ruleset while
    `branches/<b>/protection` 404s, so reading only the first would report a
    protected repo as bare (the issue's own worked example).

    The state most likely to be got wrong, per the issue's own comment: a 404
    from the protection endpoint and a 403 render as two different HTTP
    responses from `gh api`, and only the 404 is read as `not-protected` here.
    A 403 -- "insufficient permission to read this repo's settings" -- goes to
    `could-not-tell`, deliberately never folded into `not-protected`, because a
    permission-limited token and a genuinely bare repo cannot be told apart
    from that response alone. The same split applies to the `rulesets` read:
    its own 403 stops the answer at `could-not-tell` too, even after a clean
    404 from protection, because a 200 carrying an empty list is the only
    response this function treats as a conclusive "no rulesets".
    """
    run = subprocess.run if run is None else run
    if shutil.which("gh") is None:
        return "could-not-tell", "gh is not on PATH"
    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        return "could-not-tell", "the repo value in .oss.json is not a string"
    if not slug:
        slug, reason = doctor._origin_slug(project_dir, run=run)
        if slug is None:
            return "could-not-tell", reason
    branch = (config or {}).get("default_branch") if config else None
    if branch is not None and not isinstance(branch, str):
        return "could-not-tell", "the default_branch value in .oss.json is not a string"
    if not branch:
        return (
            "could-not-tell",
            "no default_branch configured, so which branch to check is unknown",
        )

    rc, out, err, exc = _gh_api("repos/{}/branches/{}/protection".format(slug, branch), run)
    if exc is not None:
        return (
            "could-not-tell",
            "gh api .../branches/{}/protection did not run ({})".format(branch, exc),
        )
    status = _classify_gh_api_status(rc, out, err)
    if status == "ok":
        return "protected", "classic branch protection is enabled on {}".format(branch)
    if status == "forbidden":
        return (
            "could-not-tell",
            "reading branch protection for {} returned a permission error (HTTP "
            "403), which renders identically to a token lacking admin access on "
            "a repo that IS protected -- not read as unprotected".format(branch),
        )
    if status == "unclassified":
        return (
            "could-not-tell",
            "reading branch protection for {} returned an unrecognised response "
            "({})".format(branch, (err or out).strip()[:200]),
        )

    # status == "not-found": the protection endpoint alone cannot conclude
    # "not protected" -- a ruleset can cover the branch while this 404s.
    rc2, out2, err2, exc2 = _gh_api("repos/{}/rulesets".format(slug), run)
    if exc2 is not None:
        return "could-not-tell", "gh api .../rulesets did not run ({})".format(exc2)
    status2 = _classify_gh_api_status(rc2, out2, err2)
    if status2 == "forbidden":
        return (
            "could-not-tell",
            "reading rulesets for {} returned a permission error (HTTP "
            "403)".format(slug),
        )
    if status2 != "ok":
        return (
            "could-not-tell",
            "reading rulesets for {} failed ({})".format(slug, (err2 or out2).strip()[:200]),
        )
    try:
        rulesets = json.loads(out2 or "[]")
    except ValueError:
        return "could-not-tell", "rulesets response for {} did not parse as JSON".format(slug)
    if not isinstance(rulesets, list):
        return "could-not-tell", "rulesets response for {} was not a list".format(slug)
    # Self-review finding: the list endpoint's own entries carry an
    # `enforcement` field ("active" / "disabled" / "evaluate"), and a ruleset
    # saved as disabled or still in evaluate mode enforces nothing -- so
    # counting the list's mere non-emptiness as "protected" would read a repo
    # whose only ruleset is a draft exactly like one that is genuinely covered,
    # the same collapse this function already refuses for the 403 case, one
    # level down. Entries that are not a dict, or omit `enforcement` entirely,
    # are NOT counted as active -- an unrecognised shape earns no benefit of
    # the doubt here, the same asymmetry `_classify_gh_api_status` applies to
    # an HTTP status this function cannot place.
    active = [
        item for item in rulesets
        if isinstance(item, dict) and item.get("enforcement") == "active"
    ]
    if active:
        return (
            "protected",
            "{} active ruleset(s) apply to {} (classic branch protection is not "
            "enabled, but a ruleset covers it)".format(len(active), branch),
        )
    return (
        "not-protected",
        "{} has no classic branch protection and no active rulesets".format(branch),
    )


def check_branch_protection(project_dir, config=None, run=None):
    """Report only -- no `--apply`, per the issue's own reasoning: an
    administrative setting with no preview, no diff and no revert is not
    something this diagnostic should ever write.
    """
    state, detail = branch_protection_state(project_dir, config=config, run=run)
    if state == "protected":
        doctor.report("OK", "branch protection: {}".format(detail))
        return
    if state == "not-protected":
        slug = (config or {}).get("repo") if config else None
        url = SETTINGS_PAGE_URL.format(slug) if isinstance(slug, str) and slug else None
        remedy = (
            "Configure a branch protection rule or ruleset requiring the CI "
            "checks before merge at {}.".format(url)
            if url
            else "Configure a branch protection rule or ruleset requiring the CI "
            "checks before merge, from the repo's Settings > Branches page."
        )
        doctor.report("WARN", "branch protection: {} -- {} {}".format(detail, "not enforced.", remedy))
        return
    doctor.report("WARN", "branch protection: could not tell -- {}".format(detail))

