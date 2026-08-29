#!/usr/bin/env python3
"""The surface `/oss:release` could close and did not: the GitHub Release object.

The command tagged, verified the tag on the remote, and stopped. The releases page
then showed a tag with no notes, nothing was marked `Latest`, and nobody watching
for releases was told. The skill's own section already argued that the tag is not
the delivery -- so it explained the difference between tagging and shipping, then
did the first while narrating the second (#58).

Three states, because this is a release path and a quiet failure here leaves a
maintainer believing something shipped that did not:

  create / created         policy asked for it, the notes exist, the command ran
  skipped                  policy says this repo tags without publishing. A
                           decision, named out loud, never silence
  could-not-run            the notes could not be extracted, `gh` is not on PATH,
  could-not-create         the notes are over GitHub's release-body length limit
                           (#483), the call failed, or `.oss.json` is not a JSON
                           object at all and so states no policy. Not a release and
                           not a skip

A `created` release also invalidates the status line's cached `latest` for this
repo (#549): the publish IS the event that falsifies that cache, and this is the
only actor that knows it happened at the moment it does, rather than waiting out
a refresh interval that cannot see it. Reported under its own key,
`cache_invalidation`, in the same three-state shape rather than folded into
`state` above -- these are two different vocabularies about two different
things, and #134 is the bill for merging vocabularies like that once already:
`invalidated` / `nothing-to-invalidate` / `could-not-invalidate`. Only present
when a release was actually created; a dry run or a skip touches nothing.

Exit codes, because a shell reads those and never reads prose:

  0   the release was created, or the command is buildable (dry run)
  3   could not run / could not create
  4   skipped by policy
  2   argparse usage error

`--verify-tag` is not optional and is not decoration. Without it `gh release create`
creates the tag itself when it is missing, which turns a verification step into a
silent tag-minting step and defeats the `git ls-remote` check the release command
insists on two paragraphs earlier. It is emitted on every branch that builds a
command, and the test spells the whole argv out rather than watching a mock.

`--repo` is likewise always passed. `gh` otherwise infers the repository from the
directory it happens to be standing in, and a release cut from the wrong worktree
is exactly this plugin's defect class wearing a different hat.

Nothing from inside the changelog section reaches the receipt. The section is prose
somebody wrote in a pull request; it belongs in the notes file, which is the whole
point, and a line of it at column 0 in the receipt forges the receipt's own verdict.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_role  # noqa: E402
import oss_config  # noqa: E402

try:
    import statusline
except ImportError:  # pragma: no cover - the module sits beside this file
    statusline = None

STATE_CREATE = "create"
STATE_SKIPPED = "skipped"
STATE_COULD_NOT_RUN = "could-not-run"
STATE_CREATED = "created"
STATE_COULD_NOT_CREATE = "could-not-create"
STATE_ROLE_FORBIDDEN = "role-forbidden"

# The whole of what `state` may say in this module. `notes_section` answers about the
# changelog and answers under `notes` for this reason (#134): two vocabularies under
# one key, in one module, with `receipt` and `_exit_code` accepting any dict, is one
# obvious line away from a notes payload printing `state: FOUND` at the top of a
# release receipt. Named here so the receipt can say when it was handed something
# that is not one of these, rather than upper-casing it into a verdict.
PUBLISH_STATES = (
    STATE_CREATE,
    STATE_SKIPPED,
    STATE_COULD_NOT_RUN,
    STATE_CREATED,
    STATE_COULD_NOT_CREATE,
    STATE_ROLE_FORBIDDEN,
)

EXIT_OK = 0
EXIT_COULD_NOT_RUN = 3
EXIT_SKIPPED = 4
EXIT_ROLE_FORBIDDEN = 5

CHANGELOG_NAME = "CHANGELOG.md"

# GitHub's own limit on a release body, as `gh release create` reports it (#483):
#   HTTP 422: Validation Failed body is too long (maximum is 125000 characters)
# Observed cutting claude-supertool v0.49.0 on 2026-08-22 -- 60 folded fragments made a
# 128,124-character section against this limit, and the tag was already on the remote
# by the time the call failed. A named constant with this citation, not a value read
# off a live 422: the number is a fact about GitHub's API today, not about any one
# repository's changelog, and a constant is the only place both a comment and a test
# can point at when the API changes it.
GITHUB_NOTES_LIMIT = 125000

# `## [0.3.0] - 2026-08-14`, and the label is captured whole. Whole rather than a
# prefix on purpose: `0.3` must not match `## [0.3.0]`, and `0.3.0` must not match
# `## [0.3.0-rc1]` -- either would announce the wrong release with the right title.
#
# Matched a line at a time rather than with re.MULTILINE over the whole file, because
# a fenced code block can contain a line shaped exactly like a heading -- a changelog
# entry quoting a changelog is not exotic. Read as a real boundary, that line
# truncates the notes at the fence and the release ships with the tail missing. That
# is worse than either absence this module reports: not a state, but wrong content
# returned as `found`, and nothing downstream can tell.
HEADING_RE = re.compile(r"^##[ \t]+\[([^\]]+)\]")

# CommonMark: three or more backticks or tildes, optionally indented up to three
# spaces. A closing fence is the same character, at least as long, and carries
# nothing after it.
FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")


def _headings(text):
    """Every real `## [label]` heading: (label, body start, heading line start).

    Real means not inside a fenced code block.
    """
    found = []
    fence = None
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.lstrip(" ")
        indented = len(line) - len(body)
        stripped = body.rstrip("\r\n")
        if indented <= 3:
            match = FENCE_RE.match(stripped)
            if match:
                marker, rest = match.group(1), match.group(2)
                if fence is None:
                    # An opening fence's info string may say anything; a closing one
                    # may not, which is the only thing keeping ```python from closing
                    # the block it opens.
                    fence = (marker[0], len(marker))
                elif marker[0] == fence[0] and len(marker) >= fence[1] and not rest.strip():
                    fence = None
                offset += len(line)
                continue
        if fence is None and indented == 0:
            heading = HEADING_RE.match(stripped)
            if heading:
                found.append((heading.group(1).strip(), offset + len(line), offset))
        offset += len(line)
    return found


def _one_line(text, limit=200):
    """Text from outside this script, reduced to one printable ASCII line.

    Adopted from ``release_delta.py``, for the same reason: a newline in a stranger's
    stderr forges a receipt line and a control character rewrites what a terminal has
    already printed.
    """
    flat = " ".join(str(text).split())
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)
    return safe[:limit]


def notes_section(text, version):
    """The release notes for `version`: everything between its heading and the next.

    Three states, and the middle one is why this does not just return a string:

      found    a heading for this version with a body under it
      empty    the heading is there and there is nothing under it. An empty string
               returned here would reach `gh` as a release with blank notes -- the
               absence the tool produced, rendered as the notes somebody wrote
      missing  no heading for this version at all

    They come back under `notes`, not `state` (#134). `state` names the publish
    lifecycle everywhere else in this module -- create / skipped / could-not-run /
    created / could-not-create -- and `receipt` and `_exit_code` read it off any dict
    they are handed. Sharing the key made `missing` a value both vocabularies could
    carry with nothing to tell them apart, which is a bug nobody had written yet.

    The last section in the file runs to the end of the file rather than off it, and
    a file with exactly one section is the same case with no next heading.
    """
    if not text or not version:
        return {"notes": "missing", "body": None, "reason": "no changelog text or no version"}

    headings = _headings(text)
    for index, (label, start, _) in enumerate(headings):
        if label != str(version).strip():
            continue
        # The body starts after the heading *line*, not after the closing bracket:
        # `## [0.3.0] - 2026-08-14` carries a date that is not part of the notes.
        end = headings[index + 1][2] if index + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        if not body:
            return {
                "notes": "empty",
                "body": None,
                "reason": "the section for {} exists and has no body".format(version),
            }
        return {"notes": "found", "body": body, "reason": ""}

    return {
        "notes": "missing",
        "body": None,
        "reason": "no `## [{}]` section in the changelog".format(_one_line(version, 60)),
    }


def _skip(reason):
    return {"state": STATE_SKIPPED, "command": None, "reason": reason}


def _could_not_run(reason):
    return {"state": STATE_COULD_NOT_RUN, "command": None, "reason": reason}


def plan(config, tag, notes_path, gh, notes_len=None):
    """The command that would run, or the state that says why none will.

    Policy is checked before anything else, so a repo that deliberately tags without
    releasing is never reported as a failure to reach an API it was never going to
    call. Which is exactly why a config that cannot state a policy has to be caught
    first: `release_publish_policy` answers `isinstance(config, dict)` with the shipped
    defaults, and the shipped default does not publish. A `.oss.json` holding `[]`,
    `"x"`, `null` or `42` therefore came back `skipped`, exit 4, with a sentence about
    `release.create_release` being unset -- about a document that could not have set
    it. The tag ships, the Release silently does not, and the receipt says a decision
    was made. That is the one outcome this script's three states exist to prevent, so
    a structurally wrong config is `could-not-run` and exit 3 (#126).

    Read as a fact about the document rather than as a missing key, because those are
    different things and only one of them is a maintainer's choice. The neighbouring
    `repo` check below already applies `isinstance(config, dict)` for the same reason;
    this is the same guard, one step earlier, where it settles the question for every
    caller instead of for one field.

    `notes_len` is the character count of the notes body, measured by the caller who
    holds the text -- `plan` never reads `notes_path` itself, so a caller that does not
    know the length (most of the unit tests below) may pass `None` and skip the check
    entirely, unchanged from before this parameter existed. `main` always passes it, on
    every dry run as well as every `--execute`, which is the point (#483): `gh release
    create` refuses a body over 125,000 characters with a 422, and by the time that
    call used to run, the tag was already pushed. Refused here, not truncated -- an
    over-limit body is close kin to the empty-body case a few lines below, where this
    module already refuses to publish content it did not write rather than send
    something the changelog's own author never declared. Truncating at a bullet
    boundary would avoid the refusal, but it substitutes an edited set of notes for the
    one the fold actually produced, silently declaring which bullets did not matter --
    the plugin's own defect class in miniature, and worse than a tag that waits one
    extra step for `--notes-out`/`--execute` to be re-run by hand against a trimmed
    changelog. Whichever way this call is made, the receipt says the measured length
    and the limit, so the size of the overage is never left for the maintainer to infer
    from a bare refusal.
    """
    if not isinstance(config, dict):
        return _could_not_run(
            "the release config is a {0}, not a JSON object, so it states no release "
            "policy at all -- which is not the same as stating one that does not "
            "publish. No GitHub Release was created and the tag is "
            "unaffected.".format(type(config).__name__)
        )

    policy = oss_config.release_publish_policy(config)

    if not policy["create"]:
        if policy["stated"]:
            return _skip(
                "release.create_release is false in .oss.json: this repo tags without "
                "publishing a GitHub Release."
            )
        return _skip(
            "release.create_release is unset in .oss.json and the shipped default does "
            "not publish -- publishing notifies watchers and is not undoable the way a "
            "draft is. Set release.create_release to true to create a GitHub Release."
        )

    if not gh:
        return _could_not_run(
            "gh is not on PATH, so no GitHub Release was created. The tag is unaffected."
        )

    if not notes_path:
        return _could_not_run(
            "no release notes were extracted, so no GitHub Release was created. A "
            "release announced with blank notes is worse than one announced late."
        )

    if notes_len is not None and notes_len > GITHUB_NOTES_LIMIT:
        return _could_not_run(
            "the release notes are {0} characters, over GitHub's {1}-character limit "
            "by {2} -- not sent to gh, so the call this would have made never runs. "
            "Trim changelog.d fragments for this version (or split the release) and "
            "re-run.".format(notes_len, GITHUB_NOTES_LIMIT, notes_len - GITHUB_NOTES_LIMIT)
        )

    slug = config.get("repo") if isinstance(config, dict) else None
    if not isinstance(slug, str) or not slug.strip():
        return _could_not_run(
            "no `repo` in .oss.json, and gh would otherwise infer the repository from "
            "whichever directory it is standing in."
        )

    command = [
        gh,
        "release",
        "create",
        str(tag),
        "--repo",
        slug.strip(),
        "--title",
        str(tag),
        "--notes-file",
        str(notes_path),
        # Never removed, never made conditional. See the module docstring.
        "--verify-tag",
    ]

    if policy["draft"]:
        command.append("--draft")
        # No latest flag at all for a draft. A draft cannot be Latest, so
        # `--latest=false` on one reads as a deliberate "not latest" about a release
        # that does not exist yet. The validator refuses draft + latest outright.
    elif policy["latest"]:
        command.append("--latest")
    else:
        command.append("--latest=false")

    return {
        "state": STATE_CREATE,
        "command": command,
        "reason": "",
        "draft": policy["draft"],
        "latest": policy["latest"],
        "tag": str(tag),
        "repo": slug.strip(),
        "notes_path": str(notes_path),
    }


def execute(planned):
    """Run a planned command. A plan that is not a `create` runs nothing, unchanged.

    A non-zero exit is `could-not-create` and never `created`. That distinction is
    the whole reason this function exists rather than a bare subprocess call at the
    call site, where a forgotten returncode check reads as a release that shipped.
    """
    result = dict(planned or {})
    result.setdefault("detail", "")

    if result.get("state") != STATE_CREATE:
        # skipped stays skipped, could-not-run stays could-not-run. Nothing ran, and
        # nothing here may promote either into an outcome about the API.
        return result

    try:
        done = subprocess.run(
            list(result["command"]),
            capture_output=True,
            text=True,
            errors="replace",
            env=dict(os.environ),
        )
    except (OSError, ValueError) as exc:
        result["state"] = STATE_COULD_NOT_CREATE
        result["detail"] = _one_line("{0}: {1}".format(type(exc).__name__, exc))
        return result

    if done.returncode == 0:
        result["state"] = STATE_CREATED
        result["detail"] = _one_line(done.stdout or done.stderr)
        return result

    result["state"] = STATE_COULD_NOT_CREATE
    result["detail"] = _one_line(
        "{0} (exit {1})".format(done.stderr or done.stdout, done.returncode)
    )
    return result


def _invalidate_cache_after_publish(repo):
    """Clear the status line's cached `latest` for `repo` immediately after a
    Release is confirmed created (#549).

    Delegates entirely to `statusline.invalidate_latest_cache`, which reads
    `cache_path`/`cache_dir` from `statusline` itself -- this module never
    re-derives that path, so the two never drift apart.

    A missing `statusline` module (an install where it sits beside this file but
    could not be imported for some other reason) is `could-not-invalidate` rather
    than a crash on a release path that has already shipped -- the Release itself
    is not undone by a cache this could not reach.
    """
    if statusline is None:
        return {
            "state": "could-not-invalidate",
            "detail": "scripts/statusline.py could not be imported",
        }
    return statusline.invalidate_latest_cache(repo)


def receipt(payload):
    """One block, fixed width, and nothing from inside the changelog in it."""
    lines = ["release publish"]

    def row(label, value):
        lines.append("  {0:<9}: {1}".format(label, value))

    # Not upper-cased blind. The state row is the first line anybody reads, and a
    # value from some other vocabulary rendered there -- `FOUND`, say -- reads as a
    # verdict this module never gave (#134).
    state = payload.get("state")
    if state in PUBLISH_STATES:
        row("state", str(state).upper())
    else:
        row(
            "state",
            "UNRECOGNISED ({0} is not a publish state)".format(
                "no state" if state is None else "'" + _one_line(str(state), 60) + "'"
            ),
        )
    row("tag", payload.get("tag") or "-")
    row("repo", payload.get("repo") or "-")
    draft = payload.get("draft")
    latest = payload.get("latest")
    row("draft", "-" if draft is None else ("yes" if draft else "no"))
    row("latest", "-" if latest is None else ("yes" if latest else "no"))
    row("notes", payload.get("notes_path") or "-")
    command = payload.get("command")
    row("command", " ".join(command) if command else "-")
    cache = payload.get("cache_invalidation")
    if isinstance(cache, dict) and cache.get("state"):
        row("cache", str(cache["state"]))
    if payload.get("reason"):
        row("reason", _one_line(payload["reason"], 320))
    if payload.get("detail"):
        row("detail", _one_line(payload["detail"]))
    return "\n".join(lines)


def _read_json(path):
    """``(document, problem)``. A non-empty ``problem`` is the only failure signal.

    NOT ``document is None``: a file containing exactly `null` parses to `None` with
    nothing wrong, and read that way it was reported as `could not read <path> --`
    with nothing after the dash, because there was no exception to name. A file that
    could not be opened and a file that says `null` are different facts and rendered
    identically -- which is the defect this plugin is named after, in the four lines
    that read the config (#126).
    """
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle), ""
    except (OSError, ValueError) as exc:
        return None, "{0}: {1}".format(type(exc).__name__, exc)


def _exit_code(state):
    if state in (STATE_CREATE, STATE_CREATED):
        return EXIT_OK
    if state == STATE_SKIPPED:
        return EXIT_SKIPPED
    if state == STATE_ROLE_FORBIDDEN:
        return EXIT_ROLE_FORBIDDEN
    return EXIT_COULD_NOT_RUN


def _emit(payload, as_json):
    if as_json:
        sys.stdout.write(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(receipt(payload) + "\n")
    return _exit_code(payload.get("state"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create the GitHub Release for a tag that already exists.",
    )
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--version", required=True, help="the version being released")
    parser.add_argument("--tag", required=True, help="the tag, already pushed and verified")
    parser.add_argument("--changelog", default=None, help="default: <repo>/CHANGELOG.md")
    parser.add_argument("--config", default=None, help="default: <repo>/.oss.json")
    parser.add_argument("--notes-out", default=None, help="where to write the notes file")
    parser.add_argument(
        "--gh", default=None, help="the gh executable (default: the one on PATH)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually run it. Without this the command is printed and nothing is called.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    # Checked before anything else -- before the config is even read -- so
    # that no repository's own policy can be consulted on the sub-manager's
    # behalf. #695 withholds *publish* authority from the per-tick
    # sub-manager "in the code, not only in prose"; this is that code. Read
    # against `args.repo`, not the calling process's own environment alone:
    # `agent_role.current_role` falls back to a marker file under that
    # repository's git directory, because an exported OSS_AGENT_ROLE does
    # not survive from one Bash tool call to the next in this harness
    # (measured, not assumed -- see scripts/agent_role.py's own docstring).
    # NOTE: tagging (`git tag` / `git push origin <tag>`, in
    # commands/release.md) is NOT gated by this check or any other code --
    # it is a plain shell command, and withholding it from the sub-manager
    # rests on agents/sub-manager.md's prose alone (it never runs the
    # release phase). Only the publish half named here is code-enforced.
    # A marker this process cannot classify -- expired, or unparsable --
    # is deliberately treated the SAME as no marker at all: it fails open,
    # towards permitting the release, not towards refusing it. Failing
    # closed on "cannot tell" would silently reintroduce the bug this
    # review round fixed -- a dead sub-manager's leftover marker blocking
    # every release after it forever, with a reason that reads as correct.
    # The underlying classification is not lost even though the decision
    # ignores it: `refusal["marker_state"]` carries it for whoever wants to
    # inspect why a release did or did not go through.
    refusal = agent_role.release_refusal("publish a GitHub Release", root=args.repo)
    if refusal["forbidden"]:
        return _emit(
            {
                "state": STATE_ROLE_FORBIDDEN,
                "command": None,
                "reason": refusal["reason"],
                "tag": args.tag,
            },
            args.as_json,
        )

    root = Path(args.repo)
    config_path = Path(args.config) if args.config else root / oss_config.CONFIG_NAME
    config, problem = _read_json(config_path)
    if problem:
        return _emit(
            _could_not_run("could not read {0} -- {1}".format(config_path, _one_line(problem))),
            args.as_json,
        )

    # Shape before policy, and before anything downstream. A document that is not an
    # object states no policy, so every later step would be answering a question this
    # config never posed -- and the first of them, `plan`, would call it a skip. Worse,
    # left to fall through, the run reports whichever downstream step failed first: an
    # absent changelog for a `.oss.json` containing `[]` is a true sentence about the
    # wrong problem (#126).
    if not isinstance(config, dict):
        broken = plan(config=config, tag=args.tag, notes_path=None, gh=None)
        broken["tag"] = args.tag
        return _emit(broken, args.as_json)

    # Policy first: a repo that does not publish is not a repo that failed to find a
    # changelog.
    early = plan(config=config, tag=args.tag, notes_path=None, gh=None)
    if early["state"] == STATE_SKIPPED:
        early["tag"] = args.tag
        return _emit(early, args.as_json)

    changelog_path = Path(args.changelog) if args.changelog else root / CHANGELOG_NAME
    try:
        text = changelog_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _emit(
            _could_not_run(
                "could not read {0} -- {1}".format(
                    changelog_path, _one_line("{0}: {1}".format(type(exc).__name__, exc))
                )
            ),
            args.as_json,
        )

    section = notes_section(text, args.version)
    if section["notes"] != "found":
        return _emit(
            _could_not_run(
                "no release notes ({0}): {1}".format(section["notes"], section["reason"])
            ),
            args.as_json,
        )

    if args.notes_out:
        notes_path = Path(args.notes_out)
    else:
        handle, name = tempfile.mkstemp(prefix="oss-release-notes-", suffix=".md")
        os.close(handle)
        notes_path = Path(name)
    # The exact string handed to `gh --notes-file` -- one character longer than
    # `section["body"]` itself, for the trailing newline. Measured here, after the
    # newline is appended and before the write, so the length check below sees what
    # the file actually holds rather than the bare extracted body: a body of exactly
    # `GITHUB_NOTES_LIMIT` characters would otherwise pass a check against `len(body)`
    # while the file on disk -- and the request `gh` sends -- is one character over.
    notes_text = section["body"] + "\n"
    try:
        notes_path.write_text(notes_text, encoding="utf-8")
    except OSError as exc:
        return _emit(
            _could_not_run(
                "could not write the notes file -- {0}".format(
                    _one_line("{0}: {1}".format(type(exc).__name__, exc))
                )
            ),
            args.as_json,
        )

    # An explicit --gh is the caller's own fact about their machine and is taken as
    # given; the default is resolved, and an unresolvable one is `could not run`
    # rather than a command that fails as something else later.
    gh = args.gh if args.gh else shutil.which("gh")

    planned = plan(
        config=config,
        tag=args.tag,
        notes_path=str(notes_path),
        gh=gh,
        notes_len=len(notes_text),
    )
    if planned["state"] != STATE_CREATE or not args.execute:
        return _emit(planned, args.as_json)

    result = execute(planned)
    if result.get("state") == STATE_CREATED:
        # The publish just made the cached `latest` reading false. Invalidated
        # here, immediately, rather than left for a refresh interval that has no
        # way to know this happened (#549).
        result["cache_invalidation"] = _invalidate_cache_after_publish(config.get("repo"))
    return _emit(result, args.as_json)


if __name__ == "__main__":
    raise SystemExit(main())
