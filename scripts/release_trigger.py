#!/usr/bin/env python3
"""Has a release trigger fired? -- #966.

`skills/manager/SKILL.md` and `skills/manager/phases/release.md` both state the
trigger: *whichever comes first -- N merged pull requests since the last tag,
any user-visible fix plus a soak period, or immediately for anything in a class
the ranking table marks blocking.* The thresholds are real config
(`oss_config.TRIGGER_KEYS`), and `release_delta.py` already computes the range.
Nothing computed the verdict, so a tick decided it by reading three conditions
and remembering two numbers.

## The state this exists for

`could-not-tell`. A delta that could not be read is not "no trigger", but a
session that cannot read one has nothing to report except that no release
happened -- which is indistinguishable from a repository that simply had
nothing to release. That is the quietest failure this loop can have: it stops
releasing, and nothing anywhere says why. So one unreadable input makes the
whole verdict `could-not-tell`, and every condition carries its own state
beside it so the reader can see which one went dark.

## Per-condition states

Each condition is `met` / `not-met` / `could-not-evaluate`, plus one that is
none of those:

  not-supplied   the blocking-findings condition when the caller passed no
                 findings at all. **This is not `not-met`.** This module does
                 not go hunting for findings -- an audit produces them, and
                 "nobody handed me any" is a statement about this call, never
                 about the repository. Rendering it as `not-met` would let a
                 tick that ran no audit report that no blocking finding
                 exists.

## What counts as a user-visible fix

The changelog fragment's own section: `added`, `changed`, `deprecated`,
`removed`, `fixed` and `security` are user-visible. A fragment is what this
repository already uses to classify a change, and `assemble_changelog.py`
already parses those names, so this costs no new vocabulary.

**It is a decision, not a discovery** (#966 records it): a change can be
user-visible and carry no fragment, or carry a `fixed` fragment and be
invisible in practice. It is written here so the answer is traceable to a rule
somebody chose, and so changing it is one edit rather than a re-remembering per
tick.

## Soak is measured from the commit, never the file

A fragment's mtime is rewritten by a rebase, a fresh clone and a checkout, so
it measures when this working tree was assembled and not when the fix landed.
The soak clock therefore runs from the **commit that last touched the
fragment** -- `git log -1 --format=%cI -- <path>` -- which survives all three.
A fragment git cannot date is `could-not-evaluate` for that condition, never a
zero-hour soak.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_delta  # noqa: E402

STATE_FIRED = "fired"
STATE_NOT_FIRED = "not-fired"
STATE_COULD_NOT_TELL = "could-not-tell"

MET = "met"
NOT_MET = "not-met"
COULD_NOT_EVALUATE = "could-not-evaluate"
NOT_SUPPLIED = "not-supplied"

#: Keep a Changelog sections that describe a change a user of the project can
#: see. `chore`-shaped work is not in this set and is not meant to be: the
#: trigger asks whether anything shipped that somebody is waiting for.
USER_VISIBLE_SECTIONS = frozenset(
    ("added", "changed", "deprecated", "removed", "fixed", "security")
)

_TIMEOUT = 30


def _git(repo, *args):
    """``(ok, stdout, detail)``. Never raises -- a verdict that crashes is a
    verdict nobody gets, and this module's whole contract is that it always
    answers."""
    try:
        proc = subprocess.run(
            ("git", "-C", str(repo)) + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "", "git is not on PATH"
    except OSError as exc:
        return False, "", "git: {0}".format(exc)
    except subprocess.TimeoutExpired:
        return False, "", "git timed out after {0}s".format(_TIMEOUT)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        return False, out, err or "git exit {0}".format(proc.returncode)
    return True, out, None


#: A commit that carries a merged pull request, under either merge method.
#:
#: **`git rev-list --merges` was the first implementation and it counted zero**
#: on this repository, whose own `.oss.json` sets `merge_method: squash` -- a
#: squash merge produces an ordinary commit with no second parent, so the
#: count that decides whether to release read `0` on a day with two merges. A
#: trigger that never fires is the failure this module was written to prevent,
#: reproduced inside the module itself; it was found by running it against the
#: repository rather than by any test, which is why the smoke run happened
#: before the tests were written.
#:
#: Matching the subject instead is method-independent: GitHub appends `(#N)` to
#: a squash commit's subject and writes `Merge pull request #N from ...` for a
#: merge commit. It is a heuristic and is named as one in the receipt -- a
#: hand-written commit whose subject ends in `(#N)` is counted, and a squash
#: whose subject somebody rewrote is not. Reading the method out of `.oss.json`
#: and counting only that shape was weighed and refused: the config states how
#: *this* loop merges, not how every commit in the range actually landed, and a
#: range spanning a change of method would then be counted under one rule and
#: be wrong for half of it.
_PR_SUBJECT_RE = re.compile(r"\(#\d+\)\s*$")
_MERGE_SUBJECT_RE = re.compile(r"^Merge pull request #\d+\b")


def _is_pull_request_commit(subject):
    return bool(_PR_SUBJECT_RE.search(subject) or _MERGE_SUBJECT_RE.match(subject))


def _condition(name, state, **extra):
    row = {"condition": name, "state": state}
    row.update(extra)
    return row


def merged_prs_condition(repo, threshold, delta=None):
    """Merged pull requests since the last tag against `release.triggers.merged_prs`.

    Counted from merge commits in `release_delta.compute`'s own range rather
    than by asking the forge: the range is the thing the release gate already
    audits, so a trigger computed over a different set than the audit reads
    would be two answers to one question.

    A `first-release` range is not an error and not a firing: there is no tag
    to count from, and inventing "everything counts" would fire the trigger on
    a repository that has never released and may not be ready to.
    """
    if threshold is None:
        return _condition(
            "merged_prs", NOT_MET, detail="no release.triggers.merged_prs declared"
        )
    payload = delta if delta is not None else release_delta.compute(repo)
    if release_delta.blocked(payload):
        return _condition(
            "merged_prs",
            COULD_NOT_EVALUATE,
            detail="release_delta: {0}".format(payload.get("reason") or "could not run"),
        )
    if payload["state"] == release_delta.STATE_FIRST_RELEASE:
        return _condition(
            "merged_prs",
            NOT_MET,
            detail="first release: no previous tag to count merged pull requests from",
            threshold=threshold,
        )
    ok, out, detail = _git(repo, "log", "--format=%s", payload["range"])
    if not ok:
        return _condition("merged_prs", COULD_NOT_EVALUATE, detail=detail)
    count = sum(1 for line in out.splitlines() if _is_pull_request_commit(line))
    state = MET if count >= threshold else NOT_MET
    return _condition(
        "merged_prs",
        state,
        count=count,
        threshold=threshold,
        short_by=None if state == MET else threshold - count,
        range=payload["range"],
        rule="subject matches a squash `(#N)` or a `Merge pull request #N`",
    )


def _fragment_sections(fragment_dir):
    """``(rows, detail)`` -- one ``(path, section)`` per fragment, or ``None``.

    A directory that cannot be listed is ``None`` and not ``[]``: "there are no
    fragments" and "nobody could look" are the two answers this whole
    repository exists to keep apart.
    """
    directory = Path(fragment_dir)
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        return None, "{0} does not exist".format(directory)
    except OSError as exc:
        return None, "{0}: {1}".format(directory, exc)
    rows = []
    for path in entries:
        if path.suffix != ".md" or path.name == "README.md":
            continue
        parts = path.name.split(".")
        # `<issue>.<section>[.<slug>].md` -- the section is always the second
        # field. A name that does not parse is skipped here rather than
        # guessed at; `assemble_changelog.py --check` is what refuses it, and
        # duplicating that refusal would be a second copy to keep in sync.
        if len(parts) >= 3 and parts[1] in USER_VISIBLE_SECTIONS:
            rows.append((path, parts[1]))
    return rows, None


def user_visible_soak_condition(repo, soak_hours, fragment_dir, now=None):
    """A user-visible fragment that has soaked for `release.triggers.soak_hours`.

    Fires on the **oldest** qualifying fragment, not the newest: the question
    is whether anything has waited long enough, and keying on the newest would
    reset the clock every time an unrelated fix landed -- a repository shipping
    steadily would never release.
    """
    if soak_hours is None:
        return _condition(
            "user_visible_soak", NOT_MET, detail="no release.triggers.soak_hours declared"
        )
    rows, detail = _fragment_sections(fragment_dir)
    if rows is None:
        return _condition("user_visible_soak", COULD_NOT_EVALUATE, detail=detail)
    if not rows:
        return _condition(
            "user_visible_soak",
            NOT_MET,
            detail="no user-visible fragment in {0}".format(fragment_dir),
            threshold_hours=soak_hours,
        )
    now = datetime.now(timezone.utc) if now is None else now
    oldest = None
    unreadable = []
    for path, section in rows:
        # A pathspec relative to the repository rather than the absolute path
        # `iterdir()` produced. **This is not a proven fix for the CI failure
        # it was written during** -- three soak tests returned
        # `could-not-evaluate` on a runner and pass locally, and the symlinked
        # -prefix theory that motivated this was measured and disproved (git
        # resolves an absolute pathspec correctly through a symlinked prefix,
        # in all four spellings). It stays because a repo-relative pathspec is
        # the narrower thing to hand git and cannot be worse, and because
        # `os.path.relpath` is computed from the two strings this function
        # already holds, so it introduces no third spelling. The cause is
        # still open; `why` below is what the next runner will report.
        try:
            pathspec = os.path.relpath(str(path), str(repo))
        except ValueError:  # pragma: no cover - different drives on Windows
            pathspec = str(path)
        ok, out, why = _git(repo, "log", "-1", "--format=%cI", "--", pathspec)
        if ok and not out.strip():
            # An empty answer from git is not a reason. Say which pathspec
            # produced it, or the next reader is left diffing two words the
            # way this round's assertion left me.
            why = "git dated nothing for pathspec {0!r} under {1}".format(
                pathspec, repo
            )
        stamp = out.strip() if ok else ""
        if not stamp:
            # An uncommitted fragment has no commit to date it from. That is
            # not a zero-hour soak and not an error either -- it has not landed
            # yet, so it cannot have soaked.
            unreadable.append(
                "{0}: {1}".format(path.name, why or "no commit has touched it yet")
            )
            continue
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            unreadable.append("{0}: unparseable commit date {1!r}".format(path.name, stamp))
            continue
        if oldest is None or when < oldest[1]:
            oldest = (path, when, section)
    if oldest is None:
        return _condition(
            "user_visible_soak",
            COULD_NOT_EVALUATE,
            detail="no user-visible fragment could be dated: {0}".format(
                "; ".join(unreadable)
            ),
        )
    hours = (now - oldest[1]).total_seconds() / 3600.0
    state = MET if hours >= soak_hours else NOT_MET
    return _condition(
        "user_visible_soak",
        state,
        fragment=oldest[0].name,
        section=oldest[2],
        soaked_hours=round(hours, 1),
        threshold_hours=soak_hours,
        short_by_hours=None if state == MET else round(soak_hours - hours, 1),
        undated=unreadable or None,
    )


def blocking_findings_condition(findings):
    """`findings` is the caller's list of blocking-class rows, or ``None``.

    ``None`` is `not-supplied` and never `not-met`: this module does not read
    an audit, so "nobody handed me any" is a statement about this call. A tick
    that ran no audit must not be able to report that no blocking finding
    exists.
    """
    if findings is None:
        return _condition(
            "blocking_finding",
            NOT_SUPPLIED,
            detail="no findings passed; this call cannot speak for the repository",
        )
    rows = [str(row) for row in findings if str(row).strip()]
    if not rows:
        return _condition("blocking_finding", NOT_MET, findings=[])
    return _condition("blocking_finding", MET, findings=rows)


def compute(repo, config=None, findings=None, fragment_dir=None, now=None, delta=None):
    """The verdict plus every condition's own row. Never raises.

    `could-not-tell` wins over `fired`: a condition that could not be evaluated
    might have fired too, so a `fired` verdict built on a partial read would be
    right by luck. It does not win over an already-firing condition, though --
    see the ordering below, which is the one judgement in this module.
    """
    triggers = ((config or {}).get("release") or {}).get("triggers") or {}
    conditions = [
        merged_prs_condition(repo, triggers.get("merged_prs"), delta=delta),
        user_visible_soak_condition(
            repo,
            triggers.get("soak_hours"),
            fragment_dir or Path(repo, "changelog.d"),
            now=now,
        ),
        blocking_findings_condition(findings),
    ]
    fired = [row for row in conditions if row["state"] == MET]
    dark = [row for row in conditions if row["state"] == COULD_NOT_EVALUATE]
    if fired:
        # A condition that actually fired is not made less true by another one
        # being unreadable: the trigger is "whichever comes first", so one `met`
        # settles it. The dark rows stay in the payload and the receipt prints
        # them, because "we are releasing, and one condition went unread" is a
        # thing the reader should still see.
        state = STATE_FIRED
    elif dark:
        state = STATE_COULD_NOT_TELL
    else:
        state = STATE_NOT_FIRED
    return {
        "state": state,
        "fired": [row["condition"] for row in fired],
        "unevaluated": [row["condition"] for row in dark],
        "conditions": conditions,
    }


HEADINGS = {
    STATE_FIRED: "fired",
    STATE_NOT_FIRED: "not fired",
    STATE_COULD_NOT_TELL: "could not tell",
}


def receipt(payload):
    """One block a human reads, with the thresholds printed rather than recalled.

    The spine's own sentence is that a threshold nobody can see arriving is
    indistinguishable from deciding on a whim, so every row prints the number
    it was compared against even when it did not fire.
    """
    lines = ["release-trigger: {0}".format(HEADINGS[payload["state"]])]
    for row in payload["conditions"]:
        bits = ["{0:<18}: {1}".format(row["condition"], row["state"])]
        for key in (
            "count",
            "threshold",
            "short_by",
            "soaked_hours",
            "threshold_hours",
            "short_by_hours",
            "fragment",
            "detail",
        ):
            value = row.get(key)
            if value not in (None, "", []):
                bits.append("{0}={1}".format(key, value))
        lines.append("  ".join(bits))
    if payload["state"] == STATE_COULD_NOT_TELL:
        lines.append(
            "verdict          : COULD NOT TELL -- {0} went unread, and a condition "
            "that could not be evaluated is not a condition that did not fire.".format(
                ", ".join(payload["unevaluated"])
            )
        )
    elif payload["state"] == STATE_FIRED:
        lines.append("verdict          : FIRED on {0}".format(", ".join(payload["fired"])))
        if payload["unevaluated"]:
            lines.append(
                "note             : {0} went unread; the release proceeds on the "
                "condition that did fire.".format(", ".join(payload["unevaluated"]))
            )
    return "\n".join(lines)


def _load_config(path):
    if not path:
        return {}, None
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, "{0}: {1}".format(path, exc)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Has a release trigger fired? fired / not-fired / could-not-tell."
    )
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--config", default=None, help="path to .oss.json")
    parser.add_argument(
        "--fragment-dir",
        default=None,
        help="changelog fragment directory (default: <repo>/changelog.d)",
    )
    parser.add_argument(
        "--blocking-finding",
        action="append",
        default=None,
        metavar="TEXT",
        help=(
            "a blocking-class finding, repeatable. Pass --no-blocking-findings to "
            "state that an audit ran and found none; omitting both is not-supplied."
        ),
    )
    parser.add_argument(
        "--no-blocking-findings",
        action="store_true",
        help="an audit ran and produced no blocking finding",
    )
    parser.add_argument("--json", action="store_true", help="emit the payload as JSON")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    config_path = args.config or os.path.join(args.repo, ".oss.json")
    config, detail = _load_config(config_path)
    if config is None:
        payload = {
            "state": STATE_COULD_NOT_TELL,
            "fired": [],
            "unevaluated": ["config"],
            "conditions": [
                _condition("config", COULD_NOT_EVALUATE, detail=detail),
            ],
        }
    else:
        findings = args.blocking_finding
        if findings is None and args.no_blocking_findings:
            findings = []
        payload = compute(
            args.repo,
            config=config,
            findings=findings,
            fragment_dir=args.fragment_dir,
        )

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(receipt(payload) + "\n")

    # `could-not-tell` exits non-zero: a caller that reads only the code must
    # not proceed as though the answer were "no release today".
    return 0 if payload["state"] in (STATE_FIRED, STATE_NOT_FIRED) else 1


if __name__ == "__main__":
    sys.exit(main())
