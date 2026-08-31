"""`agent_role._git_dir` must not raise on an undecodable subprocess byte -- #707.

`_git_dir` ran `subprocess.run(..., text=True)` with no explicit `encoding=`,
which decodes under `errors="strict"` using this platform's own preferred
text codec (`locale.getpreferredencoding(False)`) -- not necessarily UTF-8.
A `UnicodeDecodeError` there is a `ValueError`, a subclass of neither
`OSError` nor `subprocess.SubprocessError`, so it escaped the one `except`
clause guarding the call and reached `release_refusal()` -- called three
times on the ordinary no-role-declared publish path, before any of
`release_publish.main()`'s six documented states are even reached.

The trigger the issue reasons through: `git rev-parse --git-dir` returns an
absolute path, and a maintainer whose home directory or worktree root
contains an ordinary accented character (`Á`, `Í`, a Central-European
letter) produces UTF-8 bytes that a legacy codepage such as cp1252 cannot
decode. That is reasoned, not observed -- the issue itself was measured on
macOS/Darwin only. So the fixture here does not assume cp1252 specifically;
it measures THIS platform's own default text-decoding codec and skips
loudly, carrying the codec and what went untested, if that codec happens
not to reject any of the candidate bytes. Asserting on a platform's error
behaviour from a table is exactly the thing this repository's own working
rules (CLAUDE.md, the permission- and injection-fixture entries) already
forbid; this establishes the condition rather than assuming it.

Fixed by dropping `text=True` entirely: `_git_dir` now asks for raw bytes
and decodes them itself with `encoding="utf-8", errors="replace"`, the same
convention `doctor.dependency_diagnostic_state` already uses three files
over in this same delta -- which removes the class rather than adding
`UnicodeDecodeError` to the caught set to catch one more instance of it.
"""

import locale
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agent_role  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = b"" if isinstance(stdout, bytes) else ""


def _byte_the_default_text_codec_rejects():
    """One of cp1252's five undefined byte values -- the issue's own
    measurement -- that THIS platform's preferred text codec
    (`locale.getpreferredencoding(False)`, what `subprocess.run(text=True)`
    actually decodes under with no explicit `encoding=`) also rejects.

    Returns ``(None, codec)`` when none of the candidates are rejected
    here, so the caller can skip naming the codec and what went untested
    rather than asserting a platform behaviour nothing established.
    """
    codec = locale.getpreferredencoding(False)
    for value in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
        candidate = bytes([value])
        try:
            candidate.decode(codec)
        except UnicodeDecodeError:
            return candidate, codec
    return None, codec


def test_git_dir_survives_a_byte_the_default_text_codec_cannot_decode(monkeypatch, tmp_path):
    rejected, codec = _byte_the_default_text_codec_rejects()
    if rejected is None:
        pytest.skip(
            "this platform's default text-decoding codec ({0}) did not "
            "reject any of cp1252's undefined bytes (0x81/0x8d/0x8f/0x90/"
            "0x9d) -- the UnicodeDecodeError #707 reports was not "
            "reproduced here, so this leaves that class unexercised on "
            "this platform".format(codec)
        )

    def fake_run(cmd, **kwargs):
        if kwargs.get("text") or kwargs.get("universal_newlines"):
            # subprocess.run itself decodes right here, under
            # errors="strict" by default -- this is not a stand-in for
            # that behaviour, it is the same call with the same codec.
            encoding = kwargs.get("encoding") or codec
            rejected.decode(encoding)
            raise AssertionError("unreachable: the decode above must raise first")
        return _FakeCompleted(0, rejected + b"\n")

    monkeypatch.setattr(agent_role.subprocess, "run", fake_run)

    # Must not raise. Pre-fix, this propagates UnicodeDecodeError straight
    # out of `_git_dir`, past the `except (OSError,
    # subprocess.SubprocessError)` clause -- the bug #707 reports.
    result = agent_role._git_dir(str(tmp_path))
    assert result is None or isinstance(result, Path)


def test_undecodable_bytes_are_could_not_determine_not_a_garbled_path(monkeypatch, tmp_path):
    """Auditor finding on #707's own fix: decoding with `errors="replace"`
    alone does not merely avoid the crash, it silently substitutes U+FFFD
    for bytes that are not valid UTF-8 AT ALL -- not just bytes a legacy
    codepage misreads -- fabricating a `Path` that almost certainly does
    not exist on disk. That `Path` then flows into `_marker_path` and
    `write_role_marker`/`_read_marker`, which would read or WRITE a role
    marker at a location nobody actually computed from `git`'s real
    answer -- silently rendering a live marker as `absent`, or writing
    outside the real git directory entirely. Both are this same module's
    own documented trap ("reporting a confident absence about a file
    nothing was able to look at"), reintroduced by the very fix that
    closes #707's crash.

    `0xff 0xfe` are not valid UTF-8 anywhere, on any platform or locale --
    unlike cp1252's undefined bytes above, this needs no platform
    measurement or skip branch to reproduce.

    `_git_dir` must report "could not determine" (`None`) for genuinely
    undecodable bytes, the same way it already does for `git` missing
    from PATH or `root` not being a repository at all -- not fabricate a
    plausible-looking path standing in for an answer nobody computed."""
    undecodable = b"\xff\xfe not valid utf-8 at all"

    def fake_run(cmd, **kwargs):
        return _FakeCompleted(0, undecodable + b"\n")

    monkeypatch.setattr(agent_role.subprocess, "run", fake_run)
    result = agent_role._git_dir(str(tmp_path))
    assert result is None


def test_positive_control_an_ordinary_git_dir_still_resolves(tmp_path):
    """Must-fire control for the test above: an ordinary, real repository
    still resolves its git directory through the unmocked code path,
    proving the fix does not turn every call into a silent `None`."""
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    result = agent_role._git_dir(str(tmp_path))
    assert result is not None
    assert isinstance(result, Path)
