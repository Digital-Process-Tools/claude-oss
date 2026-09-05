"""The receipt is the only thing that reports the mutation, and it came last.

`assemble()` writes CHANGELOG.md, deletes the consumed fragments, and only then
prints the receipt that says so. An exception anywhere in that tail left the
process at exit 1 -- which this script's own contract defines as SKIPPED,
"nothing to do, or nothing provable". So a completed release reported itself as
a release that never happened, and SKIPPED is the worst of the three values to
be wrong with: it is the one that means *carry on*.

The measured instance was one character (U+2192 on a cp1252 console) and is
closed. The shape is not. `tests/test_receipt_encoding.py` pins cp1252 and says
so explicitly: cp437 and cp850 still cannot print the em dashes that file
deliberately permits, and a closed pipe, a full disk on a redirect and a
`BrokenPipeError` from a downstream `head` are not encoding problems at all.

Two properties are checked here, because either alone leaves the hole open:

1. **The receipt cannot fail on a console that cannot represent it.** Driven
   end to end with `PYTHONIOENCODING=ascii`, which is a codepage the cp1252
   guard deliberately does not cover.
2. **If it fails anyway, the exit code does not say SKIPPED.** Driven by making
   the reporter itself raise, after a cut that genuinely succeeded, so the tree
   has moved and the only thing left to be right is the number.

Every "must not be SKIPPED" assertion below sits beside a run that must be OK
and a run that must be SKIPPED, built from the same helpers. An assertion that
a value is not 1 also passes when the code under it never ran.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

OK = 0
SKIPPED = 1
REFUSED = 2

#: No release heading: the first-release path, whose receipt carries the widest
#: prose in the file.
FIRST = """# Changelog

All notable changes to this project are documented in this file.

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


def _repo(tmp_path, name, changelog_text=FIRST, fragments=True):
    root = tmp_path / name
    (root / ".oss").mkdir(parents=True)
    (root / ".git").mkdir()
    script_path = root / ".oss" / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    (root / "changelog.d").mkdir()
    if fragments:
        (root / "changelog.d" / "41.added.md").write_text(
            "- A thing (#41).\n", encoding="utf-8"
        )
    (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    return root, script_path


def _cut(root, script_path, version, encoding):
    """A real cut -- not `--dry-run`, whose receipt takes a different branch --
    with stdout pinned to *encoding* rather than the developer's console.

    Both ends are pinned for the same reason `test_receipt_encoding.py` pins
    both: a child encoding ascii and a parent decoding UTF-8 fails in the
    harness, which is not the script failing.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--version",
            version,
            "--date",
            "2026-08-14",
            "--dir",
            "changelog.d",
            "--changelog",
            "CHANGELOG.md",
        ],
        cwd=str(root),
        capture_output=True,
        encoding=encoding,
        errors="backslashreplace",
        env=env,
    )


def _cut_landed(root, version="0.1.0"):
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    return (
        "## [{0}] - 2026-08-14".format(version) in text
        and not (root / "changelog.d" / "41.added.md").exists()
    )


# --------------------------------------------------------------------------
# 1. the receipt cannot fail on a console that cannot represent it
# --------------------------------------------------------------------------


def test_the_first_release_receipt_holds_something_ascii_cannot_encode(tmp_path):
    """The positive control for the test below, measured rather than assumed.

    `PYTHONIOENCODING=ascii` only exercises anything while the receipt actually
    carries a non-ASCII character. Asserting that against the source would
    drift; this reads it off the receipt the next test drives.
    """
    root, script_path = _repo(tmp_path, "control")
    result = _cut(root, script_path, "0.1.0", "utf-8")
    assert result.returncode == OK, result.stdout + result.stderr
    unencodable = [char for char in result.stdout if ord(char) > 127]
    assert unencodable, (
        "the first-release receipt is pure ASCII, so pinning the console to "
        "ascii below no longer exercises a degrade path -- find a codepage "
        "this receipt does break, or delete the test rather than keeping a "
        "green one that measures nothing:\n" + result.stdout
    )


def test_a_receipt_reaches_a_console_that_cannot_represent_it(tmp_path):
    """ascii is a codepage the cp1252 guard deliberately does not cover, and it
    stands in for cp437 and cp850 -- real Windows consoles that cannot print
    the em dashes that guard permits."""
    root, script_path = _repo(tmp_path, "ascii")
    result = _cut(root, script_path, "0.1.0", "ascii")
    assert "Traceback" not in result.stderr, result.stderr
    assert "UnicodeEncodeError" not in result.stderr, result.stderr
    assert result.stdout.startswith("assemble    : ok"), result.stdout + result.stderr
    assert result.returncode == OK, result.stdout + result.stderr
    assert _cut_landed(root), "the cut did not land, so the receipt proved nothing"
    # The receipt degraded rather than dropped: the escape is present, and the
    # line carrying it is still in its place. Without these two, a `_line` that
    # discarded the whole unprintable line would pass every assertion above --
    # an absence produced by the fix, read as a receipt that printed.
    escape = "{0}u2014".format(chr(92))  # what `backslashreplace` writes for U+2014
    assert escape in result.stdout, result.stdout
    assert "no `## [x.y.z]` release heading" in result.stdout, result.stdout


# --------------------------------------------------------------------------
# 2. if the receipt fails anyway, the exit code does not deny the mutation
# --------------------------------------------------------------------------


def _module(script_path, name):
    """Import the copy under test as a module.

    Registered in `sys.modules` before it executes: the script defines a
    dataclass, and `@dataclass` resolves its annotations through
    `sys.modules[cls.__module__]`. Left unregistered that lookup returns None
    and the import dies inside the stdlib -- a harness failure that reads like
    a defect in the script.
    """
    spec = importlib.util.spec_from_file_location(name, str(script_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


class _Boom(Exception):
    """Not an encoding error. The guard has to hold for the whole class -- a
    closed pipe, a full disk on a redirect -- not for one exception type."""


def test_a_reporter_that_raises_after_the_cut_does_not_exit_skipped(tmp_path):
    """The fixture that matters: an assemble that succeeds and a receipt that
    cannot be written. The failure is forced at the print, not at the write, so
    the tree really has moved by the time the exit code is chosen."""
    root, script_path = _repo(tmp_path, "raising")
    module = _module(script_path, "assemble_raising")

    real = module._receipt

    def _stub(state, summary, details=()):
        if state == "ok":
            raise _Boom("the console is gone")
        return real(state, summary, details)

    module._receipt = _stub
    code = module.assemble(
        root / "CHANGELOG.md", root / "changelog.d", "0.1.0", "2026-08-14"
    )

    assert _cut_landed(root), (
        "the cut did not land, so this asserts nothing about a mutation that "
        "was reported wrongly"
    )
    assert code != SKIPPED, (
        "the tree moved and the exit code says SKIPPED -- 'nothing to do, or "
        "nothing provable', which tells a wrapper to carry on"
    )
    assert code == REFUSED, code


class _UnwritableChangelog:
    """A changelog that reads fine and refuses to be written.

    A shim rather than `chmod`: read-only permission bits are enforced
    differently on Windows and by root, and a fixture that quietly stops
    denying the write turns this test green for the wrong reason. Only the
    members `assemble` uses are exposed, so one appearing that is not listed
    here is a loud AttributeError rather than a silent pass-through -- which is
    how this shim caught the read moving from `read_text` to `read_bytes` and
    the write from `write_text` to `open` (#93), rather than passing both
    through to the real file and denying nothing.

    Both write paths raise. `write_text` is no longer the one `assemble` calls,
    and leaving it as a pass-through would mean a revert to it made this test
    green while denying nothing at all.
    """

    def __init__(self, path):
        self._path = path
        self.name = path.name

    def read_text(self, **kwargs):
        return self._path.read_text(**kwargs)

    def read_bytes(self):
        return self._path.read_bytes()

    def open(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    def write_text(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    def __str__(self):
        return str(self._path)


def test_a_write_that_never_landed_is_not_reported_as_a_release(tmp_path):
    """The other half of the guard, and the one an earlier draft got wrong.

    The guard wraps the write as well as the receipt, so a failure at the
    write reaches the same alarm -- and the alarm must not then announce a
    release that does not exist. Refusing is still right: a torn write is
    indistinguishable from no write at this level, so "nothing happened" is
    not a claim this run can make either.
    """
    root, script_path = _repo(tmp_path, "unwritable")
    module = _module(script_path, "assemble_unwritable")
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    code = module.assemble(
        _UnwritableChangelog(root / "CHANGELOG.md"),
        root / "changelog.d",
        "0.1.0",
        "2026-08-14",
    )

    assert code == REFUSED, code
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert (root / "changelog.d" / "41.added.md").exists(), (
        "the write failed and the fragments were consumed anyway"
    )


def test_the_same_fixture_reports_ok_when_the_reporter_works(tmp_path):
    """The positive control for the one above: without the stub, this exact
    fixture is an ordinary successful cut."""
    root, script_path = _repo(tmp_path, "working")
    module = _module(script_path, "assemble_working")
    assert (
        module.assemble(
            root / "CHANGELOG.md", root / "changelog.d", "0.1.0", "2026-08-14"
        )
        == OK
    )
    assert _cut_landed(root)


def test_a_run_that_mutated_nothing_still_reports_skipped(tmp_path):
    """The other control: `!= SKIPPED` above must not be a value the script
    stopped producing. A run with nothing to consume still says SKIPPED, and
    leaves CHANGELOG.md alone."""
    root, script_path = _repo(tmp_path, "empty", fragments=False)
    module = _module(script_path, "assemble_empty")
    assert (
        module.assemble(
            root / "CHANGELOG.md", root / "changelog.d", "0.1.0", "2026-08-14"
        )
        == SKIPPED
    )
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == FIRST


# --------------------------------------------------------------------------
# 3. the first-release receipt names the source it read, and the one it did not
# --------------------------------------------------------------------------


def test_the_first_release_receipt_names_the_source_it_did_not_read(tmp_path):
    """The changelog is this script's sole source of truth, by decision. A file
    with no `## [x.y.z]` heading is evidence about the file, and a receipt
    claiming a fact about the *repository* from it has to say so: a changelog
    rewritten by hand while tags exist presents exactly the same shape."""
    root, script_path = _repo(tmp_path, "disclosure")
    result = _cut(root, script_path, "0.1.0", "utf-8")
    assert result.returncode == OK, result.stdout + result.stderr
    assert "git tag" in result.stdout, (
        "the first-release receipt infers 'never released' from the file's "
        "structure alone and does not name the second source that would "
        "contradict it:\n" + result.stdout
    )


def test_a_repo_with_a_release_heading_makes_no_such_claim(tmp_path):
    """The positive control: the disclosure belongs to the first-release path
    only. Printing it unconditionally would make the assertion above pass for a
    reason that has nothing to do with the branch it is about."""
    root, script_path = _repo(tmp_path, "anchored", changelog_text=HAS_RELEASE)
    result = _cut(root, script_path, "0.2.0", "utf-8")
    assert result.returncode == OK, result.stdout + result.stderr
    assert _cut_landed(root, "0.2.0")
    assert "git tag" not in result.stdout, result.stdout
    assert "first     " not in result.stdout, result.stdout
