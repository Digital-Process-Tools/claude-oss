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

* ``"not-asked"`` -- ``cache["fetched_at"]`` is missing or non-numeric: no
  board reading has ever been cached for this repo.
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

Neither field's ``NOTICE``-vs-``WARN`` split reaches for #764's structurally-
permanent state wholesale: only ``channel``'s own ``"not-attributable"``
reason can be a genuine, permanent, correct answer (this machine legitimately
shares a socket with another project's fleet), so that one reason alone
renders ``NOTICE`` when nothing in ``.oss.json``/``.supertool.json`` looks
fixable, and ``WARN`` -- with the same fixable remedy -- otherwise. Every
other reason here is transient or configuration-fixable and stays ``WARN``.

Python 3.9 compatible.
"""

import time

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
    ``NO_SCAFFOLD``)."""
    if doctor.scaffold is None:
        return None
    return 'python3 "{}/{}/statusline.py" --refresh --root "{}"'.format(
        project_dir, doctor.scaffold.OWNED_DIR, project_dir
    )


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
        "in `.supertool.json` -- renders `ch?`. If this machine genuinely "
        "shares a socket with another project's fleet, this is a correct, "
        "permanent `?` and nothing further is needed; if this repo should "
        "own the channel, declare it explicitly under `ops.<name>.watch_name` "
        "in `.supertool.json`, matching the exported `SUPERTOOL_WATCH_NAME`, "
        "then: {}",
    ),
    "could-not-determine": (
        "WARN",
        "statusline channel: the `statusline` module could not be imported, "
        "so the cause of `ch?` could not be re-derived here.",
    ),
}

#: The one reason above that CAN be a permanent, correct answer -- downgraded
#: to NOTICE only when nothing in the two declared config files looks fixable
#: (mirrors #764's own pattern, applied by `doctor_check_channel_health_
#: agreement.py`'s `_preset_disabled` one check over).
_CHANNEL_NOTICE_REASON = "not-attributable"

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
    "could-not-determine": (
        "WARN",
        "statusline default-branch marker: the `statusline` module could "
        "not be imported, so the cause of `unk` could not be re-derived "
        "here.",
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
    state = result.get("state")
    reason = result.get("reason")
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
    if reason == _CHANNEL_NOTICE_REASON:
        level = "NOTICE"
    message = template.format(remedy) if "{}" in template else template
    doctor.report(level, message)


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
    message = template.format(remedy) if "{}" in template else template
    doctor.report(level, message)


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
    cache = None
    if statusline is not None and repo:
        cache = statusline.read_cache(statusline.cache_path(repo))
    remedy = _refresh_command(project_dir) or (
        "run `python3 <path-to>/statusline.py --refresh --root {}` "
        "(scaffold.py could not be imported to name the exact path)".format(project_dir)
    )
    _report_channel(channel_cause(config, cache, now), remedy)
    _report_default_branch(default_branch_cause(config, cache, now), remedy)
