"""The receipt has to reach a Windows console, which is not UTF-8.

`assemble()` wrote CHANGELOG.md, deleted the consumed fragments, and then died
printing its own `ok` receipt: the summary carried U+2192 and Python encodes
stdout with the locale codepage, which is cp1252 on the GitHub Windows runners.
The traceback left the process at exit 1 -- which this script's own contract
defines as SKIPPED, "nothing to do, or nothing provable". So the release was
cut, the fragments were gone, and the exit code said neither had happened. It
is this tracker's defect class one layer down: an absence produced by the tool
(an unprintable character) read as an absence in the world (nothing released).

Every leg but Windows was green for as long as the character was there, because
a UTF-8 console prints it fine. That is what makes this a *measurement* rather
than a claim: the tests below fail on Linux and macOS too, by pinning the
codepage instead of inheriting the developer's.

**What this establishes, and its limit.** cp1252 is the codepage CI measures.
It is not the only one Windows uses -- a cp437 or cp850 console has no em dash
either, and the script carries 76 of them that have shipped green through every
Windows leg. Widening the bar to ASCII is a repo-wide prose change and a
separate decision; this checks the encoding that is known to break the build.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

#: The codepage the failing CI leg encodes stdout with.
CONSOLE = "cp1252"

FIRST = """# Changelog

## [Unreleased]

[Unreleased]: https://github.com/o/r/commits/HEAD
"""

HAS_RELEASE = """# Changelog

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""


def _unencodable(text):
    """[(line number, character)] this codepage cannot represent."""
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        for char in line:
            if ord(char) < 128:
                continue
            try:
                char.encode(CONSOLE)
            except UnicodeEncodeError:
                out.append((number, char))
    return out


def test_the_scan_sees_a_character_that_is_there():
    """The positive control, and the reason it is first in the file.

    `_unencodable` returning `[]` is what the test below rests on, and an empty
    list is also what a scan that looked at nothing returns. Handed the exact
    character that broke the build, it has to say so.
    """
    assert _unencodable("ok\nreleased → tagged\n") == [(2, "→")]
    assert _unencodable("ok\nreleased -> tagged\n") == []


def test_the_script_holds_no_character_the_console_cannot_print():
    """The net for the paths no test drives. A summary string is only reached
    on the branch that builds it, so a character sitting on an untested branch
    is invisible until a maintainer hits it mid-release."""
    found = _unencodable(SCRIPT.read_text(encoding="utf-8"))
    assert not found, "{0} cannot encode: {1}".format(CONSOLE, ", ".join(
        "line {0}: U+{1:04X}".format(number, ord(char)) for number, char in found))


def _repo(tmp_path, changelog_text, name):
    root = tmp_path / name
    (root / ".oss").mkdir(parents=True)
    (root / ".git").mkdir()
    script_path = root / ".oss" / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    (root / "changelog.d").mkdir()
    (root / "changelog.d" / "41.added.md").write_text(
        "- A thing (#41).\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    return root, script_path


def _assemble_on_a_console(root, script_path, version):
    """A real cut -- not `--dry-run`, whose receipt takes a different branch --
    with stdout pinned to the console codepage rather than the developer's.

    `encoding=CONSOLE` and not `text=True`, on both ends for the same reason.
    The child encodes with cp1252 because that is the point of the test; a
    parent left on `text=True` then decodes those bytes as UTF-8 and dies on
    the em dash at 0x97 -- which is not the script failing, it is the harness
    reading the script's output in the wrong codepage. On the Windows runner
    both processes are cp1252 already and agree by default; pinning both is
    what reproduces that agreement everywhere else.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = CONSOLE
    return subprocess.run(
        [sys.executable, str(script_path), "--version", version,
         "--date", "2026-08-14", "--dir", "changelog.d",
         "--changelog", "CHANGELOG.md"],
        cwd=str(root), capture_output=True, encoding=CONSOLE, env=env,
    )


def test_a_first_release_receipt_prints_on_a_cp1252_console(tmp_path):
    root, script_path = _repo(tmp_path, FIRST, "first")
    result = _assemble_on_a_console(root, script_path, "0.1.0")
    assert "UnicodeEncodeError" not in result.stderr, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert result.stdout.startswith("assemble    : ok"), result.stdout + result.stderr
    assert result.returncode == 0


def test_an_ordinary_release_receipt_prints_on_a_cp1252_console(tmp_path):
    """The control, and the one that caught this: the arrow that broke the
    build was on the shared success path and in `_rewrite_links`, neither of
    which is new. A test only of the first-release branch would have missed
    both."""
    root, script_path = _repo(tmp_path, HAS_RELEASE, "anchored")
    result = _assemble_on_a_console(root, script_path, "0.2.0")
    assert "UnicodeEncodeError" not in result.stderr, result.stderr
    assert result.stdout.startswith("assemble    : ok"), result.stdout + result.stderr
    assert result.returncode == 0
    # The write half of the failure: the release landed and the fragment was
    # consumed while the exit code said SKIPPED. Assert both halves agree.
    assert "## [0.2.0] - 2026-08-14" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not (root / "changelog.d" / "41.added.md").exists()
