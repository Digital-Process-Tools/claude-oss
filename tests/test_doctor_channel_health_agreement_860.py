"""#860: doctor's own channel MCP consumer census and supertool's
`channel:health` answer the same question -- is a second channel-capable MCP
server racing this repo's socket? -- and disagreed for three release cycles
because nothing compared them. This file covers the comparison itself
(`channel_health_agreement_state`), the age-aware reuse of a cached
`channel:health` reading (`resolve_channel_health_reading`), and the check
that reports all three outcomes.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_channel_health_agreement as agreement  # noqa: E402
import doctor_check_mcp_channel_registration as mcp_mod  # noqa: E402


def setup_function(_):
    doctor.FINDINGS.clear()


@pytest.fixture(autouse=True)
def _no_plugin_population(tmp_path, monkeypatch):
    """#1241 gave `channel_consumer_census_state` a second population
    (installed plugins' own `.mcp.json` servers), read from a real,
    machine-specific registry path by default. This file predates that and
    asserts only against the `claude mcp list` half -- without this, two
    tests here picked up this repo's own real
    `~/.claude/plugins/installed_plugins.json` (a real, and on this
    development machine DUPLICATED, supertool install), turning an expected
    `single`/`agree` into `collision`/`OK`. Pointing `_PLUGIN_REGISTRY_PATH`
    at a path that does not exist makes the plugin half of the census always
    resolve to `([], None)` for every test in this file."""
    monkeypatch.setattr(
        mcp_mod, "_PLUGIN_REGISTRY_PATH", str(tmp_path / "no-such-registry.json")
    )


# --------------------------------------------------------------------------
# channel_health_agreement_state: the three outcomes, named rather than
# defaulted.
# --------------------------------------------------------------------------


def test_both_instruments_reporting_no_collision_agree():
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", "forwarding", "cached", 5.0
    )
    assert state == "agree", detail
    assert "no second channel-capable server" in detail, detail


def test_both_instruments_reporting_a_collision_agree():
    state, detail = agreement.channel_health_agreement_state(
        "collision", ["oss-channel", "other"], "cannot_determine", "probed", 0.0
    )
    assert state == "agree", detail
    assert "a second channel-capable server" in detail, detail


def test_the_860_incident_itself_is_a_disagreement():
    """The actual measurement on #860's own issue: doctor's census said
    `single` (no collision) while `channel:health` said `CANNOT DETERMINE`.
    Both readings are still named verbatim -- #913 added a known-cause
    sentence for exactly this combination (covered separately below), but
    it never replaces either reading or silently overrides the WARN."""
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", "cannot_determine", "cached", 12.0
    )
    assert state == "disagree", detail
    assert "single" in detail, detail
    assert "cannot_determine" in detail, detail


def test_disagree_known_cause_hint_fires_for_single_census_and_cannot_determine():
    """#913: this exact combination -- census says `single` (no collision) while
    channel:health says CANNOT DETERMINE -- has one overwhelmingly likely cause
    (claude-supertool#2208), and re-deriving it cost two retracted issues
    (#911, #912). Name it."""
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", "cannot_determine", "cached", 12.0
    )
    assert state == "disagree", detail
    assert "claude-supertool#2208" in detail, detail
    assert "census" in detail.lower()


def test_disagree_known_cause_hint_fires_for_single_census_and_contradicted():
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", "contradicted", "probed", 0.0
    )
    assert state == "disagree", detail
    assert "claude-supertool#2208" in detail, detail


def test_disagree_known_cause_hint_does_not_fire_on_the_collision_disagreement():
    """Positive control: a collision census versus a single-consumer health
    reading is also a `disagree`, but it is NOT the known #2208 shape (that
    shape only ever produces `census: single`), so the hint must not appear."""
    state, detail = agreement.channel_health_agreement_state(
        "collision", ["oss-channel", "other"], "forwarding", "cached", 5.0
    )
    assert state == "disagree", detail
    assert "claude-supertool#2208" not in detail, detail


def test_disagree_known_cause_hint_is_scoped_to_single_not_none():
    """`census_state == "none"` maps to the same boolean census signal as
    `"single"` (`_census_signal` folds both to `False`), but the #913 hint
    is scoped to the literal `single` state, never the signal -- a `none`
    census cannot be the #2208 shape, because #2208's own mechanism needs a
    configured consumer server to self-collide with. A regression that
    swapped the `census_state == "single"` check for the boolean signal
    would pass every other test in this file and only be caught here."""
    state, detail = agreement.channel_health_agreement_state(
        "none", "", "cannot_determine", "cached", 12.0
    )
    assert state == "disagree", detail
    assert "claude-supertool#2208" not in detail, detail


def test_could_not_ask_census_is_could_not_compare_never_agree():
    """Load-bearing (#860's own issue): an instrument that did not answer must
    never default to `agree`."""
    state, detail = agreement.channel_health_agreement_state(
        "could-not-ask", "claude is not on PATH", "forwarding", "cached", 3.0
    )
    assert state == "could-not-compare", detail


def test_no_health_reading_at_all_is_could_not_compare():
    """The `watch` preset simply not being enabled -- no probe, no cache -- must
    read as could-not-compare, never as a silent agreement."""
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", None, None, None
    )
    assert state == "could-not-compare", detail


def test_a_stale_cached_reading_is_could_not_compare():
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", None, "cached-stale", 5000.0
    )
    assert state == "could-not-compare", detail


def test_an_unrecognised_health_state_is_could_not_compare():
    state, detail = agreement.channel_health_agreement_state(
        "single", "oss-channel", "something-new", "cached", 5.0
    )
    assert state == "could-not-compare", detail


# --------------------------------------------------------------------------
# resolve_channel_health_reading: the age-aware cache reuse, and the third
# state when neither a probe nor a fresh-enough cache is available.
# --------------------------------------------------------------------------


class _FakeStatusline:
    """A minimal stand-in for `statusline`, injected via monkeypatch rather
    than a real cache file on disk -- this module's own contract is what to
    do with a reading, not how statusline stores one."""

    CHANNEL_REFRESH_AFTER = 300

    def __init__(self, cache=None, repo="owner/name", preset_declared=True):
        self._cache = cache or {}
        self._repo = repo
        self._preset_declared = preset_declared

    def repo_config(self, root):
        return {"repo": self._repo}

    def cache_path(self, repo):
        return "unused"

    def read_cache(self, path):
        return self._cache

    def _watch_preset_declared(self, root):
        return self._preset_declared

    @staticmethod
    def _run_channel_health():  # pragma: no cover -- only allow_probe exercises this
        return "channel: FORWARDING\n"

    @staticmethod
    def parse_channel_report(text):
        if text and "FORWARDING" in text:
            return "forwarding"
        return None


def test_a_fresh_enough_cached_reading_is_reused_with_its_age(monkeypatch):
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "forwarding"}, "channel_fetched_at": 100.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=False, now=150.0
    )
    assert raw_state == "forwarding"
    assert source == "cached"
    assert age == 50.0


def test_a_cached_reading_carrying_a_session_is_not_doctors_own(monkeypatch):
    """#1437: `doctor.py` has no session identity of its own -- its
    re-derivation always calls `statusline.channel_status` with
    `current_session=None` (statusline.py's own docstring for that
    function), so the `session and current_session and session !=
    current_session` guard there never fires for doctor's path, whatever the
    cache says. A cached reading written by `_fork_refresh`'s own
    `--session-id` (statusline.py:refresh) carries a real `session` value --
    doctor cannot verify it is its OWN session's reading, so this must not
    render identically to a reading with no session attribution at all
    (`source == "cached"`), which two doctor consumers
    (`check_mcp_channel_connection`, `check_channel_delivery`) treat as
    trustworthy enough to suppress a WARN or report OK on."""
    fake = _FakeStatusline(
        cache={
            "channel": {"raw_state": "forwarding", "session": "some-other-session"},
            "channel_fetched_at": 100.0,
        }
    )
    monkeypatch.setattr(agreement, "statusline", fake)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=False, now=150.0
    )
    assert source == "cached-other-session", source
    assert raw_state == "forwarding"
    assert age == 50.0


def test_a_cached_reading_with_no_session_key_is_the_positive_control(monkeypatch):
    """Positive control for the case above: a cache written before #1362 (or
    by a manual `--refresh` with no session, per statusline.py's own
    `_fork_refresh` docstring) carries no `session` key at all -- that must
    still resolve to the ordinary, trustworthy `cached` source, unchanged."""
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "forwarding"}, "channel_fetched_at": 100.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=False, now=150.0
    )
    assert source == "cached", source
    assert raw_state == "forwarding"


def test_a_cached_reading_older_than_its_own_interval_is_cached_stale(monkeypatch):
    """The #549/#550 lesson: an old reading must never render as though it were
    fresh. `age` still travels with the state so a caller can say how old."""
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "forwarding"}, "channel_fetched_at": 0.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=False, now=1000.0
    )
    assert raw_state is None
    assert source == "cached-stale"
    assert age == 1000.0


def test_no_cache_at_all_is_the_third_state_not_a_guess(monkeypatch):
    fake = _FakeStatusline(cache={})
    monkeypatch.setattr(agreement, "statusline", fake)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=False, now=1000.0
    )
    assert (raw_state, source, age) == (None, None, None)


def test_statusline_unavailable_is_also_the_third_state(monkeypatch):
    monkeypatch.setattr(agreement, "statusline", None)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=False, now=1000.0
    )
    assert (raw_state, source, age) == (None, None, None)


def test_allow_probe_calls_the_probe_fresh_rather_than_reading_any_cache(monkeypatch):
    fake = _FakeStatusline(
        cache={
            "channel": {"raw_state": "not_delivering"},
            "channel_fetched_at": 999999.0,
        }
    )
    monkeypatch.setattr(agreement, "statusline", fake)
    raw_state, source, age = agreement.resolve_channel_health_reading(
        "/repo", allow_probe=True, probe=lambda: "channel: FORWARDING\n", now=1000.0
    )
    assert raw_state == "forwarding"
    assert source == "probed"
    assert age == 0.0


# --------------------------------------------------------------------------
# check_channel_health_agreement: the reported line, end to end.
# --------------------------------------------------------------------------


class _Completed:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def test_check_reports_ok_on_agreement(monkeypatch):
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "forwarding"}, "channel_fetched_at": 100.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message
    assert "both report" in message, message


def test_check_reports_warn_on_disagreement(monkeypatch):
    fake = _FakeStatusline(
        cache={
            "channel": {"raw_state": "cannot_determine"},
            "channel_fetched_at": 100.0,
        }
    )
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "disagree" in message, message
    assert "neither is assumed right" in message, message


def test_check_reports_warn_never_ok_on_could_not_compare(monkeypatch):
    """Never `OK` on `could-not-compare` -- named explicitly rather than
    defaulted to agreement (#860's own load-bearing state)."""
    monkeypatch.setattr(agreement, "statusline", None)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "could not compare" in message, message
    assert level != "OK"


def test_check_reports_notice_when_the_watch_preset_is_plainly_disabled(monkeypatch):
    """Self-review finding: `could-not-compare` caused by a `.supertool.json`
    that plainly does not enable `watch` is structurally permanent -- the
    same "cannot ever answer" shape #764 created NOTICE for -- and must not
    render as a WARN that pins every such repo at `usable with gaps`
    forever."""
    fake = _FakeStatusline(cache={}, preset_declared=False)
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "NOTICE", message
    assert "watch" in message, message


def test_check_reports_notice_for_a_disabled_preset_even_with_a_session_tagged_cache(
    monkeypatch,
):
    """Self-review finding (Explore reviewer, lane #1426): `#1437`'s new
    `cached-other-session` source was missing from this NOTICE arm's own
    tuple -- a repo with `watch` plainly disabled in `.supertool.json` but
    still holding an unexpired, session-tagged cached reading fell through
    to the default WARN instead of the structurally-permanent NOTICE #764
    created for exactly this "cannot ever answer until a config edit"
    shape. The preset-disabled cause is unambiguous regardless of which
    session took the reading."""
    fake = _FakeStatusline(
        cache={
            "channel": {"raw_state": "forwarding", "session": "other"},
            "channel_fetched_at": 100.0,
        },
        preset_declared=False,
    )
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "NOTICE", message
    assert "watch" in message, message


def test_check_stays_warn_when_the_preset_state_is_merely_unknown(monkeypatch):
    """The must-not-fire control for the test above: `_watch_preset_declared`
    answering anything other than its own explicit `False` (unreadable, no
    file, or genuinely enabled but nothing cached yet) must stay WARN -- only
    a confirmed `False` is the permanent case."""
    fake = _FakeStatusline(cache={}, preset_declared=None)
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message


def test_preset_disabled_helper_is_false_when_statusline_is_unavailable():
    assert agreement._preset_disabled("/repo") is False


def test_preset_disabled_helper_reads_the_explicit_false(monkeypatch):
    monkeypatch.setattr(agreement, "statusline", _FakeStatusline(preset_declared=False))
    assert agreement._preset_disabled("/repo") is True


def test_preset_disabled_helper_does_not_fold_unknown_into_disabled(monkeypatch):
    monkeypatch.setattr(agreement, "statusline", _FakeStatusline(preset_declared=None))
    assert agreement._preset_disabled("/repo") is False


# --------------------------------------------------------------------------
# #1440: a stale cache beside a census that DID answer is a clock, not a
# fault -- WAIT, not WARN. The other could-not-compare causes stay WARN.
# --------------------------------------------------------------------------


def test_stale_cache_beside_a_clean_census_waits_rather_than_warns_1440(monkeypatch):
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "forwarding"}, "channel_fetched_at": 0.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(
            0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n"
        )

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=1000.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WAIT", message
    assert "could not compare" in message
    assert "Settles on the next statusline render" in message


def test_stale_cache_beside_a_census_that_could_not_ask_still_warns_1440(monkeypatch):
    """The positive control: staleness alone is not enough for WAIT. When the
    OTHER half of the comparison could not answer either, nothing establishes
    this will clear on its own, so it must stay WARN."""
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "forwarding"}, "channel_fetched_at": 0.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(1, b"boom")

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=1000.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "could not compare" in message
