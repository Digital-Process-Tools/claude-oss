"""#380: both classifiers read *absence* off an exception type, and Windows folds
the unlookable case onto the same type.

`worktree_occupancy` and `doctor._dir_state` catch `FileNotFoundError` /
`NotADirectoryError` and answer "nothing is there". That split is right on POSIX,
where an over-long name arrives as a plain `OSError` (ENAMETOOLONG) and already
reaches the third state through the general arm. On Windows without
`LongPathsEnabled` a path past `MAX_PATH` arrives as `FileNotFoundError`, errno 2,
`winerror` None -- byte-identical to a file that is merely not there (CLAUDE.md,
measured on this repo's own CI). So the receipt prints `[free]` for a worktree
nothing ever looked at: the confident absence #373 exists to close, reaching it
through the one exception type that fix treats as safe.

**Why the prescribed control is not the control used, and this is the argued part.**
The issue asks for "a plainly-missing path of the same shape, compared against the
subject". On the folding platform that comparison provably carries no signal: a
same-shape plainly-missing path is *also* past `MAX_PATH`, so it answers exactly
what the subject answered, and the guard reads identical-therefore-absent for both
the genuine miss and the unlookable one. It would be a guard nominally on and
effectively never firing -- this repo's own defect class, one layer up. What does
carry a signal is a control the subject cannot fake: the deepest ancestor of the
subject that this platform *can* look at, and that ancestor's own directory
listing. Same shape by construction rather than by approximation -- it is the
subject's own path prefix -- and enumeration answers regardless of how long the
resulting full path is, which is exactly the property `stat` loses.

**Red-first, and how.** The defect is unreachable on the machine this was written on,
so the fold is *injected* rather than waited for: `stat` on a directory that really
is there raises the same `FileNotFoundError` an absent path raises, while the parent
still lists it. That reproduces the Windows event on every interpreter and every
platform, which is the only way this class gets a red at all outside a Windows
runner. The injection is measured, never assumed: every case attempts the exact
operation the code under test performs and skips carrying the platform, the
interpreter and what went untested when the patch did not take.

**GRADE.** That both classifiers answer the third state for a name `stat` cannot
reach while its parent lists it is *observed* here on whatever platform ran this.
That Windows *emits* that event for a path past `MAX_PATH` is *reasoned*, from
CLAUDE.md's own recorded CI measurement rather than from a run here.

Every "must not fire" below is paired with a "must fire" in the same fixture: a
genuinely absent path must still answer absence under the identical injection, or
the fix would be the opposite bug -- everything folded into `unknown`.
"""

import errno
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402

doctor = pytest.importorskip("doctor")

NUL = chr(0)


def _key(value):
    """A comparable spelling of a path, or None for anything that is not one.

    `os.stat` is also called with an integer file descriptor and with bytes; the
    injection below must pass those straight through rather than crash inside the
    comparison it uses to decide.
    """
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
    """Emulate the Windows fold on `target` only: `stat` answers ordinary absence
    for a name that is really there, and everything else behaves normally.

    Both seams are patched because the two functions under test do not share one.
    `lane_setup.worktree_occupancy` calls `os.stat` by name; `doctor._dir_state`
    calls `path.stat()`, and on 3.9/3.10 `Path.stat` routes through an accessor
    that captured `os.stat` at import, so patching `os.stat` alone would silently
    not take there -- the interpreter axis CLAUDE.md records from #174, which was
    green on 3.9, 3.11 and 3.12 and red on all three operating systems at 3.10.
    """
    wanted = _key(target)
    real_os_stat = os.stat
    real_path_stat = Path.stat

    def fake_os_stat(value, *args, **kwargs):
        if _key(value) == wanted:
            raise FileNotFoundError(
                errno.ENOENT, "No such file or directory", str(value)
            )
        return real_os_stat(value, *args, **kwargs)

    def fake_path_stat(self, *args, **kwargs):
        if _key(self) == wanted:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(self))
        return real_path_stat(self, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fake_os_stat)
    monkeypatch.setattr(Path, "stat", fake_path_stat)


def _require_injection(target):
    """Confirm the fold actually took, on both seams, or skip carrying what went
    untested. A permission fixture is a measurement, not a given (CLAUDE.md), and
    an injected one is no different.
    """
    seams = (
        ("os.stat", lambda: os.stat(str(target))),
        ("Path.stat", lambda: Path(str(target)).stat()),
    )
    for what, call in seams:
        try:
            call()
        except FileNotFoundError:
            continue
        except OSError as exc:  # pragma: no cover - the patch raised something else
            pytest.skip(
                "the injected fold did not take on {}: it raised {} instead of "
                "FileNotFoundError ({}). UNTESTED here: that a name stat cannot "
                "reach while its parent lists it answers the third state. "
                "platform={} python={}".format(
                    what, type(exc).__name__, exc, sys.platform, sys.version.split()[0]
                )
            )
        else:
            pytest.skip(
                "the injected fold did not take on {}: the call succeeded. "
                "UNTESTED here: that a name stat cannot reach while its parent "
                "lists it answers the third state. platform={} python={}".format(
                    what, sys.platform, sys.version.split()[0]
                )
            )


@pytest.fixture
def folded(monkeypatch, tmp_path):
    """A directory that really is there, which `stat` reports as ordinary absence."""
    parent = tmp_path / "root"
    parent.mkdir()
    target = parent / "380"
    target.mkdir()
    _fold(monkeypatch, target)
    _require_injection(target)
    return target


# ------------------------------------------------------------ the defect itself


def test_worktree_occupancy_is_unknown_not_free_for_a_folded_name(folded):
    verdict = lane_setup.worktree_occupancy(str(folded))
    assert verdict is None, (
        "stat reported ordinary absence for a name its own parent still lists, and "
        "worktree_occupancy answered {!r} instead of unknown -- the receipt would "
        "print [free] for a worktree nothing looked at".format(verdict)
    )


def test_dir_state_is_unreadable_not_absent_for_a_folded_name(folded):
    state, detail = doctor._dir_state(folded)
    assert state == "unreadable", (state, detail)


def test_the_receipt_says_unknown_not_free_for_a_folded_name(folded):
    """The harm is the rendered word. `[free]` is what a maintainer pastes."""
    payload = {
        "issue": 380,
        "repo": ".",
        "config": {"state": "ok", "problems": []},
        "base": {"state": "could-not-resolve", "remote": "origin", "ref": None,
                 "sha": None, "detail": "x"},
        "branch": {"state": "unknown", "pattern": None, "name": None, "detail": "x",
                   "exists_local": None, "exists_remote": None},
        "worktree": {"state": "resolved", "root": str(folded.parent),
                     "path": str(folded), "detail": "",
                     "exists": lane_setup.worktree_occupancy(str(folded))},
        "board": {"state": "could-not-run", "lines": [], "detail": "x"},
    }
    row = [ln for ln in lane_setup.receipt(payload).splitlines()
           if ln.startswith("worktree  :")]
    assert len(row) == 1, row
    assert row[0].endswith("[unknown]"), row[0]
    assert "[free]" not in row[0], row[0]


def test_the_two_classifiers_agree_on_a_folded_name(folded):
    """#380 is one decision about two functions, and this is what says so."""
    state, detail = doctor._dir_state(folded)
    assert state == "unreadable", (state, detail)
    assert lane_setup.worktree_occupancy(str(folded)) is None


# --------------------------------------------- the must-fire half, same fixture


def test_a_genuinely_absent_name_is_still_absent_under_the_same_injection(
    monkeypatch, tmp_path
):
    """The fix must not fold every negative into `unknown`. Same injection seam,
    same shape, on a name that really is not there -- so a classifier that had
    simply stopped answering `False` would pass every test above and fail here.
    """
    parent = tmp_path / "root"
    parent.mkdir()
    absent = parent / "380"
    _fold(monkeypatch, absent)
    _require_injection(absent)

    assert lane_setup.worktree_occupancy(str(absent)) is False
    assert doctor._dir_state(absent)[0] == "absent"


def test_a_present_name_is_still_present_with_no_injection_at_all(tmp_path):
    """The other must-fire control: nothing is patched, and both classifiers must
    still resolve. A pair that agreed only by both refusing to answer would pass
    the agreement test above.
    """
    here = tmp_path / "here"
    here.mkdir()
    assert lane_setup.worktree_occupancy(str(here)) is True
    assert doctor._dir_state(here)[0] == "dir"


def test_a_name_under_a_file_is_still_absent(tmp_path):
    """A non-directory has no children, so absence there is confirmable without a
    listing at all -- and `NotADirectoryError` must not start answering `unknown`.
    """
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    under = afile / "under"
    assert lane_setup.worktree_occupancy(str(under)) is False
    assert doctor._dir_state(under)[0] == "absent"


def test_an_absent_name_under_an_absent_root_is_still_absent(tmp_path):
    """The common real input: `worktree_root/NNN` where the root itself has not
    been created yet. The confirmation walks up to the first ancestor this
    platform can look at, so this must stay `False` rather than becoming the
    noisy third state on every fresh machine.
    """
    nowhere = tmp_path / "no-root" / "deeper" / "380"
    assert lane_setup.worktree_occupancy(str(nowhere)) is False
    assert doctor._dir_state(nowhere)[0] == "absent"


# ------------------------------------------------------ a real path, measured


def _many_short_components(root, want=400):
    """A long path built out of one-character components.

    `MAX_PATH` caps the whole path at 260 on Windows and `NAME_MAX` caps each
    *component* at 255 on POSIX, and a fixture in this repo has already failed
    each limit by satisfying the other (CLAUDE.md). Many short components cannot
    violate either by construction, which is a construction rather than an
    assertion that a construction is safe.
    """
    path = root
    while len(str(path)) < want:
        path = path / "d"
    return path


def test_a_real_long_path_is_measured_rather_than_assumed(tmp_path):
    """Three outcomes, and the third is why this is not a table.

    The tree is attempted. If this platform will not build it, that is reported as
    what went untested, carrying the errno and the interpreter -- never an assertion
    from a constant, since `MAX_PATH` is conditional on a machine setting and a
    constant would be the errno table wearing a different hat (#380).
    """
    deep = _many_short_components(tmp_path)
    try:
        os.makedirs(str(deep))
    except OSError as exc:
        pytest.skip(
            "this platform would not create a {}-character path out of "
            "one-character components: {} (errno {}). UNTESTED here: what the two "
            "classifiers answer for a real path at that length. platform={} "
            "python={}".format(
                len(str(deep)), type(exc).__name__, exc.errno, sys.platform,
                sys.version.split()[0]
            )
        )

    try:
        os.stat(str(deep))
    except OSError as exc:
        # The platform reached its own limit on a path that exists. Whatever it
        # called it, the honest answer is the third state.
        assert lane_setup.worktree_occupancy(str(deep)) is None, (
            type(exc).__name__, exc.errno
        )
        assert doctor._dir_state(deep)[0] == "unreadable"
        return

    # The platform handled the length. That is a must-fire control rather than a
    # skip: length alone must not push either classifier off its answer.
    assert lane_setup.worktree_occupancy(str(deep)) is True
    assert doctor._dir_state(deep)[0] == "dir"


# --------------------------------------------------- the confirmation helper


@pytest.mark.parametrize("which", ["lane_setup", "doctor"])
def test_the_confirmation_helper_reports_all_three_of_its_own_states(which, tmp_path):
    """The helper is the new guard, and a guard that can only ever answer one way
    passes a suite that exercises one of them. All three arms, in both copies --
    the two are siblings rather than one import, so both are held.
    """
    confirm = (doctor if which == "doctor" else lane_setup)._absence_confirmed

    parent = tmp_path / "p"
    parent.mkdir()
    (parent / "there").mkdir()

    assert confirm(str(parent / "not-there")) is True, "confirmed absence"
    assert confirm(str(parent / "there")) is False, "the name is in the listing"
    # The anchor is its own parent, so the walk runs out of ancestors to ask and
    # has nothing to confirm with. Spelled through `abspath` rather than as a
    # literal, so it is the drive root on Windows and `/` on POSIX without either
    # being written down here.
    assert confirm(os.path.abspath(os.sep)) is None, "no ancestor left to ask"


def test_an_embedded_null_answers_rather_than_raising(tmp_path):
    """`os.stat` raises `ValueError`, not `OSError`, for a path with a null byte,
    so neither `except` arm caught it and it escaped both functions -- a raise path
    in a script whose contract is exit 0 always, one VERDICT line. `.oss.local.json`
    is JSON, and JSON spells a NUL as an ordinary escape.

    Adjacent to #380 and fixed with it because it is the same two `except` clauses.
    """
    bad = str(tmp_path) + NUL + "380"
    assert lane_setup.worktree_occupancy(bad) is None
    assert doctor._dir_state(Path(bad))[0] == "unreadable"
