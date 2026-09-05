"""Two auditor findings against the #344 fix, both on `report_with_remedy`:

1. Only `remedy` -- the paste-ready command built from `PLUGIN_ROOT`, this
   script's own resolved location -- is within `_one_line_keep_unicode`'s
   stated exemption. `resolved`/`detail`/`version_clause`, embedded in the
   SAME formatted strings at the three call sites, come from `os.path.
   realpath()` of whatever PATH resolves `oss-workspace` to -- local
   filesystem/environment state this script did not compose -- and must
   still go through the full ASCII fold every other finding gets, so a
   PATH-resolved name carrying a bidi-override or other non-control Unicode
   formatting character cannot reorder how a WARN line reads.

2. `_emit`'s `UnicodeEncodeError` fallback trusted `sys.stdout.encoding` to
   name a codec Python's registry recognises. A stream reporting a bogus
   `.encoding` (a mock, a wrapped/proxied stdout) would raise `LookupError`
   out of `.encode(encoding, ...)`, uncaught -- the exact crash `_emit`
   exists to prevent, one exception type over.
"""

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


def test_only_the_remedy_fragment_is_exempt_from_the_ascii_fold():
    """The must-fire half: text that is NOT the remedy -- passed as a
    separate `prose` argument -- must still fold to `?` exactly like an
    ordinary `report()` call, even though the finding as a whole is emitted
    through `report_with_remedy`.
    """
    doctor.report_with_remedy(
        "WARN",
        "PATH resolves to café-cache",
        'ln -sf "/plugin/bin/oss-workspace" ~/.local/bin/oss-workspace',
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "café" not in message, message
    assert "?" in message, message


def test_the_remedy_fragment_itself_still_survives_unfolded():
    """The must-not-fire control in the same fixture shape: the remedy
    argument itself must still reach the reader verbatim -- this is the
    behaviour #344 exists to fix, and the split must not have broken it.
    """
    doctor.report_with_remedy(
        "WARN",
        "not on PATH",
        'ln -sf "/Fløriåñ-cache/bin/oss-workspace" ~/.local/bin/oss-workspace',
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "Fløriåñ-cache" in message, message


def test_emit_does_not_crash_on_an_unregistered_stdout_encoding(monkeypatch):
    """The must-fire half for finding 2: `sys.stdout.encoding` naming a
    codec Python does not recognise must not raise `LookupError` out of
    `_emit`'s own defensive fallback -- that would be the crash this
    fallback exists to prevent, one exception type over.
    """

    class _FakeStdout:
        encoding = "not-a-real-codec-xyz"

        def write(self, text):
            # A real, unregistered .encoding does not stop write() from
            # accepting a plain str -- only .encode(that name) would raise.
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _FakeStdout())

    # Would raise LookupError here if the fallback trusted the bogus
    # encoding name without a net under it.
    doctor.report_with_remedy("WARN", "prose", "remedy: /Fløriåñ/bin/oss-workspace")

    assert doctor.FINDINGS[-1][0] == "WARN"
