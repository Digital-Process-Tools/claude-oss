"""#477 -- a tick's plugin identity is recorded, and the next tick can compare
against it.

Nothing before this recorded WHICH plugin version/content a tick ran under, so
"has the version changed since last tick" was not a question this system could
answer -- not because the comparison is hard, but because one of its two
operands was never written down. This is the library half: recording an
identity on an entry and comparing this tick's reading against the prior one,
in three states rather than two, mirroring `cohort_freeze`'s and `wait`'s own
three-state shape.

The comparison is over the WHOLE identity string `doctor.plugin_identity()`
already returns -- version plus content digest -- not the version alone,
because #418 measured two installs both reading "0.9.0" 16 commits apart. A
version-only comparison would be silent for exactly the skew this issue is
about.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


IDENTITY_A = "0.13.0, git HEAD 990d0da, content c079d2a9a6dd over 46 file(s)"
IDENTITY_B = "0.13.0, git HEAD 82b8143, content deadbeefcafe over 46 file(s)"


def test_plugin_identity_check_needs_a_current_reading():
    """A falsy `current` is refused rather than silently compared -- the caller
    always has one (`doctor.plugin_identity()` never raises), so an empty
    value here is a programming error, not a real reading."""
    with pytest.raises(oss_state.StateError):
        oss_state.plugin_identity_check("", IDENTITY_A)
    with pytest.raises(oss_state.StateError):
        oss_state.plugin_identity_check(None, IDENTITY_A)


def test_plugin_identity_check_could_not_tell_with_no_prior():
    """A first tick after this ships -- or any tick whose predecessor never
    recorded one -- is legitimately in this state and must say so once,
    rather than rendering as a clean 'unchanged' comparison it never
    performed (the issue's own 'must not render as unchanged')."""
    record = oss_state.plugin_identity_check(IDENTITY_A, None)
    assert record["state"] == oss_state.PLUGIN_COULD_NOT_TELL
    assert record["why"]
    assert record["current"] == IDENTITY_A
    assert record["prior"] is None


def test_plugin_identity_check_could_not_tell_on_a_blank_prior():
    """A prior that is present but empty/whitespace is the same 'nothing to
    compare against' state as no prior at all -- not a spurious 'changed'
    against an empty string."""
    record = oss_state.plugin_identity_check(IDENTITY_A, "   ")
    assert record["state"] == oss_state.PLUGIN_COULD_NOT_TELL


def test_plugin_identity_check_unchanged_on_an_identical_reading():
    """MUST FIRE: the positive control for 'must not fire' below -- two
    identical identity strings really do compare as unchanged."""
    record = oss_state.plugin_identity_check(IDENTITY_A, IDENTITY_A)
    assert record["state"] == oss_state.PLUGIN_UNCHANGED
    assert record["why"] is None


def test_plugin_identity_check_changed_when_the_content_hash_moves_and_the_version_does_not():
    """This is the case the issue names as the naive comparison's blind spot:
    a manifest version that does not move between releases is exactly the
    situation that makes a version-only check silent. IDENTITY_A and
    IDENTITY_B share the same '0.13.0' version and differ only in git HEAD
    and content digest -- a version-only comparison would call this
    unchanged; the whole-string comparison must not."""
    record = oss_state.plugin_identity_check(IDENTITY_B, IDENTITY_A)
    assert record["state"] == oss_state.PLUGIN_CHANGED
    assert record["current"] == IDENTITY_B
    assert record["prior"] == IDENTITY_A


def test_plugin_identity_check_changed_must_not_fire_on_a_pure_repeat():
    """MUST NOT FIRE: the paired negative control -- ticking the same
    identity through twice in a row must never announce a change."""
    record = oss_state.plugin_identity_check(IDENTITY_A, IDENTITY_A)
    assert record["state"] != oss_state.PLUGIN_CHANGED


def test_plugin_identity_line_renders_all_three_states():
    unchanged = oss_state.plugin_identity_line(
        oss_state.plugin_identity_check(IDENTITY_A, IDENTITY_A)
    )
    changed = oss_state.plugin_identity_line(
        oss_state.plugin_identity_check(IDENTITY_B, IDENTITY_A)
    )
    could_not_tell = oss_state.plugin_identity_line(
        oss_state.plugin_identity_check(IDENTITY_A, None)
    )
    assert "unchanged" in unchanged
    assert "changed" in changed and IDENTITY_A in changed and IDENTITY_B in changed
    assert "could not tell" in could_not_tell


def test_last_plugin_identity_scans_back_past_other_entry_kinds(tmp_path):
    state_path = tmp_path / "state.json"
    oss_state.append(
        str(state_path), "2026-01-01T00:00:00Z", "first tick",
        detail={"plugin_identity": IDENTITY_A},
    )
    oss_state.append(
        str(state_path), "2026-01-02T00:00:00Z", "second tick, no identity recorded",
    )
    oss_state.append(
        str(state_path), "2026-01-03T00:00:00Z", "third tick, an intake record",
        detail={"intake": oss_state.intake(1, 1, window="test")},
    )
    entry, identity = oss_state._last_plugin_identity(str(state_path))
    assert identity == IDENTITY_A
    assert entry["decision"] == "first tick"


def test_last_plugin_identity_with_no_history_at_all(tmp_path):
    state_path = tmp_path / "state.json"
    entry, identity = oss_state._last_plugin_identity(str(state_path))
    assert entry is None
    assert identity is None


STAMP = "2026-08-25T00:00:00Z"


def test_cli_decision_records_a_plugin_identity(tmp_path, capsys):
    path = tmp_path / "state.json"
    rc = oss_state._main(
        [str(path), "--decision", "first tick", "--at", STAMP,
         "--plugin-identity", IDENTITY_A]
    )
    assert rc == 0
    out = capsys.readouterr()
    entry = json.loads(out.out)
    assert entry["detail"]["plugin_identity"] == IDENTITY_A
    assert "RECORDED plugin identity" in out.err


def test_cli_check_plugin_identity_with_no_prior_says_could_not_tell(tmp_path, capsys):
    path = tmp_path / "state.json"
    rc = oss_state._main([str(path), "--check-plugin-identity", IDENTITY_A])
    assert rc == 0
    out = capsys.readouterr()
    record = json.loads(out.out)
    assert record["state"] == oss_state.PLUGIN_COULD_NOT_TELL
    assert "could not tell" in out.err


def test_cli_check_plugin_identity_finds_the_prior_across_a_tick(tmp_path, capsys):
    path = tmp_path / "state.json"
    oss_state._main(
        [str(path), "--decision", "first tick", "--at", STAMP,
         "--plugin-identity", IDENTITY_A]
    )
    capsys.readouterr()
    rc = oss_state._main([str(path), "--check-plugin-identity", IDENTITY_B])
    assert rc == 0
    out = capsys.readouterr()
    record = json.loads(out.out)
    assert record["state"] == oss_state.PLUGIN_CHANGED
    assert record["prior"] == IDENTITY_A
    assert record["current"] == IDENTITY_B


def test_cli_check_plugin_identity_must_not_fire_when_the_reading_repeats(tmp_path, capsys):
    """MUST NOT FIRE: the paired negative control for the CLI path -- a real
    round trip through --decision then --check-plugin-identity with an
    unchanged reading must not report `changed`."""
    path = tmp_path / "state.json"
    oss_state._main(
        [str(path), "--decision", "first tick", "--at", STAMP,
         "--plugin-identity", IDENTITY_A]
    )
    capsys.readouterr()
    oss_state._main([str(path), "--check-plugin-identity", IDENTITY_A])
    record = json.loads(capsys.readouterr().out)
    assert record["state"] == oss_state.PLUGIN_UNCHANGED


def test_cli_plugin_identity_in_a_reading_mode_is_refused_not_silently_dropped(tmp_path, capsys):
    path = tmp_path / "state.json"
    rc = oss_state._main([str(path), "--last", "--plugin-identity", IDENTITY_A])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_check_plugin_identity_with_an_empty_value_is_refused_not_dropped(tmp_path, capsys):
    """MUST NOT FIRE as --decision: an empty string is still a value somebody
    passed (a broken $IDENTITY capture upstream, say), and it used to be
    treated as absent -- falling all the way through to --decision's own
    "--at is required" refusal, which names the wrong flag entirely (found
    by review)."""
    path = tmp_path / "state.json"
    rc = oss_state._main([str(path), "--check-plugin-identity", ""])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "--at is required" not in out
