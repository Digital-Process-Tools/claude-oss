"""#485: `scaffold.settings_plan` used `Path.exists()`, the one call CLAUDE.md
prohibits by name. `Path.exists()` swallows a short list of errnos and re-raises
everything else, and which is which moves between interpreter versions -- so on one
version the run died before the `decline` the docstring promises, and on another it
swallowed to `False` and a present, unreadable file was treated as absent, which
`apply_settings` would then have overwritten.

Two fixtures for the same defect, same shape as #363's own: an *injected* raise, which
reproduces it on every interpreter regardless of which one runs the suite, and a real
`chmod`-based one that self-skips with what went untested when the platform's own
permission model does not take (root, some filesystems, Windows' read-only attribute
not stopping a read). The must-fire case (present and unreadable -> decline) is paired
with the must-not-fire control (genuinely absent -> create) in the same fixture, so a
broken guard that declines everything cannot pass silently.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


def _raise_for(monkeypatch, method_name, target, exc):
    """Patch `Path.<method_name>` to raise only for `target`; behaves normally
    everywhere else, so the must-fire and must-not-fire cases stay distinguishable.
    """
    real = getattr(Path, method_name)

    def fake(self, *a, **kw):
        if self == target:
            raise exc
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, method_name, fake)


def test_exists_raising_must_not_crash_the_run(tmp_path, monkeypatch):
    """The must-fire half, first shape: on a version where `Path.exists()` RE-RAISES
    `PermissionError` instead of swallowing it (measured on this repo's own 3.9, 3.11
    and 3.13 -- see `doctor._safe_is_file`'s docstring), the old `if not path.exists()`
    pre-check died before the `decline` this docstring promises. There is no such
    pre-check to raise any more -- `read_text` is attempted directly and its own
    exception decides the arm."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"statusLine": {"command": "mine"}}), encoding="utf-8")
    _raise_for(monkeypatch, "exists", settings, PermissionError(13, "denied"))
    _raise_for(monkeypatch, "read_text", settings, PermissionError(13, "denied"))

    entry = scaffold.settings_plan(str(tmp_path))
    assert entry["action"] == "decline", entry
    assert "could not be read" in entry["reason"]


def test_exists_swallowing_to_false_must_not_create(tmp_path, monkeypatch):
    """The must-fire half, second shape: on a version where `Path.exists()` SWALLOWS
    the permission error and answers `False`, the old code read that as "absent" and
    returned `create` -- which `apply_settings` would then have written over a file it
    never read. `read_text`'s own exception is the one asked, not `exists()`'s."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"statusLine": {"command": "mine"}}), encoding="utf-8")
    real_exists = Path.exists

    def fake_exists(self):
        return False if self == settings else real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    _raise_for(monkeypatch, "read_text", settings, PermissionError(13, "denied"))

    entry = scaffold.settings_plan(str(tmp_path))
    assert entry["action"] == "decline", entry
    assert "could not be read" in entry["reason"]


def test_a_genuinely_absent_file_still_creates(tmp_path):
    """The must-not-fire control, in the same fixture shape: nothing patched, nothing
    written -- `FileNotFoundError` is the one exception that means `create`."""
    entry = scaffold.settings_plan(str(tmp_path))
    assert entry["action"] == "create", entry


def test_apply_settings_never_overwrites_an_unreadable_file(tmp_path, monkeypatch):
    """The consequence #485 is actually about: `apply_settings` must not call
    `write_text` over a file it could not read."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    original = json.dumps({"statusLine": {"command": "mine"}, "keepThis": True})
    settings.write_text(original, encoding="utf-8")
    _raise_for(monkeypatch, "read_text", settings, PermissionError(13, "denied"))

    entry = scaffold.apply_settings(str(tmp_path))
    assert entry["action"] == "decline"
    monkeypatch.undo()  # the assertion itself must read the real file, not the fake
    assert settings.read_text(encoding="utf-8") == original


# --------------------------------------------------------- a real permission fixture


def _deny_read(path):
    os.chmod(str(path), 0o000)


def _restore(path):
    try:
        os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def test_a_real_chmod_deny_is_measured_not_assumed(tmp_path):
    """A permission fixture is a measurement, not a given (CLAUDE.md): root ignores
    the mode bit, some filesystems ignore it, and Windows' `chmod` on a file does not
    reliably stop a read. So the deny is confirmed by attempting the exact operation
    `settings_plan` performs, and this skips with what went untested when it does not
    take, rather than asserting a platform's error code from a table.
    """
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"statusLine": {"command": "mine"}}), encoding="utf-8")
    _deny_read(settings)
    try:
        try:
            settings.read_text(encoding="utf-8")
        except OSError:
            pass  # the deny took: measured, not assumed
        else:
            pytest.skip(
                "chmod 000 did not stop a read on this platform/filesystem "
                "(root, or a filesystem that ignores the mode bit) -- untested here"
            )

        entry = scaffold.settings_plan(str(tmp_path))
        assert entry["action"] == "decline", entry
    finally:
        _restore(settings)
