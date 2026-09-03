"""``check_channel_health_agreement`` -- compares doctor's own channel MCP
consumer census against supertool's ``channel:health``, and reports whether
the two instruments agree (#860).

A new check, so it lives in its own module from the start rather than going
inline in ``doctor.py`` -- the convention block at the top of that file.

Both instruments answer the same question: is a second channel-capable MCP
server racing this repo's socket? For three release cycles they answered it
oppositely on the same machine, in the same second, and nothing compared
them. ``channel_consumer_census_state`` (``doctor_check_mcp_channel_
registration.py``, #630/#810) is the census half, read from this repo's own
tracked config and ``claude mcp list``. ``channel:health`` is the other half,
read the way ``scripts/statusline.py`` already knows how to
(``_run_channel_health`` / ``parse_channel_report``).

``channel:health`` is classed ``acts`` in supertool's own op roster -- it
spawns ``claude mcp get`` -- and ``statusline.py``'s own constant documents a
worst case north of 20s. This module never pays that cost on its own: by
default it reuses whatever reading ``statusline.py``'s own detached refresh
already cached for this repo, and carries that reading's own age forward
rather than asserting it fresh (the #549/#550 lesson CLAUDE.md documents at
length). A cached reading older than its own refresh interval, or no cached
reading at all, is ``could-not-compare`` -- never silently read as
agreement. ``OSS_DOCTOR_CHANNEL_HEALTH=1`` (or ``allow_probe=True`` passed
directly) opts into paying the real cost and probing ``channel:health``
fresh instead.

Python 3.9 compatible.
"""

import os
import time

import doctor
from doctor_check_mcp_channel_registration import channel_consumer_census_state

try:
    import statusline
except ImportError:  # pragma: no cover -- statusline.py sits beside this file
    statusline = None

#: Explicit opt-in only -- see the module docstring for why this check never
#: spends channel:health's own `acts`-classed cost by default.
CHANNEL_HEALTH_PROBE_ENV = "OSS_DOCTOR_CHANNEL_HEALTH"

#: Used only when `statusline` could not be imported at all, so a cached
#: reading still has SOME staleness bound rather than none.
_FALLBACK_MAX_AGE = 900


def _census_signal(state):
    """True/False/None -- does doctor's own census say a second server races
    this socket? None is `could-not-ask`, never folded into either answer."""
    if state == "collision":
        return True
    if state in ("single", "none"):
        return False
    return None


def _health_signal(raw_state):
    """True/False/None -- the same question, from a `channel:health` reading.

    CANNOT DETERMINE and CONTRADICTED are `channel:health`'s own way of
    saying the socket answered something other than one clean consumer --
    the shape actually measured on #860's own incident, where doctor's
    census said `single` and `channel:health` said CANNOT DETERMINE. #860
    read that as a second server declaring the same socket unconditionally;
    #913's own investigation instead traced a later recurrence of the
    identical shape to claude-supertool#2208 -- no second server at all, its
    own subscription probe self-colliding with the live socket. Both are
    real, on different occasions, and this docstring does not adjudicate
    between them; `channel_health_agreement_state`'s own `disagree` branch is
    where the #913 finding is actually surfaced. FORWARDING, NOT DELIVERING
    and BOUND-NOT-SUBSCRIBED are all single-consumer readings (delivering or
    not, but from one server rather than two racing for it).
    """
    if raw_state in ("cannot_determine", "contradicted"):
        return True
    if raw_state in ("forwarding", "not_delivering", "not_subscribed"):
        return False
    return None


def _census_words(state, detail):
    if state == "collision":
        return "collision -- {} configured MCP server(s) resolve to the consumer script ({})".format(
            len(detail), ", ".join(detail)
        )
    if state == "single":
        return "single -- 1 configured MCP server resolves to the consumer script ({})".format(
            detail
        )
    if state == "none":
        return "none -- no configured MCP server resolves to the consumer script"
    return "could-not-ask -- {}".format(detail)


def _health_words(raw_state, source, age):
    if source is None:
        return "no reading available (not probed, and no fresh-enough cached one)"
    if source == "cached-stale":
        return "the cached reading is older than its own refresh interval ({:.0f}s)".format(
            age if isinstance(age, (int, float)) else -1
        )
    if raw_state is None:
        return "{} reading carried no recognised channel: state".format(source)
    aged = " ({:.0f}s old)".format(age) if isinstance(age, (int, float)) and age else ""
    return "{}{} reading: {}".format(source, aged, raw_state)


def resolve_channel_health_reading(project_dir, allow_probe=False, probe=None, now=None,
                                    max_age=None):
    """``(raw_state, source, age)`` for the health half of the comparison.

    ``source`` is ``"probed"``, ``"cached"``, ``"cached-stale"`` or ``None``
    (nothing usable at all). Only ``"probed"`` and ``"cached"`` carry a
    ``raw_state`` a caller may compare against; the other two are always
    ``could-not-compare`` upstream. ``age`` is the reading's own age in
    seconds -- ``0.0`` for a fresh probe, the real age for a cached one,
    ``None`` when there is nothing to age.
    """
    now = time.time() if now is None else now
    if allow_probe:
        if probe is None:
            if statusline is None:
                return None, None, None
            probe = statusline._run_channel_health
        text = probe()
        raw_state = (
            statusline.parse_channel_report(text)
            if statusline is not None and text is not None
            else None
        )
        return raw_state, "probed", 0.0
    if statusline is None:
        return None, None, None
    config = statusline.repo_config(project_dir)
    repo = config.get("repo") if isinstance(config, dict) else None
    if not repo:
        return None, None, None
    cache = statusline.read_cache(statusline.cache_path(repo))
    channel = cache.get("channel") if isinstance(cache, dict) else None
    fetched_at = cache.get("channel_fetched_at") if isinstance(cache, dict) else None
    if not isinstance(channel, dict) or not isinstance(fetched_at, (int, float)):
        return None, None, None
    age = now - fetched_at
    limit = (
        max_age if max_age is not None
        else getattr(statusline, "CHANNEL_REFRESH_AFTER", _FALLBACK_MAX_AGE)
    )
    if age > limit:
        return None, "cached-stale", age
    return channel.get("raw_state"), "cached", age


def channel_health_agreement_state(census_state, census_detail, health_raw_state,
                                    health_source, health_age=None):
    """``(state, detail)`` -- ``agree`` / ``disagree`` / ``could-not-compare``.

    Never picks a winner on `disagree`: naming both readings verbatim is the
    whole of what this function does, on purpose (#860 -- "doctor was right
    this once" is not a general rule and encoding it as one would make this a
    second opinion rather than a comparison). One exception, and it is a
    citation rather than a verdict (#913): when the disagreement is exactly
    `census: single` against a raw `channel:health` state of
    `cannot_determine` or `contradicted`, one extra sentence names
    claude-supertool#2208 as the known cause of that specific shape and says
    the census is the half to believe -- both readings still render verbatim
    first, and every other disagreement stays exactly as silent as before.
    """
    census_signal = _census_signal(census_state)
    health_signal = (
        _health_signal(health_raw_state) if health_source in ("probed", "cached") else None
    )
    census_words = _census_words(census_state, census_detail)
    health_words = _health_words(health_raw_state, health_source, health_age)
    if census_signal is None or health_signal is None:
        return "could-not-compare", "census: {}. channel:health: {}.".format(
            census_words, health_words
        )
    if census_signal == health_signal:
        verdict = (
            "a second channel-capable server"
            if census_signal
            else "no second channel-capable server"
        )
        return "agree", "both report {} -- census: {}. channel:health: {}.".format(
            verdict, census_words, health_words
        )
    detail = "census: {}. channel:health: {}.".format(census_words, health_words)
    if census_state == "single" and health_raw_state in ("cannot_determine", "contradicted"):
        # #913: this exact combination has one overwhelmingly likely cause,
        # claude-supertool#2208 -- its own subscription probe spawns a second
        # instance of the consumer server, that instance cannot take the live
        # socket (claude-supertool#550), writes a `.refused.json` marker, and
        # the same run reads its own marker back as CANNOT DETERMINE (or
        # CONTRADICTED). Self-inflicted, every run, until #2208 ships. Name it
        # rather than making a maintainer re-derive it -- #913's own issue
        # records two retracted issues (#911, #912) spent doing exactly that.
        # No expiry: this codebase has no structured read of a *resolved*
        # supertool's own version to compare against a fix version, and #2208
        # names no fix version to compare against either -- see this module's
        # docstring and #913's own report for why the sentence stays
        # unconditional rather than guessing at either.
        detail += (
            " Known cause: claude-supertool#2208 -- its subscription probe "
            "self-collides with the live socket and reads its own refusal "
            "marker back as this exact channel:health state. Believe the "
            "census in this combination."
        )
    return "disagree", detail


def _preset_disabled(project_dir):
    """`True` only when `.supertool.json` was actually read and explicitly does
    NOT declare the `watch` preset -- the one `could-not-compare` cause that is
    structurally permanent rather than transient. `None`/`False` from
    `_watch_preset_declared` (no file, unreadable, or genuinely enabled) must
    never be read as "disabled"; only its own `False` answers that."""
    if statusline is None:
        return False
    try:
        return statusline._watch_preset_declared(project_dir) is False
    except OSError:
        return False


def check_channel_health_agreement(project_dir, run=None, which=None, env=None,
                                    allow_probe=None, now=None, probe=None):
    """One line: does doctor's own channel census agree with `channel:health`?

    Never `OK` on `could-not-compare` -- named explicitly rather than
    defaulted to `agree`, which #860's own issue calls load-bearing: the
    `watch` preset may simply not be enabled, in which case there is nothing
    to compare and this must say so.

    That last case gets its own render level, NOTICE rather than WARN
    (self-review finding on this same change): a repo whose `.supertool.json`
    plainly does not enable `watch` can never produce a `channel:health`
    reading to compare against, by construction, until somebody edits that
    file -- the identical "structurally unable to ever answer" shape #764
    created NOTICE for two other doctor.py checks to stop rendering as a
    permanent, unresolvable WARN. Every OTHER could-not-compare cause
    (`claude mcp list` failing, a stale or absent cache) stays WARN: each is
    an environment or timing fact that can clear on its own without a config
    edit.
    """
    env = os.environ if env is None else env
    if allow_probe is None:
        allow_probe = bool(env.get(CHANNEL_HEALTH_PROBE_ENV))
    census_state, census_detail = channel_consumer_census_state(run=run, which=which, env=env)
    health_raw_state, health_source, health_age = resolve_channel_health_reading(
        project_dir, allow_probe=allow_probe, probe=probe, now=now
    )
    state, detail = channel_health_agreement_state(
        census_state, census_detail, health_raw_state, health_source, health_age
    )
    if state == "agree":
        doctor.report("OK", "channel census vs channel:health: {}".format(detail))
        return
    if state == "disagree":
        doctor.report(
            "WARN",
            "channel census vs channel:health: disagree, and neither is assumed "
            "right -- {}".format(detail),
        )
        return
    if health_source in (None, "cached-stale") and _preset_disabled(project_dir):
        doctor.report(
            "NOTICE",
            "channel census vs channel:health: could not compare -- the `watch` "
            "preset is not enabled in .supertool.json, so channel:health has "
            "nothing to answer with until that changes -- {}".format(detail),
        )
        return
    doctor.report(
        "WARN",
        "channel census vs channel:health: could not compare -- {}".format(detail),
    )
