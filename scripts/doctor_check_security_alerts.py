"""#760: the loop reads issues and pull requests and never the security tab, so
an open High finding is invisible to every tick. Sibling of #759's own
branch-protection check, written directly into its own module per the
per-check module convention (#497, #630) -- see the convention block at the
top of doctor.py, and see doctor_check_branch_protection.py, whose gating and
403-handling shape this reuses almost verbatim.

Three checks share one module, the same call `doctor_check_worktree_reap_
permission.py` already made for its own pair: they are one subject (is a
GitHub security-alert scanner turned on for this repo) asked about three
endpoints, not three unrelated subjects that happen to share a name.

**The four states are configuration states, never counts.** The issue is
explicit: "Any check written here that renders those four as a number is
worse than no check." `configured` covers a clean 200 AND a 200 whose body
carries open findings -- this module never reads the array for its length or
its contents, so a High finding sitting in the body is exactly as invisible
to this check as an empty one. That is deliberate and is the issue's own
second, separately-argued piece (a board read that actually surfaces a
finding) -- not this one.

**never-scanned vs disabled is the split the issue calls out as the one most
likely to get flattened.** Both render as HTTP 404 from `gh api`, and the only
signal available is the response body's own `message` text: GitHub's API
spells a deliberately-off setting as "... is disabled ..." (observed, this
repo, both for secret scanning and -- per GitHub's own published docs -- for
Dependabot alerts) and spells "nothing has ever scanned this repo" as
"no analysis found" (observed, this repo, code scanning). A 404 whose body
cannot be parsed, or carries no such wording, is read as `never-scanned`
rather than guessed at as `disabled` -- the narrower of the two claims, since
"deliberately turned off" is the one that must never be manufactured from
nothing.

A 403 is never folded into either 404 state, for the same reason #759's
`branch_protection_state` never folds a 403 into `not-protected`: a
permission-limited token and a repo where the scanner is not configured
cannot be told apart from a 403 alone.
"""

import json
import re
import shutil
import subprocess

import doctor


def _gh_api(path, run):
    """Run ``gh api <path>``, returning ``(returncode, stdout, stderr, exc)``.

    ``exc`` is set only when the process itself failed to start -- the shape
    `doctor_check_branch_protection._gh_api` already uses for the same call.
    """
    try:
        done = run(
            ["gh", "api", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", "", exc
    # #1019: NOT `universal_newlines=True` -- that decodes under `errors="strict"`
    # with the runner's own locale codec, and a byte that codec cannot represent
    # raises `UnicodeDecodeError` (a `ValueError`, escaping the `except` above)
    # straight out of what is meant to be a check that exits 0 always. Bytes,
    # decoded here with `errors="replace"` instead -- the same fix `doctor.py`'s
    # own two subprocess reads already carry for the identical trap.
    stdout = done.stdout.decode("utf-8", "replace") if isinstance(done.stdout, bytes) else (done.stdout or "")
    stderr = done.stderr.decode("utf-8", "replace") if isinstance(done.stderr, bytes) else (done.stderr or "")
    return done.returncode, stdout, stderr, None


_GH_API_HTTP_STATUS_RE = re.compile(r"HTTP (\d+)")


def _classify_gh_api_status(returncode, stdout, stderr):
    """``"ok"`` / ``"not-found"`` / ``"forbidden"`` / ``"unclassified"`` -- same
    derivation as `doctor_check_branch_protection._classify_gh_api_status`:
    `gh api` folds the HTTP status into its error text rather than exposing it
    as a field, so it is recovered from that text. Anything that is not 404 or
    403 is `unclassified` rather than guessed at.
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


def _is_disabled_body(stdout):
    """True only when the 404 body's own ``message`` field names this as a
    deliberately-off setting, rather than "nothing has scanned this repo yet".
    A body that does not parse, or carries no such wording, answers False --
    the narrower claim, since `disabled` asserts a deliberate choice that
    `never-scanned` does not.
    """
    try:
        body = json.loads(stdout or "{}")
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = body.get("message")
    return isinstance(message, str) and "disabled" in message.lower()


#: scanner name -> the `gh api` path suffix that answers it.
SCANNERS = {
    "code-scanning": "code-scanning/alerts",
    "dependabot": "dependabot/alerts",
    "secret-scanning": "secret-scanning/alerts",
}

SECURITY_SETTINGS_URL = "https://github.com/{}/settings/security_analysis"

#: #1065: the runnable `gh` command for each scanner, where one exists. The
#: `dependabot`/`secret-scanning` toggles are the SAME underlying settings
#: `doctor_check_security_settings.py` already offers commands for
#: (`vulnerability-alerts` and the nested `security_and_analysis` object
#: respectively) -- this module asks a different question (has it ever run?
#: see the module docstring), but the remedy that turns the toggle on is the
#: same call either way. `code-scanning` has no equivalent dedicated toggle
#: endpoint: enabling it means turning on a scanner, and `default-setup`
#: (PATCH `state=configured`) is the one call that does that without also
#: requiring a workflow file -- the same endpoint #1062 names for reading the
#: state this module's own `code-scanning` scanner cannot see.
_REMEDY_COMMANDS = {
    "code-scanning": "gh api -X PATCH repos/{}/code-scanning/default-setup -f state=configured",
    "dependabot": "gh api -X PUT repos/{}/vulnerability-alerts",
    "secret-scanning": "gh api -X PATCH repos/{} -f security_and_analysis[secret_scanning][status]=enabled",
}


def _resolve_slug(project_dir, config, run):
    """``(slug, reason)`` -- ``.oss.json``'s ``repo`` key, else the ``origin``
    remote. ``slug`` is ``None`` when it could not be resolved, with
    ``reason`` explaining why.

    Shared by `security_alert_state` and `_report_security_alert_check` so a
    slug resolved via the origin fallback still reaches the WARN remedy's
    settings-page link -- self-review finding: an earlier draft had
    `_report_security_alert_check` re-derive the slug from `config` alone,
    which silently dropped the link whenever the slug actually came from
    `origin` rather than from config.
    """
    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        return None, "the repo value in .oss.json is not a string"
    if slug:
        return slug, None
    return doctor._origin_slug(project_dir, run=run)


def security_alert_state(project_dir, scanner, config=None, run=None):
    """``"configured"`` / ``"never-scanned"`` / ``"disabled"`` / ``"could-not-tell"``
    for one of the three GitHub security-alert endpoints (#760).

    Gated on the same local facts `check_label_vocabulary` and #759's
    `branch_protection_state` already gate on -- `gh` on PATH, `origin`/config
    naming the repo. Raises ``ValueError`` for a ``scanner`` this module does
    not know, which is a caller bug (a typo in this file), not a repo state.
    """
    if scanner not in SCANNERS:
        raise ValueError("unknown scanner {!r} (expected one of {})".format(scanner, sorted(SCANNERS)))
    run = subprocess.run if run is None else run
    if shutil.which("gh") is None:
        return "could-not-tell", "gh is not on PATH"
    slug, reason = _resolve_slug(project_dir, config, run)
    if slug is None:
        return "could-not-tell", reason

    rc, out, err, exc = _gh_api("repos/{}/{}".format(slug, SCANNERS[scanner]), run)
    if exc is not None:
        return (
            "could-not-tell",
            "gh api .../{} did not run ({})".format(SCANNERS[scanner], exc),
        )
    status = _classify_gh_api_status(rc, out, err)
    if status == "ok":
        return (
            "configured",
            "{} is configured on {} and has run (HTTP 200)".format(scanner, slug),
        )
    if status == "forbidden":
        return (
            "could-not-tell",
            "reading {} for {} returned a permission error (HTTP 403), which "
            "renders identically to a token that cannot see alerts on a repo "
            "where the scanner IS configured -- not read as never-scanned or "
            "disabled".format(scanner, slug),
        )
    if status == "unclassified":
        return (
            "could-not-tell",
            "reading {} for {} returned an unrecognised response ({})".format(
                scanner, slug, (err or out).strip()[:200]
            ),
        )
    # status == "not-found": distinguish "disabled" from "never scanned" by the
    # body's own message text.
    if _is_disabled_body(out):
        return (
            "disabled",
            "{} is disabled on {} (HTTP 404, {})".format(scanner, slug, (out or "").strip()[:150]),
        )
    return (
        "never-scanned",
        "{} has never run on {} (HTTP 404, no analysis found)".format(scanner, slug),
    )


def _report_security_alert_check(project_dir, scanner, config=None, run=None):
    state, detail = security_alert_state(project_dir, scanner, config=config, run=run)
    if state == "configured":
        doctor.report("OK", "{}: {}".format(scanner, detail))
        return
    if state in ("never-scanned", "disabled"):
        run_ = subprocess.run if run is None else run
        slug, _reason = _resolve_slug(project_dir, config, run_)
        url = SECURITY_SETTINGS_URL.format(slug) if isinstance(slug, str) and slug else None
        # #1065: offer the runnable command where one exists, falling back to
        # the settings-page URL only when no slug is in hand to build it
        # from -- same shape as `doctor_check_security_settings.py`'s own
        # `_report_setting_check`.
        command = _REMEDY_COMMANDS.get(scanner)
        if command and isinstance(slug, str) and slug:
            remedy = "Run `{}`, or enable it from the repo's Settings > Code security and analysis page ({}).".format(
                command.format(slug), url
            )
        else:
            remedy = (
                "Enable it from the repo's Settings > Code security and analysis page{}.".format(
                    " ({})".format(url) if url else ""
                )
            )
        doctor.report("WARN", "{}: {} -- {}".format(scanner, detail, remedy))
        return
    doctor.report("WARN", "{}: could not tell -- {}".format(scanner, detail))


def check_code_scanning_alerts(project_dir, config=None, run=None):
    """Report only -- no `--apply`: the loop must never resolve, dismiss or act
    on an alert, per the issue's own reasoning, the same one `check_branch_
    protection` and the `no-changelog` label already follow.
    """
    _report_security_alert_check(project_dir, "code-scanning", config=config, run=run)


def check_dependabot_alerts(project_dir, config=None, run=None):
    _report_security_alert_check(project_dir, "dependabot", config=config, run=run)


def check_secret_scanning_alerts(project_dir, config=None, run=None):
    _report_security_alert_check(project_dir, "secret-scanning", config=config, run=run)
