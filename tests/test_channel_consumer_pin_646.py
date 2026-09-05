"""#646: `check_mcp_channel_registration`'s `registered` line confirms the
consumer path EXISTS and never compares the VERSION it is pinned to against
the version `active_versions` says supertool actually is -- so a stale pin
(an older copy the plugin cache has not dropped yet) renders `OK` twice over.
This adds the comparison, in three states -- `current` / `SKEW` /
`could-not-tell` -- and `SKEW` names whether the two files are byte-identical
rather than assuming it.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _install_record(tmp_path, version):
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps(
            {
                "plugins": {
                    "supertool@dpt-plugins": [
                        {
                            "version": version,
                            "installPath": str(tmp_path / "active" / version),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return record


def _plugin_tree(root, version, consumer_body="// consumer\n"):
    """A minimal installed-plugin shape: `<root>/.claude-plugin/plugin.json`
    naming VERSION, plus a `notifiers/claude-channel/channel.ts` consumer."""
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    consumer = root / "notifiers" / "claude-channel" / "channel.ts"
    consumer.parent.mkdir(parents=True, exist_ok=True)
    consumer.write_text(consumer_body, encoding="utf-8")
    return consumer


# --- could-not-tell: no manifest found, or nothing to compare against -------


def test_could_not_tell_when_no_manifest_is_found_walking_up(tmp_path):
    target = tmp_path / "some" / "random" / "path" / "channel.ts"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")
    state, detail = doctor.channel_consumer_pin_state(target)
    assert state == "could-not-tell", (state, detail)


def test_could_not_tell_when_no_active_version_can_be_read(tmp_path):
    pinned_root = tmp_path / "cache" / "supertool" / "0.51.0"
    consumer = _plugin_tree(pinned_root, "0.51.0")
    empty_record = tmp_path / "installed_plugins.json"
    empty_record.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    state, detail = doctor.channel_consumer_pin_state(consumer, record=empty_record)
    assert state == "could-not-tell", (state, detail)


def test_could_not_tell_never_folds_into_current(tmp_path):
    """Must-not-fire control across both could-not-tell arms, exercised
    against the real function rather than a self-review-flagged tautology:
    a pinned version that cannot be compared -- here, an unparseable pinned
    version string -- must never be spelled `current`. An unparseable or
    absent pair is not evidence of a match, and this is #646's own point
    about the third state."""
    pinned_root = tmp_path / "cache" / "supertool" / "not-a-version"
    consumer = _plugin_tree(pinned_root, "not-a-version")
    record = _install_record(tmp_path, "0.52.0")
    state, detail = doctor.channel_consumer_pin_state(consumer, record=record)
    assert state == "could-not-tell", (state, detail)
    assert state != "current"


# --- current: versions match ------------------------------------------------


def test_current_when_the_pinned_version_matches_the_active_install(tmp_path):
    pinned_root = tmp_path / "cache" / "supertool" / "0.52.0"
    consumer = _plugin_tree(pinned_root, "0.52.0")
    record = _install_record(tmp_path, "0.52.0")
    state, detail = doctor.channel_consumer_pin_state(consumer, record=record)
    assert state == "current", (state, detail)
    assert "0.52.0" in detail


# --- SKEW: versions differ, byte-identity computed not assumed --------------


def test_skew_when_versions_differ_and_reports_byte_identical(tmp_path):
    body = "// consumer, byte for byte\n"
    pinned_root = tmp_path / "cache" / "supertool" / "0.51.0"
    consumer = _plugin_tree(pinned_root, "0.51.0", consumer_body=body)
    active_root = tmp_path / "active" / "0.52.0"
    _plugin_tree(active_root, "0.52.0", consumer_body=body)
    record = _install_record(tmp_path, "0.52.0")
    state, detail = doctor.channel_consumer_pin_state(
        consumer, record=record, cache_root=tmp_path / "cache"
    )
    assert state == "SKEW", (state, detail)
    assert "0.51.0" in detail and "0.52.0" in detail
    assert "byte-identical" in detail
    assert "NOT byte-identical" not in detail


def test_skew_when_versions_differ_and_the_files_are_not_byte_identical(tmp_path):
    """Must-fire control for the test above, same fixture shape, different
    consumer bytes on the active side: the identity clause must flip, not
    stay silent about the difference."""
    pinned_root = tmp_path / "cache" / "supertool" / "0.51.0"
    consumer = _plugin_tree(pinned_root, "0.51.0", consumer_body="// old\n")
    active_root = tmp_path / "active" / "0.52.0"
    _plugin_tree(active_root, "0.52.0", consumer_body="// changed\n")
    record = _install_record(tmp_path, "0.52.0")
    state, detail = doctor.channel_consumer_pin_state(
        consumer, record=record, cache_root=tmp_path / "cache"
    )
    assert state == "SKEW", (state, detail)
    assert "NOT byte-identical" in detail


def test_skew_when_the_active_copy_cannot_be_located_at_all(tmp_path):
    pinned_root = tmp_path / "cache" / "supertool" / "0.51.0"
    consumer = _plugin_tree(pinned_root, "0.51.0")
    empty_record = tmp_path / "installed_plugins.json"
    empty_record.write_text(
        json.dumps({"plugins": {"supertool@dpt-plugins": [{"version": "0.52.0"}]}}),
        encoding="utf-8",
    )
    state, detail = doctor.channel_consumer_pin_state(
        consumer, record=empty_record, cache_root=tmp_path / "nonexistent-cache"
    )
    assert state == "SKEW", (state, detail)
    assert "could not be established" in detail


# --- the check-level wiring: OK for current, WARN for SKEW and could-not-tell,
# and it is silent (no line at all) unless the registration itself resolved.


def test_check_is_silent_when_the_registration_is_not_registered():
    doctor.check_channel_consumer_pin(precomputed=("not-registered", ""))
    assert doctor.FINDINGS == []


def test_check_reports_ok_on_current(tmp_path):
    pinned_root = tmp_path / "cache" / "supertool" / "0.52.0"
    consumer = _plugin_tree(pinned_root, "0.52.0")
    record = _install_record(tmp_path, "0.52.0")
    doctor.check_channel_consumer_pin(
        precomputed=("registered", str(consumer)), record=record
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", (level, message)


def test_check_reports_warn_never_ok_on_skew(tmp_path):
    """Must-fire control for the test above: SKEW must render as a finding, not
    silently fold into `OK` -- the whole subject of #646."""
    pinned_root = tmp_path / "cache" / "supertool" / "0.51.0"
    consumer = _plugin_tree(pinned_root, "0.51.0")
    record = _install_record(tmp_path, "0.52.0")
    doctor.check_channel_consumer_pin(
        precomputed=("registered", str(consumer)),
        record=record,
        cache_root=tmp_path / "cache",
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "SKEW" in message


def test_check_reports_warn_never_ok_on_could_not_tell(tmp_path):
    target = tmp_path / "some" / "random" / "channel.ts"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")
    doctor.check_channel_consumer_pin(precomputed=("registered", str(target)))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)


def test_check_asks_for_itself_when_nothing_precomputed_is_given(tmp_path):
    """Standalone callers (every other test in this file) get the same
    real-or-injected read `mcp_channel_registration_state` always did."""
    doctor.check_channel_consumer_pin(
        which=lambda name: (
            None
        ),  # claude not on PATH -> could-not-ask -> not registered path -> silent
    )
    assert doctor.FINDINGS == []
