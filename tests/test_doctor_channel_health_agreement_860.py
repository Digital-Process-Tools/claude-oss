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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_channel_health_agreement as agreement  # noqa: E402


def setup_function(_):
    doctor.FINDINGS.clear()


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
        cache={"channel": {"raw_state": "not_delivering"}, "channel_fetched_at": 999999.0}
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
        return _Completed(0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n")

    agreement.check_channel_health_agreement(
        "/repo", run=run, which=lambda name: "/usr/bin/claude", env={}, now=150.0
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message
    assert "both report" in message, message


def test_check_reports_warn_on_disagreement(monkeypatch):
    fake = _FakeStatusline(
        cache={"channel": {"raw_state": "cannot_determine"}, "channel_fetched_at": 100.0}
    )
    monkeypatch.setattr(agreement, "statusline", fake)

    def run(argv, **kw):
        return _Completed(0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n")

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
        return _Completed(0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n")

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
        return _Completed(0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n")

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
        return _Completed(0, b"oss-channel:    bun /x/notifiers/claude-channel/channel.ts\n")

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
