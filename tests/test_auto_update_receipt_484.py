"""#484: a corrupt receipt reads as no receipt, and `doctor.check_auto_update` must
tell the two apart -- run in-process so `doctor.FINDINGS` can be inspected directly.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import plugin_update  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


def test_a_corrupt_receipt_is_not_the_ordinary_no_receipt_state(tmp_path, monkeypatch):
    """The must-fire half: a receipt that exists and is broken must WARN, distinctly
    from the OK "hook has not run yet" arm."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update, "read_receipt", lambda: plugin_update.ReceiptUnreadable("boom")
    )
    doctor.check_auto_update(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "could not be read" in message and "boom" in message


def test_no_receipt_at_all_is_still_ok_not_warn(tmp_path, monkeypatch):
    """The must-not-fire control: a receipt that was genuinely never written is still
    the ordinary pre-first-run state, not the broken-receipt WARN above."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "no receipt" in message


def test_opt_out_unknown_warns_and_is_neither_on_nor_off_492(tmp_path, monkeypatch):
    """The must-fire half for #492: an unreadable config must WARN, distinctly from both
    the OK "off" arm and the ordinary "on, no receipt yet" arm above -- and nothing must
    have been touched, since `doctor.check_auto_update` only ever reports the receipt,
    never calls `update`."""
    _reset()
    monkeypatch.setattr(
        plugin_update,
        "opt_out",
        lambda root=None, env=None: ("unknown", ".oss.json (boom)"),
    )
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "unknown" in message and "boom" in message
    assert "neither on nor off" in message


def test_current_with_no_partial_failure_is_still_ok_521(tmp_path, monkeypatch):
    """The must-not-fire control for the two tests below: a clean `current` receipt --
    no `partial_failure` at all -- must keep reading as OK."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {"state": "current", "plugin": "oss", "from": "0.12.0", "to": "0.12.0"},
    )
    doctor.check_auto_update(str(tmp_path))
    # The loop plugin's row is first and is this test's whole subject. #605 added a
    # second row about the declared dependencies -- this receipt predates it and says
    # nothing about them, which that row states rather than rounding to a pass. The
    # count moved from 1; what is asserted about row 0 did not.
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "already current" in message


def test_current_with_a_partial_failure_warns_and_names_it_521(tmp_path, monkeypatch):
    """#521's own measured instance: `state: current` with one of two scopes failed on a
    transient SSH error. The row must not print the same OK a clean run gets -- the
    failed scope has to reach the one surface a maintainer actually reads."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "current",
            "plugin": "oss",
            "from": "0.12.0",
            "to": "0.12.0",
            "partial_failure": True,
            "detail": "already at the newest published version -- but 1 of 2 scope(s) "
            "failed: local: Connection closed by 140.82.121.4 port 22 fatal: Could not "
            "read from remote repository.",
        },
    )
    doctor.check_auto_update(str(tmp_path))
    state, message = doctor.FINDINGS[0]  # the loop plugin's row -- see #605 note above
    assert state == "WARN", doctor.FINDINGS
    assert "local" in message and "Could not read from remote repository" in message


def test_updated_with_a_partial_failure_names_the_failed_scope_too_521(
    tmp_path, monkeypatch
):
    """The `updated` arm was already WARN, but it dropped `detail` entirely -- the same
    structural gap #521 found in the `current` arm, just less visible because the state
    itself already read as WARN."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "updated",
            "plugin": "oss",
            "from": "0.11.0",
            "to": "0.12.0",
            "partial_failure": True,
            "detail": "restart Claude Code before the new version runs -- this session "
            "is still on 0.11.0 -- but 1 of 2 scope(s) failed: local: boom",
        },
    )
    doctor.check_auto_update(str(tmp_path))
    state, message = doctor.FINDINGS[0]  # the loop plugin's row -- see #605 note above
    assert state == "WARN", doctor.FINDINGS
    assert "local" in message and "boom" in message


def test_could_not_check_becomes_wait_when_a_fresh_check_answers_cleanly_1440(
    tmp_path, monkeypatch
):
    """#1440's own measured instance: the cached receipt's install record could not
    be read (mid-rewrite during the launcher's own version bump), and a fresh check
    right now answers cleanly -- that is a clock, not a fault, so this must WAIT
    rather than WARN, and must name what settles it."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "could-not-check",
            "detail": "the install record could not be read",
        },
    )
    doctor.check_auto_update(
        str(tmp_path),
        fresh_check=lambda: {
            "state": "current",
            "detail": "already at the newest published version",
        },
    )
    state, message = doctor.FINDINGS[0]
    assert state == "WAIT", doctor.FINDINGS
    assert "current" in message
    assert "settles" in message.lower()


def test_could_not_check_stays_warn_when_the_fresh_check_also_fails_1440(
    tmp_path, monkeypatch
):
    """The positive control for the test above: a fresh check that ALSO cannot
    answer is a real, standing gap -- not a clock -- and must stay WARN."""
    _reset()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("on", None)
    )
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda: {
            "state": "could-not-check",
            "detail": "the install record could not be read",
        },
    )
    doctor.check_auto_update(
        str(tmp_path),
        fresh_check=lambda: {
            "state": "could-not-check",
            "detail": "still could not read the install record",
        },
    )
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "could not check" in message
