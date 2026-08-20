"""#344: `check_oss_workspace_launcher`'s remedy is the first RUNNABLE command
`scripts/doctor.py` prints, and it went through `report()`'s ASCII sanitiser --
`_one_line`, which folds every non-ASCII character to `?`. `?` is a shell glob
matching any single character, so a non-ASCII install path (ordinary on a
localised macOS or Windows account) turned a paste-ready `ln -sf "..."` /
`sh "..."` command into one that either fails against a path that does not
exist or links a file the caller never named.

## The decision this issue asked for

`report()`'s sanitiser is correct and stays exactly as it is for every OTHER
caller: the strings that normally reach it are chosen by the audited tree --
settings entries, config values, subprocess stderr -- genuinely foreign text
that a sanitiser must fold to stop it forging this script's own output. The
remedy is different in kind: it is composed by THIS script, from THIS
install's own resolved location (`PLUGIN_ROOT` / `plugin_root`), which is not
"text from outside this script" in the sense `_one_line`'s own docstring
means. So the fix is narrow rather than wide -- a sibling sanitiser,
`_one_line_keep_unicode`, used only where a remedy is embedded, that keeps
the newline/control-character defence (the actual injection vector) and
drops only the ASCII-fold, which was defending against a threat this text
does not carry. `report()` and every one of its many other callers are
untouched.
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


def _plugin_root(tmp_path, name="Fløriåñ-cache"):
    root = tmp_path / name / "oss" / "9.9.9"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "oss-workspace").write_bytes(b"# running install\n")
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    manifest_dir.joinpath("plugin.json").write_text(
        '{"name": "oss", "version": "9.9.9"}', encoding="utf-8"
    )
    return root


def test_a_non_ascii_install_path_survives_into_the_remedy_verbatim(tmp_path):
    """The must-fire half. A non-ASCII plugin_root reaches the printed remedy
    with its real characters intact -- not `?`, which is a shell glob and
    would either fail to match or match a directory the caller never named.
    """
    plugin_root = _plugin_root(tmp_path)
    empty = tmp_path / "empty-path"
    empty.mkdir()

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(empty))

    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "Fløriåñ-cache" in message, message
    assert "?" not in message, message


def test_the_sanitiser_still_folds_foreign_text_in_an_ordinary_finding():
    """The must-not-fire control in the same fixture shape: `report()` -- the
    route every OTHER finding in this script still goes through -- must
    still fold non-ASCII/control characters from text that really is foreign.
    Without this, the fix above could have been a blanket relaxation of
    `report()` itself rather than a narrow one at the remedy's own call
    sites.
    """
    doctor.report("WARN", "settings entry: café \x07 bell")
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "café" not in message, message
    assert "?" in message, message


def test_one_line_keep_unicode_preserves_printable_non_ascii():
    assert doctor._one_line_keep_unicode("Fløriåñ") == "Fløriåñ"


def test_one_line_keep_unicode_still_strips_control_characters():
    """The actual injection vector -- a newline forging a line of this
    script's own output, or a control character rewriting what a terminal
    has already printed -- must still be neutralised even though the
    ASCII-fold is gone."""
    result = doctor._one_line_keep_unicode("line one\nline two\x07bell")
    assert "\n" not in result, result
    assert "\x07" not in result, result
    assert "line one" in result and "line two" in result, result


def test_the_remedy_survives_report_limit_intact(tmp_path):
    """Not claimed as new by #344 -- the audit that filed it already measured
    this -- but pinned here so the new call site cannot regress it silently.
    """
    plugin_root = _plugin_root(tmp_path, name="x" * 50)
    remedy = doctor._launcher_remedy(plugin_root, windows=False)
    assert len(remedy) < doctor.REPORT_LIMIT
