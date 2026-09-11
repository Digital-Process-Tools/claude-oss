#!/usr/bin/env python3
"""Is a post-release triage sweep due? -- #1386.

`skills/manager/phases/accounting.md`'s own cadence rule -- three to four
ticks, then a release, then a triage sweep, then three to four more (#855) --
lives where its only reader, a sub-manager, cannot act on it: a sub-manager
dies with its own context at the end of its tick, cannot count ticks across
spawns, and is already past the release by the time it reads the rule. The
scheduler is the one actor spanning ticks, and nothing handed it a verdict to
read.

The recorder side already exists: `scripts/oss_state.py --triage-recorded`
writes, `--last-triage` reads back in three states (#855). Nothing consumed
it. This module is that consumer, in the same shape `scripts/release_trigger.py`
(#966) and `scripts/workspace_routes.py` (#1155) already give their own
cadence steps -- a real threshold in config, evaluated mechanically, never
felt.

## The condition, chosen over the alternative

"After a release" is read here as: **the most recent recorded triage sweep is
older than the most recent tag, or none was ever recorded.** A tick-count
was considered and rejected -- a sub-manager cannot count ticks across its own
spawns (see above), so a tick-count would need a second recorder nothing else
needs, where the tag date and the triage record both already exist. Comparing
two timestamps this repository already has costs no new state and is
falsifiable in one call by any later tick: re-run this module and read the
same two facts again, rather than trust a memory of how many ticks passed.

## Three states, not two

  due             a release has landed and either no triage sweep was ever
                  recorded, or the most recent one predates the most recent
                  tag.
  not-due         the most recent recorded sweep is at or after the most
                  recent tag, or no tag exists yet -- nothing has been
                  released for a sweep to follow.
  could-not-tell  the tag's date, or the triage record, could not be read.
                  Never collapsed into `not-due`: an input this call could not
                  see is not evidence the board was swept, only that this call
                  could not tell -- the defect class this whole repository is
                  named after, one trigger over.

## Declared, not assumed

`release.triggers.triage_after_release` in `.oss.json` must be `true` for this
to evaluate at all -- absent or falsy answers `not-due` with a `detail` saying
so, the same rule `curate_route_threshold` and `changelog_untagged` already
use: an absent key means a repository has not asked for the step, not that the
step silently always fires. It sits beside `merged_prs`/`soak_hours` because
all three are cadence conditions the scheduler reads after a release-shaped
event, not because it shares their arithmetic -- it is a boolean, not a count,
because the underlying condition ("has anything swept the board since the
last tag") has no meaningful threshold to tune.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402
import oss_config  # noqa: E402
import oss_state  # noqa: E402
import release_delta  # noqa: E402

STATE_DUE = "due"
STATE_NOT_DUE = "not-due"
STATE_COULD_NOT_TELL = "could-not-tell"

_TIMEOUT = 20


def _git(repo, *args):
    """Run git in `repo`. Returns (ok, stdout, why). Never raises.

    Duplicated from `release_trigger._git` rather than imported across
    modules -- a small, private helper, and this repository already accepts
    that shape (`workspace_routes._decode` cites the same precedent).
    """
    git_bin = gh_which.safe_which("git")
    if git_bin is None:
        return False, "", "git is not on PATH"
    try:
        import subprocess

        proc = subprocess.run(
            (git_bin, "-C", str(repo)) + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "", "git is not on PATH"
    except OSError as exc:
        return False, "", "git: {0}".format(exc)
    except Exception as exc:  # noqa: BLE001 - subprocess.TimeoutExpired et al
        return False, "", "git: {0}".format(exc)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        return False, out, err or "git exit {0}".format(proc.returncode)
    return True, out, None


def _parse_stamp(text):
    """A git `%cI` or a recorded ISO stamp, as an aware datetime, or ``None``.

    Same Z-suffix normalisation as `release_trigger._parse_stamp`, for the
    same reason (#966's own note): `datetime.fromisoformat` only accepts a
    bare `Z` from Python 3.11 on, and the supported floor is 3.9.
    """
    if not text:
        return None
    stamp = str(text).strip()
    if stamp.endswith(("Z", "z")):
        stamp = stamp[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _condition(state, **extra):
    row = {"state": state}
    row.update(extra)
    return row


def compute(repo, config=None, state_path=None, delta=None):
    """The verdict, plus enough detail to print it. Never raises."""
    triggers = ((config or {}).get("release") or {}).get("triggers") or {}
    if not triggers.get("triage_after_release"):
        return _condition(
            STATE_NOT_DUE,
            detail="release.triggers.triage_after_release is not enabled",
        )

    # `release_delta.compute`'s own `config` parameter is a *path* to `.oss.json`
    # (it re-reads and re-derives `tag_pattern` from it), not the already-loaded
    # dict this module receives -- `release_trigger.compute` makes the identical
    # choice, unscoped, rather than re-deriving a path this caller may not have.
    payload = delta if delta is not None else release_delta.compute(repo)
    if release_delta.blocked(payload):
        return _condition(
            STATE_COULD_NOT_TELL,
            detail="release_delta: {0}".format(
                payload.get("reason") or "could not run"
            ),
        )
    if payload["state"] == release_delta.STATE_FIRST_RELEASE:
        return _condition(
            STATE_NOT_DUE,
            detail="first release: no tag exists yet for a sweep to follow",
        )

    tag = payload["tag"]
    ok, out, why = _git(repo, "log", "-1", "--format=%cI", tag)
    if not ok or not out.strip():
        return _condition(
            STATE_COULD_NOT_TELL,
            detail="could not read the commit date of tag {0!r}: {1}".format(
                tag, why or "git printed nothing"
            ),
        )
    tag_date = _parse_stamp(out.strip())
    if tag_date is None:
        return _condition(
            STATE_COULD_NOT_TELL,
            detail="tag {0!r} has an unparseable commit date {1!r}".format(
                tag, out.strip()
            ),
        )

    if not state_path:
        return _condition(
            STATE_COULD_NOT_TELL,
            detail="no state file configured, so the last triage sweep could not be read",
        )
    record = oss_state.last_triage(state_path)
    if record["state"] == oss_state.TRIAGE_COULD_NOT_READ:
        return _condition(
            STATE_COULD_NOT_TELL,
            tag=tag,
            tag_date=tag_date.isoformat(),
            detail="last-triage: {0}".format(record["why"] or "could not read"),
        )
    if record["state"] == oss_state.TRIAGE_NEVER:
        return _condition(
            STATE_DUE,
            tag=tag,
            tag_date=tag_date.isoformat(),
            detail="no triage sweep has ever been recorded, and tag {0} exists".format(
                tag
            ),
        )

    recorded_at = _parse_stamp(record["recorded_at"])
    if recorded_at is None:
        return _condition(
            STATE_COULD_NOT_TELL,
            tag=tag,
            tag_date=tag_date.isoformat(),
            detail="the recorded triage sweep has an unparseable timestamp {0!r}".format(
                record["recorded_at"]
            ),
        )
    if recorded_at < tag_date:
        return _condition(
            STATE_DUE,
            tag=tag,
            tag_date=tag_date.isoformat(),
            last_triage=record["recorded_at"],
            detail="the last recorded triage sweep ({0}) predates tag {1} ({2})".format(
                record["recorded_at"], tag, tag_date.isoformat()
            ),
        )
    return _condition(
        STATE_NOT_DUE,
        tag=tag,
        tag_date=tag_date.isoformat(),
        last_triage=record["recorded_at"],
        detail="the last recorded triage sweep ({0}) is at or after tag {1} ({2})".format(
            record["recorded_at"], tag, tag_date.isoformat()
        ),
    )


HEADINGS = {
    STATE_DUE: "due",
    STATE_NOT_DUE: "not due",
    STATE_COULD_NOT_TELL: "could not tell",
}


def receipt(payload):
    """One block a human reads."""
    lines = ["triage-trigger: {0}".format(HEADINGS[payload["state"]])]
    for key in ("tag", "tag_date", "last_triage", "detail"):
        value = payload.get(key)
        if value not in (None, ""):
            lines.append("{0:<11}: {1}".format(key, value))
    if payload["state"] == STATE_COULD_NOT_TELL:
        lines.append(
            "verdict    : COULD NOT TELL -- an input went unread, and that is "
            "not the same fact as nothing being due."
        )
    elif payload["state"] == STATE_DUE:
        lines.append(
            "verdict    : DUE -- dispatch a triage sweep before the next tick."
        )
    return "\n".join(lines)


def _load_config(path):
    """`(config, detail)` -- routed through `oss_config.load`, not a raw
    `json.load` over `.oss.json` alone (#1436 self-review, and see
    `next_action.py`'s own identical call for the reference shape). A raw
    read never merges `.oss.local.json`, where `state_file` actually lives
    on any repo with a split config -- this call reported "no state file
    configured" even when one was, in the half it never read."""
    if not path:
        return {}, None
    config, problems = oss_config.load(path)
    if config is None:
        return None, "; ".join(problems) if problems else "could not read {0}".format(
            path
        )
    return config, None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Is a post-release triage sweep due? due / not-due / could-not-tell."
    )
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--config", default=None, help="path to .oss.json")
    parser.add_argument(
        "--state-file",
        default=None,
        help="path to the tick state file (default: config's own state_file)",
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
        payload = _condition(STATE_COULD_NOT_TELL, detail="config: {0}".format(detail))
    else:
        state_path = args.state_file or (
            os.path.join(args.repo, config["state_file"])
            if config.get("state_file")
            else None
        )
        payload = compute(args.repo, config=config, state_path=state_path)

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(receipt(payload) + "\n")

    # `could-not-tell` exits non-zero: a caller reading only the exit code must
    # not proceed as though "not due today" were the answer.
    return 0 if payload["state"] in (STATE_DUE, STATE_NOT_DUE) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
