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
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
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
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
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
        plugin_update, "opt_out", lambda root=None, env=None: ("unknown", ".oss.json (boom)")
    )
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "unknown" in message and "boom" in message
    assert "neither on nor off" in message
