"""``check_statusline_unknowns`` -- names the exact cause behind every ``?``
``statusline.py`` can render for the watch channel and the default-branch
marker, each paired with an executable remedy (#1311).

A new check, so it lives in its own module from the start, per the #497
convention. Every shared name from ``doctor`` -- ``report``, ``unmeasured``,
``scaffold`` -- is reached through ``import doctor``, never
``from doctor import name``, for the same reason ``doctor_check_statusline.py``
gives at length: a monkeypatch on ``doctor``'s own namespace has to reach this
module too.

**Why this is a doctor check rather than a change to ``statusline.py``'s own
render.** ``_channel_field`` and ``_default_branch_marker`` already compute
(or, for the default-branch field, discard) the reason a field renders ``?``
-- the issue's own complaint is that the render layer throws that reason
away, not that it was never computed. Changing the render itself is riskier:
``statusline.py`` runs on every session start, on a budget the loop's own
CLAUDE.md documents at length (`REFRESH_AFTER`, the Windows codepage trap,
the width discipline `_channel_field`'s own docstring argues for), and widening
its output to carry a reason would make an already-narrow line either wider
on every render or conditionally wider in a way a reader has to learn to
parse. `/oss:doctor` already exists to explain a WARN with as much prose as
it needs and a runnable remedy -- adding the explanation there costs nothing
on the render path and reuses `statusline.py`'s own state machine unchanged,
by re-deriving the identical reason from the identical cache file rather than
guessing at it. `.oss.json` cannot express a channel or a default-branch
reading, so this check does not modify `/oss:scaffold` either -- the contract
tested in `.claude/jit-context/paths/00-manual/doctor-check-contract.md` (a
manual op or a scaffold run) reduces to one route here, the manual op named
in every remedy below.

**Both readers, re-derived rather than read off a computed fact.**
``statusline.py`` never writes its own reasoning to disk, only the collapsed
render -- so this module re-derives the same inputs (``raw_state``,
``attribution``, ``channel_fetched_at`` for the channel; ``fetched_at``,
``default_branch_state`` for the branch marker) from the identical cache
file ``statusline.py`` itself reads, and hands the channel half to the
identical function, ``channel_status``, that decides the render. There is
nothing to re-derive for the branch marker -- ``gather()`` computes it
inline, collapsing three distinguishable causes into one ``"unknown"``
before ``_default_branch_marker`` ever sees it -- so this module reconstructs
those three causes directly from the cache, in the same order ``gather()``'s
own two conditions test them:

* ``"not-asked"`` -- no cache document exists at all: no board reading has
  ever been cached for this repo.
* ``"stale"`` -- ``board_is_due`` is true: the cached board (including the
  default-branch reading, which shares its clock, #856) is older than its
  own refresh interval, or was marked stale by this session's own merge or
  close (#516). Checked before the raw value below regardless of what that
  value says, mirroring ``gather()``'s own ``or`` -- a stale reading of a
  real value is still ``"unknown"`` there.
* ``"no-answer"`` -- the board is fresh, but the cached
  ``default_branch_state`` is ``None``: the last refresh's own ``gh`` call
  for this branch's CI state did not answer.
* ``"unrecognized"`` -- the board is fresh, and the cached value is present
  but is not one of the four ``_gh_default_branch_state`` can ever produce
  -- a hand-edited or otherwise corrupted cache file.

**A fifth cause, shared by both fields and checked before either one: the
cache file EXISTS and could not be read or parsed (self-review finding,
#1311).** ``statusline.read_cache`` folds "no such file" (``FileNotFoundError``)
and "the file is there and broken" (any other ``OSError``, or a ``ValueError``
from malformed JSON) into the identical ``None`` -- correct for
``statusline.py``'s own render, which treats both as "nothing to show", but
wrong for this module: "nobody has asked yet" and "something is wrong with
the cache" call for different remedies, and this module's own docstring
already draws exactly that line for `.supertool.json`'s
``declaration-unreadable`` state. So this module reads the cache file itself,
distinguishing the three outcomes `Path.read_text`/`json.loads` can actually
produce, rather than reusing `statusline.read_cache`'s collapsed contract --
`cache-unreadable` reports before either field's own not-asked/stale
derivation runs, for both fields at once, since a broken cache file makes
both readers equally unable to answer.

Neither field's ``NOTICE``-vs-``WARN`` split reaches for #764's structurally-
permanent state as a default: only ``channel``'s own ``"not-attributable"``
reason CAN be a genuine, permanent, correct answer (this machine legitimately
shares a socket with another project's fleet) -- but this module cannot
establish from this repository's own files alone whether that is actually
true here, or whether `.supertool.json` simply has not declared a
`watch_name` yet (the fixable case the remedy text itself names). Per the
contract's own first test ("no manual op, no scaffold run" is the bar for
NOTICE, not "might already be correct"), a cause that is not structurally
impossible to clear stays `WARN`, unconditionally, even for `not-attributable`
-- the remedy still names the possibility that nothing further is needed. An
earlier draft downgraded this reason to `NOTICE` unconditionally, which is
exactly backwards: it demoted a class of findings that frequently DOES have a
manual-op fix to the one state the maintainer loop treats as never
actionable (self-review finding, #1311). `could-not-determine` (the
`statusline` module itself failed to import) IS structurally unclearable by
any manual op or scaffold run on THIS repository -- it is an install-time
fact about the plugin, not about the repo being diagnosed -- so it routes
through `doctor.unmeasured` instead of a WARN with no remedy to name
(self-review finding, #1311), the same convention this module's own
top-level ``config is None`` branch already follows.

Python 3.9 compatible.
"""

import json
import time
from pathlib import Path

import doctor

try:
    import statusline
except ImportError:  # pragma: no cover -- statusline.py sits beside this file
    statusline = None


def _refresh_command(project_dir):
    """The one executable remedy shared by every transient reason below: force
    a real refresh rather than wait out the interval. ``None`` only when
    ``scaffold`` itself could not be imported, mirroring every other remedy
    builder in this convention (``doctor_check_statusline.py``'s own
    ``NO_SCAFFOLD``).

    Built with ``Path`` throughout (self-review finding, #1311) -- the first
    draft joined ``project_dir`` and ``OWNED_DIR`` with a literal ``"/"`` in a
    format string, and ``project_dir`` arrives from ``doctor.main()`` as a
    ``Path``, so on Windows that produced backslash-separated segments with a
    literal forward slash spliced between them. ``Path`` normalises the whole
    join to this platform's own separator.
    """
    if doctor.scaffold is None:
        return None
    script = Path(project_dir) / doctor.scaffold.OWNED_DIR / "statusline.py"
    return 'python3 "{}" --refresh --root "{}"'.format(script, project_dir)


def channel_cause(config, cache, now):
    """``{"applicable": False}`` or ``{"applicable": True, "state": ..., "reason": ...}``
    for the watch-channel field, re-deriving exactly what ``gather()`` would
    hand ``_channel_field`` for this ``cache`` right now.

    ``applicable`` is ``False`` only when ``watch_channel`` is explicitly
    ``False`` in ``.oss.json`` -- the deliberate off switch ``_channel_field``
    itself renders as nothing at all, never ``?``, so there is no cause to
    explain.
    """
    config = config if isinstance(config, dict) else {}
    if config.get("watch_channel") is False:
        return {"applicable": False}
    if statusline is None:
        return {
            "applicable": True,
            "state": "cannot_determine",
            "reason": "could-not-determine",
        }
    raw_channel = (cache or {}).get("channel") or {}
    fetched_at = (cache or {}).get("channel_fetched_at")
    result = statusline.channel_status(
        raw_channel.get("raw_state"),
        raw_channel.get("attribution", "not-attributable"),
        fetched_at,
        now,
    )
    return {
        "applicable": True,
        "state": result.get("state"),
        "reason": result.get("reason"),
    }


def default_branch_cause(config, cache, now):
    """``{"applicable": False}`` or ``{"applicable": True, "reason": ..., ...}``
    for the default-branch marker, reconstructing the three causes ``gather()``
    itself collapses into one ``"unknown"`` (see the module docstring).

    ``applicable`` is ``False`` when ``.oss.json`` declares no
    ``default_branch`` at all -- ``_default_branch_marker`` renders nothing
    for that repo, by the same deliberate-absence convention as the channel
    field, so there is no cause to explain.
    """
    config = config if isinstance(config, dict) else {}
    if not config.get("default_branch"):
        return {"applicable": False}
    if statusline is None:
        return {"applicable": True, "reason": "could-not-determine"}
    fetched_at = (cache or {}).get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return {"applicable": True, "reason": "not-asked"}
    if statusline.board_is_due(cache, now):
        return {"applicable": True, "reason": "stale"}
    raw_state = (cache or {}).get("default_branch_state")
    if raw_state in ("green", "bad", "running", "no-run"):
        return {"applicable": True, "reason": None, "state": raw_state}
    if raw_state is None:
        return {"applicable": True, "reason": "no-answer"}
    return {"applicable": True, "reason": "unrecognized", "value": raw_state}


def _read_cache_or_unreadable(path):
    """``(cache, unreadable)`` -- distinguishes "no cache file at all" from
    "a cache file is there and broken" (self-review finding, #1311).

    ``statusline.read_cache`` folds both into the same ``None``, which is
    correct for its own caller (nothing to show either way) and wrong for
    this module: the two causes call for different remedies (run a refresh,
    versus fix or delete a broken file), and this module's own docstring
    already draws exactly that line for ``.supertool.json``. Mirrors
    ``statusline.read_cache``'s own two exception classes -- ``OSError``,
    ``ValueError`` -- rather than inventing a third reading of the same
    bytes.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True
    try:
        document = json.loads(text)
    except ValueError:
        return None, True
    if not isinstance(document, dict):
        return None, True
    return document, False


#: reason -> (doctor state, message template taking `remedy`). Every WARN
#: template names an executable remedy per the doctor-check-contract's own
#: second test; `refresh` is the shared force-a-fresh-read command, built once
#: by the caller and threaded through.
_CHANNEL_EXPLAIN = {
    "not-asked": (
        "WARN",
        "statusline channel: nobody has taken a `channel:health` reading yet "
        "for this repo (no cached channel entry) -- renders `ch?`. {}",
    ),
    "stale": (
        "WARN",
        "statusline channel: the cached `channel:health` reading is older "
        "than its own refresh interval -- renders `ch?`. This self-heals on "
        "the next statusline render (a background refresh forks "
        "automatically), or force it now: {}",
    ),
    "declaration-unreadable": (
        "WARN",
        "statusline channel: `.supertool.json` exists and could not be read "
        "or parsed, so which repo this channel reading belongs to could not "
        "be settled -- renders `ch?`. Fix or remove the malformed file, "
        "then: {}",
    ),
    "unrecognized": (
        "WARN",
        "statusline channel: the last `channel:health` reading did not match "
        "any of the five recognised states -- renders `ch?`. Run `supertool "
        "'channel:health'` directly to see the raw text and confirm "
        "`supertool version` is current, then: {}",
    ),
    "not-attributable": (
        "WARN",
        "statusline channel: the cached channel reading does not attribute "
        "to this repository -- neither derived from `.oss.json` nor declared "
        "in `.supertool.json` -- renders `ch?`. This MAY already be correct "
        "and permanent (this machine could legitimately share a socket with "
        "another project's fleet, in which case no further action is "
        "needed); if this repo should own the channel instead, declare it "
        "explicitly under `ops.<name>.watch_name` in `.supertool.json`, "
        "matching the exported `SUPERTOOL_WATCH_NAME`, then: {}",
    ),
}

_BRANCH_EXPLAIN = {
    "not-asked": (
        "WARN",
        "statusline default-branch marker: no board reading has ever been "
        "cached for this repo -- renders as no marker at all rather than a "
        "real state (`?` once a first reading exists and then goes stale). "
        "{}",
    ),
    "stale": (
        "WARN",
        "statusline default-branch marker: the cached board (including the "
        "default branch's own CI state, which shares its clock, #856) is "
        "older than its own refresh interval, or was marked stale by a "
        "recent merge/close in this session -- renders `unk`. Self-heals on "
        "the next statusline render, or force it now: {}",
    ),
    "no-answer": (
        "WARN",
        "statusline default-branch marker: the last refresh's own `gh` call "
        "for this branch's CI state did not answer -- renders `unk`. Confirm "
        "`gh auth status` and that the configured `default_branch` exists on "
        "the forge, then: {}",
    ),
    "unrecognized": (
        "WARN",
        "statusline default-branch marker: the cached value is not one of "
        "the four states this field can ever produce -- likely a "
        "hand-edited or corrupted cache file -- renders `unk`. Delete the "
        "cache file (see `scripts/statusline.py`'s own `cache_path`) and "
        "then: {}",
    ),
}


def _report_channel(result, remedy):
    if not result.get("applicable"):
        doctor.report(
            "OK",
            "statusline channel: watch_channel is off in .oss.json -- a "
            "deliberate absence, statusline renders nothing for it.",
        )
        return
    reason = result.get("reason")
    if reason == "could-not-determine":
        doctor.unmeasured(
            "statusline channel",
            "the `statusline` module could not be imported, so the cause of "
            "`ch?` could not be re-derived here.",
        )
        return
    state = result.get("state")
    if state and state != "cannot_determine" and reason is None:
        doctor.report(
            "OK",
            "statusline channel: currently reporting {} -- no `?` to explain.".format(
                state
            ),
        )
        return
    level, template = _CHANNEL_EXPLAIN.get(
        reason, ("WARN", "statusline channel: could not be determined -- {}")
    )
    doctor.report(level, template.format(remedy))


def _report_default_branch(result, remedy):
    if not result.get("applicable"):
        doctor.report(
            "OK",
            "statusline default-branch marker: no default_branch declared "
            "in .oss.json -- a deliberate absence, statusline renders "
            "nothing for it.",
        )
        return
    reason = result.get("reason")
    if reason == "could-not-determine":
        doctor.unmeasured(
            "statusline default-branch marker",
            "the `statusline` module could not be imported, so the cause of "
            "`unk` could not be re-derived here.",
        )
        return
    if reason is None:
        doctor.report(
            "OK",
            "statusline default-branch marker: currently reporting {} -- no "
            "`?` to explain.".format(result.get("state")),
        )
        return
    level, template = _BRANCH_EXPLAIN.get(
        reason,
        ("WARN", "statusline default-branch marker: could not be determined -- {}"),
    )
    doctor.report(level, template.format(remedy))


def check_statusline_unknowns(project_dir, config, now=None):
    """Explain the cause of every `?` `statusline.py` can render for the
    watch channel and the default-branch marker, each with a runnable
    remedy (#1311). See the module docstring for the full derivation.
    """
    if config is None:
        doctor.unmeasured("statusline unknowns")
        return
    now = time.time() if now is None else now
    repo = config.get("repo") if isinstance(config, dict) else None
    remedy = _refresh_command(project_dir) or (
        "run `python3 <path-to>/statusline.py --refresh --root {}` "
        "(scaffold.py could not be imported to name the exact path)".format(project_dir)
    )
    if statusline is None or not repo:
        cache = None
    else:
        cache, unreadable = _read_cache_or_unreadable(statusline.cache_path(repo))
        if unreadable:
            message = (
                "statusline: the cached board/channel state exists on disk "
                "and could not be read or parsed, so neither field's cause "
                "could be established -- fix or delete the cache file (see "
                "`scripts/statusline.py`'s own `cache_path`), then: {}".format(remedy)
            )
            doctor.report("WARN", message)
            return
    _report_channel(channel_cause(config, cache, now), remedy)
    _report_default_branch(default_branch_cause(config, cache, now), remedy)
