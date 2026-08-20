"""Review finding on #344: `_one_line_keep_unicode` preserves printable
non-ASCII on purpose, but a codepoint that decodes to a lone surrogate (which
`str()` on a `Path` built from undecodable bytes produces via
`surrogateescape`, ordinary for a non-UTF-8 filename on Linux) or a character
the ACTUAL stdout stream's codepage cannot represent (a narrow Windows
console codepage, per this repo's own CLAUDE.md cross-platform checklist) is
neither an ASCII character nor a control character, so it survives
`_one_line_keep_unicode` unfolded and reaches `print()` verbatim. If the
process's stdout uses strict encoding, that `print()` raises
`UnicodeEncodeError` -- which breaks `scripts/doctor.py`'s one contract that
matters more than any single check: `exit 0 always, one VERDICT line`,
never a crash.

`_emit` -- the function both `report()` and `report_with_remedy()` funnel
through -- now encodes defensively against the stream actually in use rather
than assuming it can represent everything `_one_line_keep_unicode` chose to
keep.
"""

import io
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


def test_emit_does_not_crash_on_a_lone_surrogate_under_strict_stdout(monkeypatch):
    """The must-fire half. A lone surrogate (what `surrogateescape` produces
    from an undecodable filename byte) reaching a strict-encoding stdout must
    not raise -- it must still print something and doctor must still exit
    cleanly, per `exit 0 always`.
    """
    strict_stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", strict_stdout)

    # Would raise UnicodeEncodeError here if the code did nothing -- this is
    # the assertion that makes the test worth having. The surrogate sits in
    # `remedy`, not `prose`: `prose` is fully ASCII-folded (a self-review
    # finding narrowed the exemption to `remedy` alone -- see
    # `tests/test_report_with_remedy_scope_review.py`), so a surrogate placed
    # in `prose` would never reach `_emit` unfolded and this test would not
    # exercise the encoding defence at all.
    doctor.report_with_remedy("WARN", "path", "/tmp/plugin-\udcff-cache/bin")

    assert doctor.FINDINGS[-1][0] == "WARN"


def test_emit_still_prints_ordinary_non_ascii_under_a_normal_stdout(capsys):
    """The must-not-fire control in the same fixture shape: the defensive
    encode path must not degrade the ordinary case #344 exists to fix --
    genuine non-ASCII text under a stdout that can represent it must still
    print unfolded.
    """
    doctor.report_with_remedy("WARN", "install path", "Fløriåñ")
    captured = capsys.readouterr()
    assert "Fløriåñ" in captured.out, captured.out
