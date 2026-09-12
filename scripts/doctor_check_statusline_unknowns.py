"""``check_statusline_unknowns`` -- names the exact cause behind every ``?``
``statusline.py`` can render for the watch channel, the default-branch
marker, and (#1345) the ``/oss:doctor`` reading, each paired with an
executable remedy (#1311).

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

**All three readers, re-derived rather than read off a computed fact.**
``statusline.py`` never writes its own reasoning to disk, only the collapsed
render -- so this module re-derives the same inputs (``raw_state``,
``attribution``, ``channel_fetched_at`` for the channel; ``fetched_at``,
``default_branch_state`` for the branch marker; ``doctor_fetched_at``,
``doctor_verdict`` for the doctor reading) from the identical cache file
``statusline.py`` itself reads, and hands the channel half to the identical
function, ``channel_status``, that decides the render. There is
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

**The `/oss:doctor` reading (`dr`), and why it gets no bulleted derivation
here the way the two fields above do (#1345).** Unlike the channel and
default-branch fields, the cache carries no code for WHICH of five distinct
causes (no `doctor.py` located, the subprocess could not start,
`DOCTOR_TIMEOUT` expiry, a non-zero exit, no `VERDICT:` line) produced a
`None` verdict -- `statusline.py`'s own `_doctor_reading` folds all five into
the identical `None` before it is ever written to disk. So `doctor_cause`
distinguishes only what the cache DOES allow (never asked, stale, an
unrecognised verdict shape, and the honest `"no-answer"` fold of the five
real causes) rather than a five-way split this module cannot see through the
cache alone -- see `doctor_cause`'s own docstring for the full reasoning.

**`repo-missing`, a cause shared by all three fields (self-review finding,
#1345).** A `.oss.json` with no usable `repo` means there is nowhere to look
up a cache at all -- distinct from `"not-asked"`, whose own remedy
(`--refresh`) cannot resolve anything without `repo` set either. Computed
once in `check_statusline_unknowns` and threaded through every `*_cause`
call, checked ahead of `cache-unreadable` and the individual not-asked/stale
derivations for the same reason: no `repo` means `cache` itself is `None`
for a reason distinct from either of those.

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
    # #1426: `str(script)`/`project_dir` used to go straight into the
    # double-quoted shell string below with no escaping -- a `"` anywhere in
    # either interpolated path terminates that quoting early, so a
    # maintainer who pastes the remedy runs something other than a
    # statusline refresh. `shlex.quote()` is the wrong tool here: it wraps
    # the whole value in single quotes, which is a different quoting
    # convention than the double-quoted form every other remedy in this
    # module already uses (and single quotes are not stripped by Windows'
    # `cmd.exe`, where they would be passed into argv literally). Escaping
    # only the one character that could break the existing double quotes
    # keeps the remedy's shape identical for every path that does not
    # contain one.
    quoted_script = str(script).replace('"', '\\"')
    quoted_project_dir = str(project_dir).replace('"', '\\"')
    return 'python3 "{}" --refresh --root "{}"'.format(
        quoted_script, quoted_project_dir
    )


def channel_cause(config, cache, now, repo_missing=False):
    """``{"applicable": False}`` or ``{"applicable": True, "state": ..., "reason": ...}``
    for the watch-channel field, re-deriving exactly what ``gather()`` would
    hand ``_channel_field`` for this ``cache`` right now.

    ``applicable`` is ``False`` only when ``watch_channel`` is explicitly
    ``False`` in ``.oss.json`` -- the deliberate off switch ``_channel_field``
    itself renders as nothing at all, never ``?``, so there is no cause to
    explain.

    ``repo_missing`` -- #1345 -- is ``True`` when ``.oss.json`` declares no
    usable ``repo``, which is the caller's own signal that ``cache`` is
    ``None`` for a reason distinct from "nobody has asked yet": there is
    nowhere to look up a cache at all. Checked before ``cache`` is read at
    all, because a missing ``repo`` would otherwise be indistinguishable
    from ``"not-asked"`` and the remedy that reason names (run a refresh)
    cannot itself resolve without ``repo`` either.
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
    if repo_missing:
        return {
            "applicable": True,
            "state": "cannot_determine",
            "reason": "repo-missing",
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


def default_branch_cause(config, cache, now, repo_missing=False):
    """``{"applicable": False}`` or ``{"applicable": True, "reason": ..., ...}``
    for the default-branch marker, reconstructing the three causes ``gather()``
    itself collapses into one ``"unknown"`` (see the module docstring).

    ``applicable`` is ``False`` when ``.oss.json`` declares no
    ``default_branch`` at all -- ``_default_branch_marker`` renders nothing
    for that repo, by the same deliberate-absence convention as the channel
    field, so there is no cause to explain.

    ``repo_missing`` -- see ``channel_cause``'s own docstring, #1345 -- is the
    identical signal for this field: no ``repo`` means no cache to look up,
    which must not read as "nobody has asked yet".
    """
    config = config if isinstance(config, dict) else {}
    if not config.get("default_branch"):
        return {"applicable": False}
    if statusline is None:
        return {"applicable": True, "reason": "could-not-determine"}
    if repo_missing:
        return {"applicable": True, "reason": "repo-missing"}
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


#: `_doctor_verdict_state`'s own three recognised VERDICT shapes, matched the
#: identical way (`==` for the bare "ok", `startswith` for the other two, since
#: both carry a trailing count `doctor.py` formats itself). Duplicated rather
#: than reached for through `statusline._doctor_verdict_state` -- every other
#: cross-module call in this file goes through a PUBLIC name (`channel_status`,
#: `board_is_due`, `cache_path`, both `_REFRESH_AFTER` constants); reaching into
#: a leading-underscore name would be new coupling this module has avoided
#: everywhere else. `test_doctor_classification_agrees_with_statusline_own_
#: classifier` pins the two against each other so a drift here is caught rather
#: than silently misreporting a real reading as `dr?`'s own unexplained state.
def _doctor_verdict_reason(verdict):
    # Self-review finding, #1345: `_read_cache_or_unreadable` only validates
    # that the parsed cache document is a dict overall -- it never validates
    # any individual field's type, so a hand-edited or otherwise malformed
    # cache can carry a non-string `doctor_verdict` (an int, a list, ...).
    # `.startswith` below would raise `AttributeError` for one, which is
    # exactly doctor.py's own "exit 0 always" contract this module's
    # docstrings elsewhere invoke -- so a non-string value folds into
    # `"unrecognized"` here, the same state a corrupted-but-string value
    # already gets, rather than propagating.
    if not isinstance(verdict, str):
        return "unrecognized"
    if verdict == "ok":
        return None
    if verdict.startswith("usable with gaps") or verdict.startswith("not usable"):
        return None
    return "unrecognized"


def doctor_cause(cache, now, repo_missing=False):
    """``{"reason": ..., ...}`` for the `/oss:doctor` field (``dr``), explaining
    the cause of a rendered ``?`` as far as the cache allows (#1345).

    There is no deliberate off switch for this field the way ``watch_channel:
    false`` turns ``channel_cause`` off -- ``/oss:doctor`` runs unconditionally
    -- so, unlike the other two ``*_cause`` functions, this one has no
    ``"applicable": False`` arm.

    **Unlike ``channel_cause``/``default_branch_cause``, the cache does not
    carry enough to name which of ``_doctor_reading``'s five causes produced a
    ``None`` verdict** -- no ``doctor.py`` located, the subprocess could not be
    started, ``DOCTOR_TIMEOUT`` expiry, a non-zero exit, and no ``VERDICT:``
    line in the output all fold into the identical ``None`` in
    ``statusline.py`` before it is ever written to disk. Re-running the
    diagnostic here to tell them apart would mean this module -- itself one of
    doctor's own checks -- spawning a second, recursive `doctor.py` subprocess
    on every render, which is exactly the cost `_doctor_reading` already pays
    once per refresh interval and is not this check's to pay again. So
    ``"no-answer"`` below names the fold honestly, per the issue's own stated
    fallback, rather than guessing at which of the five actually happened.
    """
    if statusline is None:
        return {"reason": "could-not-determine"}
    if repo_missing:
        return {"reason": "repo-missing"}
    fetched_at = (cache or {}).get("doctor_fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return {"reason": "not-asked"}
    if now - fetched_at >= statusline.DOCTOR_REFRESH_AFTER:
        return {"reason": "stale"}
    verdict = (cache or {}).get("doctor_verdict")
    if verdict is None:
        return {"reason": "no-answer"}
    reason = _doctor_verdict_reason(verdict)
    if reason == "unrecognized":
        return {"reason": "unrecognized", "value": verdict}
    return {"reason": None, "state": verdict}


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
        "for this repo (no cached channel entry) -- renders `ch?`. {remedy}",
    ),
    "stale": (
        # #1440: a cache clock running out settles on its own -- the very
        # next statusline render forks a background refresh -- so it is not
        # a WARN wearing a self-heal disclaimer, it is a WAIT. Every other
        # row in this table stays WARN: none of them names a moment that
        # clears the gap on its own the way this one's own refresh interval
        # does.
        "WAIT",
        "statusline channel: the cached `channel:health` reading is older "
        "than its own refresh interval -- renders `ch?`. {fork_sentence} Or "
        "force it synchronously now: {remedy}",
    ),
    "declaration-unreadable": (
        "WARN",
        "statusline channel: `.supertool.json` exists and could not be read "
        "or parsed, so which repo this channel reading belongs to could not "
        "be settled -- renders `ch?`. Fix or remove the malformed file, "
        "then: {remedy}",
    ),
    "unrecognized": (
        "WARN",
        "statusline channel: the last `channel:health` reading did not match "
        "any of the five recognised states -- renders `ch?`. Run `supertool "
        "'channel:health'` directly to see the raw text and confirm "
        "`supertool version` is current, then: {remedy}",
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
        "matching the exported `SUPERTOOL_WATCH_NAME`, then: {remedy}",
    ),
    "repo-missing": (
        "WARN",
        "statusline channel: `.oss.json` declares no `repo` (or it is blank), "
        "so there is nowhere to look up a cached channel reading -- renders "
        "`ch?`. Add `repo` to `.oss.json` first; running a refresh before "
        "that will not help, since it also cannot compute where to write "
        "the cache.",
    ),
}

_BRANCH_EXPLAIN = {
    "not-asked": (
        "WARN",
        "statusline default-branch marker: no board reading has ever been "
        "cached for this repo -- renders as no marker at all rather than a "
        "real state (`?` once a first reading exists and then goes stale). "
        "{remedy}",
    ),
    "stale": (
        "WARN",
        "statusline default-branch marker: the cached board (including the "
        "default branch's own CI state, which shares its clock, #856) is "
        "older than its own refresh interval, or was marked stale by a "
        "recent merge/close in this session -- renders `unk`. {fork_sentence} "
        "Or force it synchronously now: {remedy}",
    ),
    "no-answer": (
        "WARN",
        "statusline default-branch marker: the last refresh's own `gh` call "
        "for this branch's CI state did not answer -- renders `unk`. Confirm "
        "`gh auth status` and that the configured `default_branch` exists on "
        "the forge, then: {remedy}",
    ),
    "unrecognized": (
        "WARN",
        "statusline default-branch marker: the cached value is not one of "
        "the four states this field can ever produce -- likely a "
        "hand-edited or corrupted cache file -- renders `unk`. Delete the "
        "cache file (see `scripts/statusline.py`'s own `cache_path`) and "
        "then: {remedy}",
    ),
    "repo-missing": (
        "WARN",
        "statusline default-branch marker: `.oss.json` declares no `repo` "
        "(or it is blank), so there is nowhere to look up a cached board "
        "reading -- renders `unk`. Add `repo` to `.oss.json` first; running "
        "a refresh before that will not help, since it also cannot compute "
        "where to write the cache.",
    ),
}

#: reason -> (doctor state, message template taking `remedy`), the `dr` field's
#: own version of `_CHANNEL_EXPLAIN`/`_BRANCH_EXPLAIN` above. `"no-answer"` is
#: the honest fold of the five causes `doctor_cause`'s own docstring names --
#: this check does not guess at which one happened.
_DOCTOR_EXPLAIN = {
    "repo-missing": (
        "WARN",
        "/oss:doctor reading: `.oss.json` declares no `repo` (or it is "
        "blank), so there is nowhere to look up a cached doctor reading -- "
        "renders `dr?`. Add `repo` to `.oss.json` first; running a refresh "
        "before that will not help, since it also cannot compute where to "
        "write the cache.",
    ),
    "not-asked": (
        "WARN",
        "/oss:doctor reading: nobody has taken a doctor reading yet for "
        "this repo (no cached `doctor_verdict`) -- renders `dr?`. {remedy}",
    ),
    "stale": (
        "WARN",
        "/oss:doctor reading: the cached doctor reading is older than its "
        "own refresh interval -- renders `dr?`. {fork_sentence} Or force it "
        "synchronously now: {remedy}",
    ),
    "no-answer": (
        "WARN",
        "/oss:doctor reading: the last background doctor run produced no "
        "verdict this statusline can read back -- renders `dr?`. The cache "
        "does not record which of five causes it was (no doctor.py located, "
        "the subprocess could not start, DOCTOR_TIMEOUT expired, it exited "
        "non-zero, or its output had no `VERDICT:` line); run `/oss:doctor` "
        "(or the script directly) to see the real one, then: {remedy}",
    ),
    "unrecognized": (
        "WARN",
        "/oss:doctor reading: the cached verdict text does not match any "
        "shape doctor.py's own main() is known to print -- renders `dr?`. "
        "Run `/oss:doctor` directly to see the raw VERDICT line, then: {remedy}",
    ),
}


#: The two `{fork_sentence}` fillers a "stale" template's `.format()` call
#: chooses between (#1373's own reviewer round) -- `_fork_refresh` (via the
#: public `statusline.fork_refresh`) now REPORTS whether it actually started
#: a new detached process, so the WARN a reader sees stops claiming a fork
#: "just" happened when the attempt was skipped (a busy lock) or failed (the
#: lock write, or the `Popen` itself).
_FORK_SUCCEEDED_SENTENCE = (
    "This check just forked a background refresh itself; it should "
    "self-heal in moments."
)
_FORK_NOT_STARTED_SENTENCE = (
    "This check tried to fork a background refresh but none was started -- "
    "a refresh may already be in flight from another render, or the "
    "attempt itself failed."
)


def _fork_sentence(forked):
    return _FORK_SUCCEEDED_SENTENCE if forked else _FORK_NOT_STARTED_SENTENCE


def _report_channel(result, remedy, forked=False):
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
        reason, ("WARN", "statusline channel: could not be determined -- {remedy}")
    )
    doctor.report(
        level, template.format(remedy=remedy, fork_sentence=_fork_sentence(forked))
    )


def _report_default_branch(result, remedy, forked=False):
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
        (
            "WARN",
            "statusline default-branch marker: could not be determined -- {remedy}",
        ),
    )
    doctor.report(
        level, template.format(remedy=remedy, fork_sentence=_fork_sentence(forked))
    )


def _report_doctor(result, remedy, forked=False):
    reason = result.get("reason")
    if reason == "could-not-determine":
        doctor.unmeasured(
            "/oss:doctor reading",
            "the `statusline` module could not be imported, so the cause of "
            "`dr?` could not be re-derived here.",
        )
        return
    if reason is None:
        doctor.report(
            "OK",
            "/oss:doctor reading: currently reporting {} -- no `?` to explain.".format(
                result.get("state")
            ),
        )
        return
    level, template = _DOCTOR_EXPLAIN.get(
        reason, ("WARN", "/oss:doctor reading: could not be determined -- {remedy}")
    )
    doctor.report(
        level, template.format(remedy=remedy, fork_sentence=_fork_sentence(forked))
    )


def _maybe_fork_refresh(project_dir, repo, now):
    """Fork a background refresh the moment THIS check finds a stale cache
    (#1373), rather than only naming a command for the reader to run by
    hand. Doctor already reads the cache to derive the cause below -- this
    is the same read, spending nothing new to also start the fix.

    Deliberately calls `statusline.fork_refresh` -- a public wrapper added
    for exactly this caller, per the module docstring's own rule against
    reaching into a leading-underscore name -- never `statusline.
    _fork_refresh` directly. Best-effort: `fork_refresh` already swallows
    every failure it can reach (a lock it cannot write, a `Popen` that
    cannot start), so nothing here needs its own `try`/`except` to keep
    doctor's "exit 0, always" contract.

    This clears the cache the same way `/oss:release`'s own
    `invalidate_latest_cache` does -- an actor OTHER than the render path
    starting the fix at the moment it finds the falsified/stale state --
    rather than writing a diagnosis into the cache itself: the fork starts
    an ordinary `--refresh` subprocess, the identical one a live statusline
    render already forks on its own when `board_is_due`. Deleting or
    rewriting cache fields directly, from inside a diagnostic, would cross
    into repair; forking the same self-healing refresh the render path
    already trusts does not -- see CLAUDE.md's "a diagnosis is not a
    repair" and this file's own PR body for the fuller argument.
    """
    if statusline is None or not repo:
        return False
    return statusline.fork_refresh(project_dir, repo, now=now)


def check_statusline_unknowns(project_dir, config, now=None):
    """Explain the cause of every `?` `statusline.py` can render for the
    watch channel, the default-branch marker, and (#1345) the `/oss:doctor`
    reading, each with a runnable remedy (#1311). See the module docstring
    for the full derivation.

    #1373: when any of the three causes below is `"stale"`, this also forks
    the same background refresh a live statusline render would have forked
    on its own -- see `_maybe_fork_refresh`'s own docstring for why that
    stays inside the report-only contract rather than crossing into repair.
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
    # #1345: a missing/blank `repo` must not collapse onto "not-asked" -- it
    # is a different cause (nowhere to look up a cache at all) with a
    # different remedy (add `repo`, not `--refresh`, which cannot resolve
    # anything until `repo` is set). Computed once here and threaded through
    # every `*_cause` call below, rather than each one re-deriving it from
    # `config` -- `statusline is None` alone already means "cannot tell", so
    # `repo_missing` is only ever true when `statusline` loaded and `repo`
    # itself is genuinely absent or blank.
    repo_missing = statusline is not None and not repo
    if statusline is None or not repo:
        cache = None
    else:
        cache, unreadable = _read_cache_or_unreadable(statusline.cache_path(repo))
        if unreadable:
            message = (
                "statusline: the cached board/channel/doctor state exists on "
                "disk and could not be read or parsed, so no field's cause "
                "could be established -- fix or delete the cache file (see "
                "`scripts/statusline.py`'s own `cache_path`), then: {}".format(remedy)
            )
            doctor.report("WARN", message)
            return
    channel_result = channel_cause(config, cache, now, repo_missing)
    branch_result = default_branch_cause(config, cache, now, repo_missing)
    doctor_result = doctor_cause(cache, now, repo_missing)
    # #1373's own reviewer round: `forked` is threaded into every `_report_*`
    # call below so the WARN text reflects what `_maybe_fork_refresh` ACTUALLY
    # did, never a blanket claim -- `False` (the default) is also the correct
    # value passed when nothing was stale, since `_fork_sentence` is only
    # ever read from a "stale" template.
    forked = False
    if not repo_missing and any(
        result.get("reason") == "stale"
        for result in (channel_result, branch_result, doctor_result)
    ):
        forked = _maybe_fork_refresh(project_dir, repo, now)
    _report_channel(channel_result, remedy, forked)
    _report_default_branch(branch_result, remedy, forked)
    _report_doctor(doctor_result, remedy, forked)
