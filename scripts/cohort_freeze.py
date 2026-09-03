#!/usr/bin/env python3
"""Freeze a cohort: label every issue open at a release with `cohort-N` (#917).

The hand process this replaces reads "issues open **now**" -- and `now` is
whenever the maintainer got to it. Measured on `v0.20.0` in one afternoon:
tag-object time gave 27, release-publish time gave 30, an hour later gave 32.
Same label, three different memberships, because a hand freeze records when it
ran rather than what it claims to record.

**Membership is derived from the tag object's own `tagger.date`, never from
`now`.** `gh api repos/{repo}/git/refs/tags/{tag}` names the object a tag ref
points at; for an annotated tag (`object.type == "tag"`) that object itself
carries `tagger.date` at `gh api repos/{repo}/git/tags/{sha}`. A lightweight
tag -- `object.type == "commit"` -- carries no tagger at all, so the fallback
is the pointed-at commit's own `committer.date`
(`gh api repos/{repo}/git/commits/{sha}`); this repo's own tags are annotated
(verified against `v0.20.0` while writing this), so the fallback is exercised
by test only, not by anything this repo actually produces today.

**Boundary: an issue belongs to `cohort-N` if it was created at or before the
cutoff, and was either still open then or closed strictly after it.** Closed
*at* the exact cutoff instant is treated as not-open-then and excluded --
"closed after it" per the issue, read literally rather than as "at or after."
The boundary is not expected to matter in practice (GitHub timestamps carry
one-second resolution and a real coincidence is unlikely); it has to be
unambiguous regardless, and this module and its tests pick the exclusive
reading consistently.

Timestamps are compared as ISO-8601 UTC strings (`...Z`), never parsed into
`datetime` objects: every timestamp from the GitHub REST API in this module
shares that exact format and width, so a plain string compare is correct and
sidesteps `datetime.fromisoformat`'s refusal of the trailing `Z` on Python
before 3.11 -- this repository's own floor is 3.9 (`CLAUDE.md`).

Three states, and the third is the point -- this repository's own defect
class, applied to its own bookkeeping. A check that cannot look has to say
so, because a cohort nobody could measure and a cohort that is genuinely
empty must never render the same:

  frozen            issues were labelled (or, on a dry run, would be)
  already-frozen    every member already carries the label -- re-running
                     is the ordinary case, not the exception, and is a no-op
  could-not-read     the tag could not be resolved, the issue list could not
                     be read, current label membership could not be read, or
                     a write failed partway -- NEVER an empty cohort. `state`
                     is the signal to read, not the shape of `count`: it is
                     `None` when the read failed before anything was
                     computed, and the already-computed value when a later
                     step (reading current labels, writing one) failed
                     partway. A real empty cohort is `already-frozen` with
                     `count == 0`, an int -- always distinguishable from
                     `could-not-read` by `state`.

Dry run by default -- `--execute` is required to actually write a label, since
an unqualified run touches every open issue on the tracker. `pull_request` is
excluded server-side (`select(.pull_request == null)`): the REST issues
listing mixes issues and pull requests in one endpoint, and only issues carry
cohort labels.

**Multi-cohort labels are correct and this module never removes one.** An
issue open across several releases legitimately carries several `cohort-N`
labels (`#383` carries eleven, as of this writing) -- `apply_labels` only ever
adds, `--add-label`, never `--set-label` or a remove.

Not in scope, per the issue: backfilling cohorts 1-15 from tag timestamps.
Recomputing history that was frozen by hand at its own time would silently
rewrite it to a different, more "accurate" history -- a separate decision
with its own argument, not smuggled in here. This module only makes a
*future* freeze reproducible.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CONFIG_NAME = ".oss.json"

STATE_FROZEN = "frozen"
STATE_ALREADY = "already-frozen"
STATE_COULD_NOT_READ = "could-not-read"

FREEZE_STATES = (STATE_FROZEN, STATE_ALREADY, STATE_COULD_NOT_READ)

EXIT_OK = 0
EXIT_COULD_NOT_READ = 3

LABEL_PREFIX = "cohort-"

ISSUES_LISTING_JQ = ".[] | select(.pull_request == null) | {number, created_at, closed_at}"

DEFAULT_TIMEOUT = 60


def _command_text(command):
    return " ".join(command)


def _decode_output(raw):
    """Decode a subprocess's bytes for display. Never raises. (#112's shape,
    reintroduced here and closed the same way.)

    None of the four `gh` call sites below pass `universal_newlines=True` (or its
    modern spelling `text=True`) to `run` -- that flag makes `subprocess` decode with
    the *locale* encoding, strictly, and `UnicodeDecodeError` is a `ValueError`, so it
    walks straight past every `except (OSError, subprocess.SubprocessError)` guarding
    these calls. What they carry is free text authored by whoever cut the tag or filed
    the issue -- `tagger.name`, a commit message, an issue body byte GitHub echoes back
    -- the one place a byte the runner's locale cannot decode is ordinary rather than
    exotic. `scripts/oss_config.py`'s own `_decode_output` (#112) is this exact fix,
    already shipped once in this repo; this is a second, independent copy rather than
    an import, because reaching into `oss_config` from here for four lines would be a
    cross-module coupling this file does not otherwise have.

    UTF-8 is named rather than inherited: GitHub's API speaks UTF-8, while a locale is
    a property of the machine *reading* the output, not of the process that wrote it.
    `replace` rather than `surrogateescape`, since this text ends up in a `reason`
    string that may be printed -- a lone surrogate would only move the crash from the
    decode here to a later `print`.
    """
    if raw is None:
        return ""
    if not isinstance(raw, bytes):
        return raw
    return raw.decode("utf-8", "replace")


def _gh_api_json(gh, path_args, run, timeout=25):
    """Run ``gh api <path_args...>`` and parse the JSON it prints.

    Returns ``(state, data, reason)``. ``state`` is ``"ok"`` or
    ``"could-not-read"`` -- never a third thing, and never an exception raised
    out of this function: a `gh` that is not on PATH, a non-zero exit (a 404,
    a 403, a rate limit -- `gh` folds all of those into a non-zero exit with
    the HTTP status in its stderr text, so this does not try to tell them
    apart further than the caller's own reason string does) and unparseable
    stdout are all `could-not-read` with a reason naming which.
    """
    command = [gh, "api"] + list(path_args)
    try:
        done = run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "could-not-read", None, "{} did not run ({})".format(
            _command_text(command), exc
        )
    stdout = _decode_output(done.stdout)
    stderr = _decode_output(done.stderr)
    if done.returncode != 0:
        message = (stderr or stdout or "").strip()
        return "could-not-read", None, "{} failed: {}".format(
            _command_text(command), message
        )
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return "could-not-read", None, "{} printed text that is not JSON".format(
            _command_text(command)
        )
    return "ok", data, ""


def resolve_tag_timestamp(repo, tag, gh, run):
    """The instant `tag` was cut, as the tag object's own `tagger.date` (or,
    for a lightweight tag, the pointed-at commit's `committer.date`).

    Returns ``{"state": "ok"/"could-not-read", "timestamp": str or None,
    "reason": str}``. Never raises -- every `gh` failure, at either API call,
    folds into `could-not-read` with a reason naming which call and why.
    """
    ref_path = "repos/{}/git/refs/tags/{}".format(repo, tag)
    state, data, reason = _gh_api_json(gh, [ref_path], run)
    if state != "ok":
        return {"state": "could-not-read", "timestamp": None, "reason": reason}

    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(obj, dict) or "sha" not in obj or "type" not in obj:
        return {
            "state": "could-not-read",
            "timestamp": None,
            "reason": "{} did not carry an object.sha/object.type".format(ref_path),
        }

    sha = obj["sha"]
    kind = obj["type"]

    if kind == "tag":
        tag_path = "repos/{}/git/tags/{}".format(repo, sha)
        state2, data2, reason2 = _gh_api_json(gh, [tag_path], run)
        if state2 != "ok":
            return {"state": "could-not-read", "timestamp": None, "reason": reason2}
        tagger = data2.get("tagger") if isinstance(data2, dict) else None
        date = tagger.get("date") if isinstance(tagger, dict) else None
        if not date:
            return {
                "state": "could-not-read",
                "timestamp": None,
                "reason": "{} carried no tagger.date".format(tag_path),
            }
        return {"state": "ok", "timestamp": date, "reason": ""}

    if kind == "commit":
        # A lightweight tag: the ref points straight at a commit, and there
        # is no tag object to carry a `tagger` at all. The commit's own
        # committer date is the closest available instant.
        commit_path = "repos/{}/git/commits/{}".format(repo, sha)
        state2, data2, reason2 = _gh_api_json(gh, [commit_path], run)
        if state2 != "ok":
            return {"state": "could-not-read", "timestamp": None, "reason": reason2}
        committer = data2.get("committer") if isinstance(data2, dict) else None
        date = committer.get("date") if isinstance(committer, dict) else None
        if not date:
            return {
                "state": "could-not-read",
                "timestamp": None,
                "reason": "{} carried no committer.date".format(commit_path),
            }
        return {"state": "ok", "timestamp": date, "reason": ""}

    return {
        "state": "could-not-read",
        "timestamp": None,
        "reason": "{} points at a {}, neither a tag object nor a commit".format(
            ref_path, kind
        ),
    }


def cohort_members(issues, cutoff):
    """Issue numbers created at or before `cutoff`, and either still open then
    or closed strictly after it. See the module docstring for the boundary
    reasoning. `issues` rows need only `number`, `created_at`, `closed_at`.
    """
    members = []
    for row in issues:
        created = row.get("created_at")
        if not isinstance(created, str) or created > cutoff:
            continue
        closed = row.get("closed_at")
        if closed is not None and closed <= cutoff:
            continue
        members.append(row["number"])
    return sorted(members)


def fetch_issues(repo, gh, run, timeout=DEFAULT_TIMEOUT):
    """Every issue on the tracker (open and closed), `{number, created_at,
    closed_at}` each -- pull requests excluded server-side. Paginated by
    `gh api --paginate`, one compact JSON object per line, which is why lines
    concatenate safely across pages the way a raw `--paginate` array would not.
    """
    command = [
        gh,
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(repo),
        "-f",
        "state=all",
        "-f",
        "per_page=100",
        "--jq",
        ISSUES_LISTING_JQ,
    ]
    try:
        done = run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "state": "could-not-read",
            "issues": None,
            "reason": "{} did not run ({})".format(_command_text(command), exc),
        }
    stdout = _decode_output(done.stdout)
    stderr = _decode_output(done.stderr)
    if done.returncode != 0:
        message = (stderr or stdout or "").strip()
        return {
            "state": "could-not-read",
            "issues": None,
            "reason": "{} failed: {}".format(_command_text(command), message),
        }

    issues = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return {
                "state": "could-not-read",
                "issues": None,
                "reason": "a line of {} was not valid JSON: {!r}".format(
                    _command_text(command), line[:120]
                ),
            }
        if not isinstance(row, dict) or "number" not in row or "created_at" not in row:
            return {
                "state": "could-not-read",
                "issues": None,
                "reason": "a row from {} was missing number/created_at".format(
                    _command_text(command)
                ),
            }
        issues.append(row)
    return {"state": "ok", "issues": issues, "reason": ""}


def label_members(repo, label, gh, run, timeout=DEFAULT_TIMEOUT):
    """Issue numbers that already carry `label` (open and closed) -- what the
    freeze must treat as already done, for idempotency.
    """
    command = [
        gh,
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(repo),
        "-f",
        "state=all",
        "-f",
        "labels={}".format(label),
        "-f",
        "per_page=100",
        "--jq",
        ".[] | select(.pull_request == null) | .number",
    ]
    try:
        done = run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "state": "could-not-read",
            "numbers": None,
            "reason": "{} did not run ({})".format(_command_text(command), exc),
        }
    stdout = _decode_output(done.stdout)
    stderr = _decode_output(done.stderr)
    if done.returncode != 0:
        message = (stderr or stdout or "").strip()
        return {
            "state": "could-not-read",
            "numbers": None,
            "reason": "{} failed: {}".format(_command_text(command), message),
        }

    numbers = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            numbers.append(int(line))
        except ValueError:
            return {
                "state": "could-not-read",
                "numbers": None,
                "reason": "a line of {} was not a number: {!r}".format(
                    _command_text(command), line[:120]
                ),
            }
    return {"state": "ok", "numbers": numbers, "reason": ""}


def apply_labels(repo, label, numbers, gh, run, timeout=25):
    """Add `label` to each issue in `numbers`, one `gh issue edit --add-label`
    per issue -- never `--remove-label`, never a set. Returns
    ``{"added": [...], "failed": [{"number": n, "reason": str}, ...]}``; a
    caller sees exactly which numbers actually got labelled even when some
    failed partway through.
    """
    added = []
    failed = []
    for number in numbers:
        command = [
            gh,
            "issue",
            "edit",
            str(number),
            "--repo",
            repo,
            "--add-label",
            label,
        ]
        try:
            done = run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            failed.append(
                {
                    "number": number,
                    "reason": "{} did not run ({})".format(_command_text(command), exc),
                }
            )
            continue
        if done.returncode != 0:
            message = (_decode_output(done.stderr) or _decode_output(done.stdout) or "").strip()
            failed.append({"number": number, "reason": message})
            continue
        added.append(number)
    return {"added": added, "failed": failed}


def freeze(repo, tag, cohort, gh, run, execute=False):
    """Freeze `cohort-{cohort}` for `tag`. Computes membership either way;
    only actually writes a label when `execute` is true.

    Returns a payload with `state` in `FREEZE_STATES`. The authoritative
    signal is always `state`, never the shape of `count`/`members` alone:
    when the tag timestamp or the issue listing could not be read, nothing
    was computed yet and both are `None`; when the *current* label
    membership or a label write fails partway, `count` and `members` still
    carry whatever was already computed before that point, so a caller
    reading the reason can see how far the freeze got -- both cases are
    `could-not-read` regardless. A real empty cohort is `already-frozen`
    with `count == 0`, an `int` -- distinguishable from every `could-not-read`
    case by `state`, and from the two earliest ones by `count is None` too,
    but never claim more than `state` promises.
    """
    label = "{}{}".format(LABEL_PREFIX, cohort)

    resolved = resolve_tag_timestamp(repo, tag, gh, run)
    if resolved["state"] != "ok":
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "could not resolve the timestamp of tag {}: {}".format(
                tag, resolved["reason"]
            ),
            "label": label,
            "tag": tag,
            "cutoff": None,
            "count": None,
            "members": None,
            "added": None,
            "dry_run": not execute,
        }
    cutoff = resolved["timestamp"]

    fetched = fetch_issues(repo, gh, run)
    if fetched["state"] != "ok":
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "could not list issues: {}".format(fetched["reason"]),
            "label": label,
            "tag": tag,
            "cutoff": cutoff,
            "count": None,
            "members": None,
            "added": None,
            "dry_run": not execute,
        }

    members = cohort_members(fetched["issues"], cutoff)

    existing = label_members(repo, label, gh, run)
    if existing["state"] != "ok":
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "could not read current {} membership: {}".format(
                label, existing["reason"]
            ),
            "label": label,
            "tag": tag,
            "cutoff": cutoff,
            "count": len(members),
            "members": members,
            "added": None,
            "dry_run": not execute,
        }

    already = set(existing["numbers"])
    to_add = sorted(n for n in members if n not in already)

    if not to_add:
        return {
            "state": STATE_ALREADY,
            "reason": "",
            "label": label,
            "tag": tag,
            "cutoff": cutoff,
            "count": len(members),
            "members": members,
            "added": [],
            "dry_run": not execute,
        }

    if not execute:
        return {
            "state": STATE_FROZEN,
            "reason": "dry run: would add {} to {} issue(s)".format(
                label, len(to_add)
            ),
            "label": label,
            "tag": tag,
            "cutoff": cutoff,
            "count": len(members),
            "members": members,
            "added": to_add,
            "dry_run": True,
        }

    result = apply_labels(repo, label, to_add, gh, run)
    if result["failed"]:
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "labelled {} of {} issue(s) with {}; failed: {}".format(
                len(result["added"]), len(to_add), label, result["failed"]
            ),
            "label": label,
            "tag": tag,
            "cutoff": cutoff,
            "count": len(members),
            "members": members,
            "added": result["added"],
            "dry_run": False,
        }

    return {
        "state": STATE_FROZEN,
        "reason": "",
        "label": label,
        "tag": tag,
        "cutoff": cutoff,
        "count": len(members),
        "members": members,
        "added": result["added"],
        "dry_run": False,
    }


def _resolve_repo_slug(value):
    """`value` is either an `owner/name` slug, or a repository root whose
    `.oss.json` names one under `repo` -- the same `--repo .` shape
    `release_publish.py` uses. Returns `(slug, problem)`; `problem` is `None`
    on success.
    """
    path = Path(value)
    config_path = path / CONFIG_NAME
    if not config_path.is_file():
        if "/" in value and not path.exists():
            return value, None
        return None, "{} not found, and {!r} is not an owner/name slug".format(
            config_path, value
        )
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "could not read {}: {}".format(config_path, exc)
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, "{} is not valid JSON: {}".format(config_path, exc)
    slug = data.get("repo") if isinstance(data, dict) else None
    if not isinstance(slug, str) or not slug.strip():
        return None, "{} does not name a `repo`".format(config_path)
    return slug.strip(), None


def _exit_code(state):
    if state == STATE_COULD_NOT_READ:
        return EXIT_COULD_NOT_READ
    return EXIT_OK


def _emit(payload, as_json):
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print("cohort_freeze: {}".format(payload.get("state")))
    for key in ("label", "tag", "cutoff", "count", "added", "dry_run", "reason"):
        if key in payload:
            print("  {}: {}".format(key, payload[key]))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Freeze a cohort label from a tag's own timestamp (#917).",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="repository root (reads .oss.json for `repo`) or an owner/name slug",
    )
    parser.add_argument("--tag", required=True, help="the tag to freeze, e.g. v0.20.0")
    parser.add_argument(
        "--cohort", required=True, type=int, help="the cohort number, e.g. 16"
    )
    parser.add_argument("--gh", default=None, help="the gh executable (default: PATH)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually write labels. Without this, nothing is written.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    slug, problem = _resolve_repo_slug(args.repo)
    if problem:
        payload = {
            "state": STATE_COULD_NOT_READ,
            "reason": problem,
            "label": "{}{}".format(LABEL_PREFIX, args.cohort),
            "tag": args.tag,
            "cutoff": None,
            "count": None,
            "members": None,
            "added": None,
            "dry_run": not args.execute,
        }
        _emit(payload, args.as_json)
        return _exit_code(payload["state"])

    gh = args.gh or shutil.which("gh")
    if not gh:
        payload = {
            "state": STATE_COULD_NOT_READ,
            "reason": "gh is not on PATH",
            "label": "{}{}".format(LABEL_PREFIX, args.cohort),
            "tag": args.tag,
            "cutoff": None,
            "count": None,
            "members": None,
            "added": None,
            "dry_run": not args.execute,
        }
        _emit(payload, args.as_json)
        return _exit_code(payload["state"])

    payload = freeze(slug, args.tag, args.cohort, gh, subprocess.run, execute=args.execute)
    _emit(payload, args.as_json)
    return _exit_code(payload["state"])


if __name__ == "__main__":
    sys.exit(main())

