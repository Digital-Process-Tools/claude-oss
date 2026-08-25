"""#548 -- `plugin_update.opt_out`'s ancestor walk read `FileNotFoundError` out of
`Path.iterdir()` as "nothing is here, keep walking up" (`:159-160`). The sibling arm
one line down (`except OSError`) already returns `"unknown"` correctly; only the
`FileNotFoundError` arm treated the exception type as the verdict.

CLAUDE.md's own #380 record: Windows folds an over-`MAX_PATH` name onto
`FileNotFoundError`, errno 2, `winerror` None -- indistinguishable from a directory
that is genuinely not there. Under that fold, a directory that DOES declare
`"auto_update": false` gets silently skipped as though it were absent, and the walk
answers `"on"` about a repository that opted out.

`scripts/doctor.py`'s `_dir_state`/`_absence_confirmed` already perform this
confirm-the-absence dance for the identical class. Per this issue's own scope, that
pair is not imported or factored into a shared module here (`doctor.py` is owned by a
concurrent lane this round) -- this is a small, local copy of the same three-state
idea, scoped to this one walk.

**Grade: reasoned, not observed.** This suite runs on darwin; CI gates 3.9-3.12
across three operating systems, and the fold is Windows-specific. The fixture below
INJECTS the fold (patches `Path.iterdir` to raise `FileNotFoundError` for a directory
that really is there) rather than waiting for a Windows runner -- the only way this
class gets a red outside one -- and the injection is measured, never assumed: it
confirms the patch actually took before asserting anything, and skips loudly, naming
the platform and interpreter, if it did not.
"""

import errno
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


def _key(value):
    try:
        text = os.fspath(value)
    except TypeError:
        return None
    if isinstance(text, bytes):
        try:
            text = text.decode(sys.getfilesystemencoding(), "strict")
        except (UnicodeDecodeError, LookupError):
            return None
    try:
        return os.path.normcase(os.path.abspath(text))
    except (OSError, ValueError):
        return None


def _fold(monkeypatch, target):
    """Emulate the Windows fold on `target` only: `Path.iterdir()` answers ordinary
    absence (`FileNotFoundError`) for a directory that really is there and whose
    parent still lists it -- the shape `opt_out`'s own walk calls directly.
    """
    wanted = _key(target)
    real_iterdir = Path.iterdir

    def fake_iterdir(self, *args, **kwargs):
        if _key(self) == wanted:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(self))
        return real_iterdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)


def _require_injection(target):
    """Confirm the fold actually took, or skip carrying what went untested -- a
    permission/platform fixture is a measurement, not a given (CLAUDE.md).
    """
    try:
        list(Path(str(target)).iterdir())
    except FileNotFoundError:
        return
    except OSError as exc:  # pragma: no cover - the patch raised something else
        pytest.skip(
            "the injected fold did not take: Path.iterdir raised {} instead of "
            "FileNotFoundError ({}). UNTESTED here: that a directory iterdir cannot "
            "reach while its parent lists it answers unknown, not on. "
            "platform={} python={}".format(
                type(exc).__name__, exc, sys.platform, sys.version.split()[0]
            )
        )
    else:
        pytest.skip(
            "the injected fold did not take: the call succeeded. UNTESTED here: "
            "that a directory iterdir cannot reach while its parent lists it answers "
            "unknown, not on. platform={} python={}".format(
                sys.platform, sys.version.split()[0]
            )
        )


@pytest.fixture
def folded(monkeypatch, tmp_path):
    """A directory that really is there -- and declares an opt-out inside it --
    which `Path.iterdir()` reports as ordinary absence.
    """
    parent = tmp_path / "root"
    parent.mkdir()
    target = parent / "548"
    target.mkdir()
    (target / ".oss.json").write_text(
        json.dumps({"repo": "x", "auto_update": False}), encoding="utf-8"
    )
    _fold(monkeypatch, target)
    _require_injection(target)
    return target


# ------------------------------------------------------------ the defect itself


def test_a_folded_candidate_directory_is_unknown_not_on(folded):
    """The positive control: `target` genuinely declares `"auto_update": false`,
    but the fold makes it unlookable. Before the fix, `FileNotFoundError` was read
    as "nothing here" and the walk continued past it, up to ancestors that declare
    nothing, landing on `"on"` -- exactly backwards for a repo that opted out.
    """
    status, detail = plugin_update.opt_out(root=str(folded))
    assert status == "unknown", (status, detail)
    assert status != "on", (
        "a directory the walk could not list was read as 'nothing declared here' "
        "and the search continued past it: status={!r} detail={!r}".format(
            status, detail
        )
    )


# --------------------------------------------- the must-fire half, same shape


def test_a_genuinely_absent_candidate_directory_still_lets_the_walk_continue(
    monkeypatch, tmp_path
):
    """The fix must not fold every `FileNotFoundError` into `unknown`. Same
    injection seam, same shape, on a name that really is not there and whose
    parent does NOT list it -- so a classifier that had simply stopped answering
    "keep walking" would pass the test above and fail here.
    """
    parent = tmp_path / "root"
    parent.mkdir()
    absent = parent / "548-not-here"
    _fold(monkeypatch, absent)
    _require_injection(absent)

    # No .oss.json anywhere in this tree, so the walk must reach the top and
    # answer "on" -- exactly as it did before this fix, for a genuinely absent
    # candidate.
    status, detail = plugin_update.opt_out(root=str(absent))
    assert status == "on", (status, detail)


def test_a_present_candidate_directory_still_declares_its_opt_out_with_no_injection(
    tmp_path,
):
    """Nothing patched: the ordinary case still works. A pair that agreed only by
    both refusing to answer would pass the tests above trivially.
    """
    repo = tmp_path / "ordinary"
    repo.mkdir()
    (repo / ".oss.json").write_text(
        json.dumps({"repo": "x", "auto_update": False}), encoding="utf-8"
    )
    status, detail = plugin_update.opt_out(root=str(repo))
    assert status == "off", (status, detail)
