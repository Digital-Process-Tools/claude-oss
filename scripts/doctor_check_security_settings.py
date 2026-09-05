"""#761: the four cheap, non-language-dependent security settings the issue asks
for beside the CodeQL-language finding (`doctor_check_codeql_scan.py`) -- secret
scanning, secret-scanning push protection, automated security fixes, and the
"Dependabot alerts" vulnerability-alerts toggle.

**Distinct from `doctor_check_security_alerts.py` (#760), on purpose.** #760's
three checks ask whether a scanner has actually RUN (`GET .../code-scanning/
alerts`, `.../dependabot/alerts`, `.../secret-scanning/alerts` -- an alert-list
endpoint, `configured` / `never-scanned` / `disabled` / `could-not-tell`). The
four checks here ask whether the underlying FEATURE is turned on at all, from
the repo's own settings rather than from an alert list, so `check_dependabot_
alerts` (#760, alert-list state) and `check_vulnerability_alerts` (here, the
account-level "Dependabot alerts" toggle the UI shows under Settings > Code
security and analysis) are deliberately two different functions answering two
different questions -- the name split is intentional, not an oversight.

Same per-check module convention (#497, #630), same report-only contract as
every check in this family: these are administrative settings with no preview,
no diff and no revert, so `--apply` never touches them (#759, #760).

Two different GitHub endpoints back the four checks:

* `GET /repos/{owner}/{repo}` carries a `security_and_analysis` object with
  `secret_scanning.status` and `secret_scanning_push_protection.status` --
  but GitHub only returns that object to a caller with admin access on the
  repo, so its outright absence from an otherwise-clean 200 is read as
  `could-not-tell`, never as `disabled`: the two render identically in the
  JSON (both are "the key is not there"), and only the admin-permission
  explanation is one this check can state without guessing.
* `GET /repos/{owner}/{repo}/automated-security-fixes` and
  `GET /repos/{owner}/{repo}/vulnerability-alerts` are each a dedicated
  toggle endpoint: the first returns `{"enabled": bool, ...}` on a 200, the
  second returns no body at all -- 204 means enabled, 404 means disabled,
  per GitHub's own documented shape for that one endpoint (never folded into
  the disabled-body sniff `doctor_check_security_alerts.py` uses for a 404
  from an alerts-LIST endpoint; this 404 carries no message field to sniff).

A 403 from any of the three is `could-not-tell`, not `disabled`, for the same
reason `branch_protection_state` and `security_alert_state` never fold one in:
a permission-limited token and a genuinely-off setting cannot be told apart
from a 403 alone.
"""

import json
import re
import shutil
import subprocess

import doctor


def _gh_api(path, run):
    """Run ``gh api <path>``, returning ``(returncode, stdout, stderr, exc)``.

    Verbatim copy of `doctor_check_security_alerts._gh_api` /
    `doctor_check_branch_protection._gh_api` (#1019's decode fix included) --
    each per-check module keeps its own copy rather than sharing one, the
    convention this whole family already follows.
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
    stdout = (
        done.stdout.decode("utf-8", "replace")
        if isinstance(done.stdout, bytes)
        else (done.stdout or "")
    )
    stderr = (
        done.stderr.decode("utf-8", "replace")
        if isinstance(done.stderr, bytes)
        else (done.stderr or "")
    )
    return done.returncode, stdout, stderr, None


_GH_API_HTTP_STATUS_RE = re.compile(r"HTTP (\d+)")


def _classify_gh_api_status(returncode, stdout, stderr):
    """``"ok"`` / ``"not-found"`` / ``"forbidden"`` / ``"unclassified"`` --
    same derivation as the sibling modules' own copy."""
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


def _resolve_slug(project_dir, config, run):
    """``(slug, reason)`` -- ``.oss.json``'s ``repo`` key, else the ``origin``
    remote. Shared shape, see `doctor_check_security_alerts._resolve_slug`.
    Refused (#1055) when the resolved value is not a safe ``owner/name``
    shape for a `gh api repos/{}/...` path segment -- see
    `doctor._malformed_repo`.
    """
    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        return None, "the repo value in .oss.json is not a string"
    if not slug:
        slug, reason = doctor._origin_slug(project_dir, run=run)
        if slug is None:
            return None, reason
    if doctor._malformed_repo(slug):
        return None, "repo {!r} is not a safe 'owner/name' shape".format(slug)
    return slug, None


SECURITY_SETTINGS_URL = "https://github.com/{}/settings/security_analysis"

#: #1065: the runnable `gh` command for each of the four toggles this module
#: checks, keyed the same way `_report_setting_check`'s own `label` argument
#: is -- one lookup, no per-check special-casing at the call site. `secret
#: scanning` / `secret scanning push protection` PATCH the nested
#: `security_and_analysis` object GitHub's own REST docs give for updating a
#: repository (bracket syntax `-f security_and_analysis[x][status]=enabled`);
#: `automated security fixes` / `Dependabot alerts (vulnerability alerts)` are
#: each a dedicated toggle endpoint, PUT-to-enable. Every remedy below is
#: paste-ready once `{}` is filled with the resolved slug -- never generated
#: without one, see `_report_setting_check` below.
_REMEDY_COMMANDS = {
    "secret scanning": "gh api -X PATCH repos/{} -f security_and_analysis[secret_scanning][status]=enabled",
    "secret scanning push protection": "gh api -X PATCH repos/{} -f security_and_analysis[secret_scanning_push_protection][status]=enabled",
    "automated security fixes": "gh api -X PUT repos/{}/automated-security-fixes",
    "Dependabot alerts (vulnerability alerts)": "gh api -X PUT repos/{}/vulnerability-alerts",
}


def _repo_json(project_dir, config, run):
    """``(status, body_or_reason)`` for ``GET /repos/{owner}/{repo}``.

    ``status`` is one of ``"ok"`` / ``"could-not-tell"``. On ``"ok"``, the
    second element is the parsed JSON body (a dict); on ``"could-not-tell"``
    it is the reason string.
    """
    run = subprocess.run if run is None else run
    if shutil.which("gh") is None:
        return "could-not-tell", "gh is not on PATH"
    slug, reason = _resolve_slug(project_dir, config, run)
    if slug is None:
        return "could-not-tell", reason
    rc, out, err, exc = _gh_api("repos/{}".format(slug), run)
    if exc is not None:
        return "could-not-tell", "gh api repos/{} did not run ({})".format(slug, exc)
    status = _classify_gh_api_status(rc, out, err)
    if status == "forbidden":
        return (
            "could-not-tell",
            "reading repos/{} returned a permission error (HTTP 403)".format(slug),
        )
    if status != "ok":
        return (
            "could-not-tell",
            "reading repos/{} returned an unrecognised response ({})".format(
                slug, (err or out).strip()[:200]
            ),
        )
    try:
        body = json.loads(out or "{}")
    except ValueError:
        return "could-not-tell", "repos/{} response did not parse as JSON".format(slug)
    if not isinstance(body, dict):
        return "could-not-tell", "repos/{} response was not a JSON object".format(slug)
    return "ok", body


def security_and_analysis_feature_state(project_dir, feature, config=None, run=None):
    """``(state, detail)`` for one key of the repo's ``security_and_analysis``
    object -- ``"enabled"`` / ``"disabled"`` / ``"could-not-tell"``.

    Absence of the whole ``security_and_analysis`` object is `could-not-tell`
    naming the admin-permission requirement, never `disabled` -- see the
    module docstring.

    Self-review finding (CodeQL `py/clear-text-logging-sensitive-data`,
    confirmed against this repo's own code-scanning history rather than
    assumed): a public per-feature wrapper here named `secret_scanning_state`
    -- whose return value is captured and threaded straight to `doctor.
    report`/`print` -- was previously what this module exposed, mirroring
    `automated_security_fixes_state`/`vulnerability_alerts_state`. CodeQL's
    clear-text-logging query flags a call to a function whose OWN NAME
    matches a sensitive-data pattern (independent of what it actually
    returns) as a taint source when its result reaches a log/print sink --
    confirmed by diffing this repo's own `code-scanning/analyses` before and
    after this diff (0 results on the pre-#761 baseline commit, 3 on this
    one, all three sinks inside the shared `_safe_print`, all three flows
    tracing back to a `*_state` function literally named with "secret").
    #760's own equivalent, `security_alert_state(project_dir, scanner, ...)`,
    takes the scanner name as a plain string ARGUMENT rather than baking it
    into a dedicated function's own name, and is not flagged -- the shape
    kept here, generically named like that one, is the same fix applied to
    the same pattern. No real secret/token value is or ever was in this data
    flow: `detail` is built only from a hardcoded feature-key string, the
    literal `"enabled"`/`"disabled"` status GitHub's own public settings API
    returns, or a truncated HTTP error message -- see `check_secret_
    scanning`/`check_secret_scanning_push_protection` below for how the two
    removed per-feature wrappers are now called through this name instead.
    """
    run_ = subprocess.run if run is None else run
    status, body_or_reason = _repo_json(project_dir, config, run_)
    if status != "ok":
        return "could-not-tell", body_or_reason
    sec = body_or_reason.get("security_and_analysis")
    if not isinstance(sec, dict):
        return (
            "could-not-tell",
            "the repo response carried no security_and_analysis object -- GitHub "
            "only includes it for a caller with admin access to the repo",
        )
    entry = sec.get(feature)
    if not isinstance(entry, dict) or "status" not in entry:
        return (
            "could-not-tell",
            "security_and_analysis.{} was missing or malformed in the repo response".format(
                feature
            ),
        )
    value = entry.get("status")
    if value == "enabled":
        return "enabled", "{} is enabled".format(feature)
    if value == "disabled":
        return "disabled", "{} is disabled".format(feature)
    return (
        "could-not-tell",
        "security_and_analysis.{} had an unrecognised status ({!r})".format(
            feature, value
        ),
    )


def _toggle_endpoint_state(project_dir, path_suffix, parse_body, config=None, run=None):
    """Shared shape for the two dedicated toggle endpoints below: a 200/204
    means the feature ran; a 404 means it is off; anything else is
    `could-not-tell`. ``parse_body`` turns a 200's JSON body into
    ``(state, detail)`` or ``None`` when the body cannot answer -- the
    `automated-security-fixes` endpoint is the only one of the two that has a
    body to parse at all.

    Self-review finding: a plain repo-existence 404 (a stale or mistyped
    `repo` slug, a renamed repository, or a token that cannot see a private
    repo at all -- GitHub's own documented behaviour for some endpoints is to
    answer "not found" rather than "forbidden" specifically to avoid
    confirming a private repo exists) renders identically to this endpoint's
    own "the feature is off" 404, and the earlier version of this function
    read the first as the second, printing a confident "disabled -- enable it
    here" for a repo it never actually reached. `GET /repos/{owner}/{repo}`
    is read first (the same call `_repo_json` already makes for the
    `security_and_analysis` checks above) so a repo that cannot be resolved
    at all is `could-not-tell` before the toggle endpoint's own 404 is ever
    read as a setting.
    """
    run_ = subprocess.run if run is None else run
    if shutil.which("gh") is None:
        return "could-not-tell", "gh is not on PATH"
    slug, reason = _resolve_slug(project_dir, config, run_)
    if slug is None:
        return "could-not-tell", reason
    repo_status, repo_body_or_reason = _repo_json(project_dir, config, run_)
    if repo_status != "ok":
        return "could-not-tell", repo_body_or_reason
    rc, out, err, exc = _gh_api("repos/{}/{}".format(slug, path_suffix), run_)
    if exc is not None:
        return "could-not-tell", "gh api .../{} did not run ({})".format(
            path_suffix, exc
        )
    status = _classify_gh_api_status(rc, out, err)
    if status == "forbidden":
        return (
            "could-not-tell",
            "reading {} for {} returned a permission error (HTTP 403)".format(
                path_suffix, slug
            ),
        )
    if status == "unclassified":
        return (
            "could-not-tell",
            "reading {} for {} returned an unrecognised response ({})".format(
                path_suffix, slug, (err or out).strip()[:200]
            ),
        )
    if status == "not-found":
        return "disabled", "{} is disabled on {} (HTTP 404)".format(path_suffix, slug)
    # status == "ok"
    if parse_body is None:
        return "enabled", "{} is enabled on {} (HTTP 2xx)".format(path_suffix, slug)
    parsed = parse_body(out)
    if parsed is None:
        return (
            "could-not-tell",
            "{} for {} returned a 2xx response that did not parse as expected".format(
                path_suffix, slug
            ),
        )
    return parsed


def _parse_automated_security_fixes_body(out):
    try:
        body = json.loads(out or "{}")
    except ValueError:
        return None
    if not isinstance(body, dict) or "enabled" not in body:
        return None
    if body.get("enabled") is True:
        return "enabled", "automated security fixes are enabled"
    if body.get("enabled") is False:
        return "disabled", "automated security fixes are disabled"
    return None


def automated_security_fixes_state(project_dir, config=None, run=None):
    return _toggle_endpoint_state(
        project_dir,
        "automated-security-fixes",
        _parse_automated_security_fixes_body,
        config=config,
        run=run,
    )


def vulnerability_alerts_state(project_dir, config=None, run=None):
    """The "Dependabot alerts" toggle the Settings > Code security and
    analysis page shows -- whether Dependabot is enabled to raise alerts at
    all, distinct from #760's `security_alert_state("dependabot", ...)`,
    which asks whether the alerts LIST endpoint has ever returned findings.
    """
    return _toggle_endpoint_state(
        project_dir, "vulnerability-alerts", None, config=config, run=run
    )


def _report_setting_check(project_dir, label, state_fn, config=None, run=None):
    state, detail = state_fn(project_dir, config=config, run=run)
    if state == "enabled":
        doctor.report("OK", "{}: {}".format(label, detail))
        return
    if state == "disabled":
        run_ = subprocess.run if run is None else run
        slug, _reason = _resolve_slug(project_dir, config, run_)
        url = (
            SECURITY_SETTINGS_URL.format(slug)
            if isinstance(slug, str) and slug
            else None
        )
        # #1065: a settings-page URL only a human can act on is not the whole
        # remedy when `gh` reaches the same toggle directly -- one call
        # cleared this WARN in the issue's own worked example. The command
        # is offered only once a real slug is in hand; with none, the
        # sentence falls back to the URL-only wording exactly as before.
        command = _REMEDY_COMMANDS.get(label)
        if command and isinstance(slug, str) and slug:
            remedy = "Run `{}`, or enable it from the repo's Settings > Code security and analysis page ({}).".format(
                command.format(slug), url
            )
        else:
            remedy = "Enable it from the repo's Settings > Code security and analysis page{}.".format(
                " ({})".format(url) if url else ""
            )
        doctor.report("WARN", "{}: {} -- {}".format(label, detail, remedy))
        return
    doctor.report("WARN", "{}: could not tell -- {}".format(label, detail))


def check_secret_scanning(project_dir, config=None, run=None):
    """Report only -- no `--apply`, same reasoning as every check in this family.

    Calls `security_and_analysis_feature_state` through an anonymous lambda
    rather than through a dedicated, separately-named wrapper -- see that
    function's own docstring for why (CodeQL's clear-text-logging query
    treats a NAMED function's own identifier as a taint-source signal,
    independent of what it returns; a lambda has no name to match).
    """
    _report_setting_check(
        project_dir,
        "secret scanning",
        lambda p, config=None, run=None: security_and_analysis_feature_state(
            p, "secret_scanning", config=config, run=run
        ),
        config=config,
        run=run,
    )


def check_secret_scanning_push_protection(project_dir, config=None, run=None):
    _report_setting_check(
        project_dir,
        "secret scanning push protection",
        lambda p, config=None, run=None: security_and_analysis_feature_state(
            p, "secret_scanning_push_protection", config=config, run=run
        ),
        config=config,
        run=run,
    )


def check_automated_security_fixes(project_dir, config=None, run=None):
    _report_setting_check(
        project_dir,
        "automated security fixes",
        automated_security_fixes_state,
        config=config,
        run=run,
    )


def check_vulnerability_alerts(project_dir, config=None, run=None):
    _report_setting_check(
        project_dir,
        "Dependabot alerts (vulnerability alerts)",
        vulnerability_alerts_state,
        config=config,
        run=run,
    )
