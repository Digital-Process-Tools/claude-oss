"""`skip_symlink.symlink_or_skip` -- the two-mechanism fixture #265 added.

The Windows junction fallback (`mklink /J`) cannot be exercised on this
machine: there is no Windows runner here, so every claim about it in
`skip_symlink.py`'s docstring is *reasoned*, not observed. What *can* be
observed on any platform is the shape of the fallback logic itself --
`_junction` answering "not windows" for real off this machine's own
`sys.platform`, and the skip message naming both mechanisms once a directory
case's `symlink_to` is made to fail -- so that is what these tests measure.
"""

import sys
from pathlib import Path

import pytest

import skip_symlink  # noqa: E402


def test_junction_answers_not_windows_off_windows(tmp_path):
    """The one branch of `_junction` this machine can actually exercise: on
    every platform that is not win32, it must refuse without touching the
    filesystem, and say why, rather than attempting a `cmd` it has no reason
    to expect exists.
    """
    if sys.platform == "win32":
        pytest.skip("this machine is win32 -- the 'not windows' branch does not apply here")
    landed, reason = skip_symlink._junction(tmp_path / "link", tmp_path / "target")
    assert landed is False
    assert reason == "not windows"


def test_a_directory_case_names_both_mechanisms_when_both_fail(tmp_path, monkeypatch):
    """Must-fire control for the #265 fix: a directory-kind case whose
    `symlink_to` fails has to try the junction fallback and, when that also
    fails, name *both* reasons in the skip -- one mechanism's message alone
    would be the third state going quiet about the other.

    `symlink_to` is forced to fail via monkeypatch so this is exercised on
    every platform, not only ones where it happens to fail on its own.
    """
    def _refuse(self, target, target_is_directory=False):
        raise OSError(1314, "a client does not have the required privilege")

    monkeypatch.setattr(Path, "symlink_to", _refuse)
    link = tmp_path / "evil"
    target = tmp_path / "outside"
    target.mkdir()
    with pytest.raises(pytest.skip.Exception) as excinfo:
        skip_symlink.symlink_or_skip(link, target, target_is_directory=True, what="the probe")
    reason = str(excinfo.value)
    assert "symlink_to raised" in reason
    assert "junction" in reason
    assert "the probe" in reason


def test_a_file_case_names_only_the_symlink_mechanism_when_it_fails(tmp_path, monkeypatch):
    """The must-fire control's negative half: a *file*-kind case has no junction
    fallback (junctions are directory-only), so its skip must not claim one was
    tried -- that would misreport what actually went untested.
    """
    def _refuse(self, target, target_is_directory=False):
        raise OSError(1314, "a client does not have the required privilege")

    monkeypatch.setattr(Path, "symlink_to", _refuse)
    link = tmp_path / "evil.txt"
    target = tmp_path / "outside.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(pytest.skip.Exception) as excinfo:
        skip_symlink.symlink_or_skip(link, target, target_is_directory=False, what="the probe")
    reason = str(excinfo.value)
    assert "symlink_to raised" in reason
    assert "junction" not in reason
    assert "the probe" in reason


def test_the_directory_case_actually_calls_junction_when_symlink_to_fails(tmp_path, monkeypatch):
    """The message-content assertions above (`"junction" in reason`) are satisfied
    by the literal text of the skip format string whether or not `_junction` was
    ever invoked -- a maintainer reproduction confirmed this by hardcoding the
    call site's result to `(False, "disabled")` without touching `_junction` at
    all, and the message-only tests kept passing. This spies on `_junction`
    itself so a directory-kind case whose `symlink_to` fails is pinned to
    actually attempting the fallback, not merely to a message that mentions it.
    """
    def _refuse(self, target, target_is_directory=False):
        raise OSError(1314, "a client does not have the required privilege")

    monkeypatch.setattr(Path, "symlink_to", _refuse)
    calls = []

    def _spy(link, target):
        calls.append((link, target))
        return False, "spy declined"

    monkeypatch.setattr(skip_symlink, "_junction", _spy)
    link = tmp_path / "evil"
    target = tmp_path / "outside"
    target.mkdir()
    with pytest.raises(pytest.skip.Exception):
        skip_symlink.symlink_or_skip(link, target, target_is_directory=True, what="the probe")
    assert calls == [(link, target)]


def test_the_file_case_never_calls_junction_at_all(tmp_path, monkeypatch):
    """Negative half of the spy control: a file-kind case has no junction
    fallback, so `_junction` must not even be attempted for it -- attempting
    and discarding the result would still be a wasted `mklink` subprocess on
    every unelevated Windows leg, for a mechanism that can never apply.
    """
    def _refuse(self, target, target_is_directory=False):
        raise OSError(1314, "a client does not have the required privilege")

    monkeypatch.setattr(Path, "symlink_to", _refuse)
    calls = []

    def _spy(link, target):
        calls.append((link, target))
        return False, "spy declined"

    monkeypatch.setattr(skip_symlink, "_junction", _spy)
    link = tmp_path / "evil.txt"
    target = tmp_path / "outside.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(pytest.skip.Exception):
        skip_symlink.symlink_or_skip(link, target, target_is_directory=False, what="the probe")
    assert calls == []


def test_a_successful_junction_returns_the_link_without_skipping(tmp_path, monkeypatch):
    """The actual Windows post-condition #265 exists for: when the fallback
    lands, the case must assert (return the link), not skip. A spy alone could
    pass while the caller still discarded a successful junction and skipped
    anyway -- this is the pairing that catches that.
    """
    def _refuse(self, target, target_is_directory=False):
        raise OSError(1314, "a client does not have the required privilege")

    monkeypatch.setattr(Path, "symlink_to", _refuse)
    monkeypatch.setattr(skip_symlink, "_junction", lambda link, target: (True, None))
    link = tmp_path / "evil"
    target = tmp_path / "outside"
    target.mkdir()
    result = skip_symlink.symlink_or_skip(link, target, target_is_directory=True, what="the probe")
    assert result == link


def test_a_working_symlink_is_returned_and_resolves_to_target(tmp_path):
    """Positive control: on a platform that can make a plain symlink (this
    machine, observed), the ordinary path is taken and nothing is skipped.
    """
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        result = skip_symlink.symlink_or_skip(link, target, target_is_directory=True)
    except pytest.skip.Exception as exc:
        pytest.skip("this platform would not create a plain symlink either: {}".format(exc))
    assert result == link
    assert link.resolve() == target.resolve()
