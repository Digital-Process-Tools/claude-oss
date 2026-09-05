"""#383: the swallow census, `scripts/assemble_changelog.py`.

Two sites named by the issue's own comment as "the one worth doing next" --
`collect()`'s directory check (line 634 at the time of filing) and the
per-entry filter beside it (line 640). The issue's own rule decides which is
which: a call that only *filters a list* may swallow; a call that *prints a
verdict* must classify in three states.

`collect()`'s `if not directory.is_dir(): raise BadFragment(...)` prints a
verdict -- "fragment directory does not exist" is the message a maintainer
reads at a release cut -- so it is the site fixed here. `Path.is_dir()` /
`Path.exists()` swallow `OSError` to `False` on some interpreter versions
(CLAUDE.md's own `Path.exists()`/`Path.is_dir()` trap; also
`scripts/doctor.py`'s `_dir_state` docstring, which measured the same
swallow directly on a local 3.14 install), so a permission-denied
`changelog.d/` would print a confident "does not exist" for a directory
that is right there -- indistinguishable, to a maintainer reading the
refusal, from the directory genuinely being absent.

Every "must not fire" case (unreadable must not become "does not exist") is
paired with a "must fire" control in the same fixture (genuine absence must
still be reported, and a genuinely readable directory must still collect
normally) -- CLAUDE.md's own rule for a negative assertion.

The loop's `path.is_dir() or path.name in _IGNORED or ...` filter (line 640)
is not touched: it is a *filter* site, and even swallowed to `False` its
worst case is trying to read a directory as a fragment file, which raises
loudly out of `path.read_text()` a few lines later rather than silently
dropping the entry. Left as-is by design; recorded in the agent report
rather than "fixed" here, per the issue's own instruction that a site
judged correct is a result worth reporting as loudly as a site that needed
a fix.
"""

import errno
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assemble_changelog  # noqa: E402
import doctor  # noqa: E402
import lane_setup  # noqa: E402


def _raise_stat_for(monkeypatch, target, exc):
    """Patch `Path.stat` to raise `exc` only for `target`'s own path, and
    behave normally everywhere else -- self-verifying, since a fixture that
    patched every `stat` call would make the "must fire" and "must not
    fire" cases in the same tree indistinguishable.
    """
    real_stat = Path.stat
    target_str = str(target)

    def fake(self, *a, **kw):
        if str(self) == target_str:
            raise exc
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", fake)


def test_unreadable_fragment_dir_is_cannot_validate_not_bad_fragment_injected(
    monkeypatch, tmp_path
):
    """Must-fire half: a directory `stat` cannot reach is reported as
    "could not determine", never as the confident "does not exist" a
    genuinely absent directory earns.
    """
    directory = tmp_path / "changelog.d"
    directory.mkdir()
    (directory / "1.added.md").write_text("- something (#1)\n", encoding="utf-8")

    _raise_stat_for(monkeypatch, directory, PermissionError(13, "denied"))

    with pytest.raises(assemble_changelog.CannotValidate) as exc_info:
        assemble_changelog.collect(directory)
    assert "does not exist" not in str(exc_info.value)


def test_genuinely_absent_fragment_dir_is_still_bad_fragment_control(tmp_path):
    """Must-not-fire control, same class of fixture: a directory that truly
    is not there must still raise `BadFragment` naming it absent -- the fix
    must not fold every `OSError` into "could not determine" and lose the
    ordinary refusal.
    """
    directory = tmp_path / "does-not-exist"

    with pytest.raises(assemble_changelog.BadFragment) as exc_info:
        assemble_changelog.collect(directory)
    assert "does not exist" in str(exc_info.value)


def test_readable_fragment_dir_still_collects_normally_control(tmp_path):
    """Second control, same fixture family: an ordinary readable directory
    is unaffected by the classification change.
    """
    directory = tmp_path / "changelog.d"
    directory.mkdir()
    (directory / "1.added.md").write_text("- something (#1)\n", encoding="utf-8")

    fragments = assemble_changelog.collect(directory)
    assert [f.issue for f in fragments] == [1]


def test_unlookable_fragment_dir_is_cannot_validate_not_absent_windows_fold(
    monkeypatch, tmp_path
):
    """Must-fire half, the case a first-pass reviewer of this same fix
    found missing: `FileNotFoundError` alone is not evidence of genuine
    absence. CLAUDE.md's own measurement is that an over-`MAX_PATH` name on
    Windows arrives as `FileNotFoundError, errno 2, winerror None` -- no
    distinguishing signal from a name that is truly not there -- which is
    the exact fold `doctor._dir_state` and `lane_setup._absence_confirmed`
    exist to see through, by confirming absence positively against the
    subject's own deepest lookable ancestor rather than trusting the
    exception type alone. Reproduced here the same way those two do: the
    entry is present in its parent's own listing, and `stat` still raised
    `FileNotFoundError` -- the unlookable case wearing absence's clothes.
    """
    directory = tmp_path / "changelog.d"
    directory.mkdir()

    real_stat = Path.stat
    target_str = str(directory)

    def fake(self, *a, **kw):
        if str(self) == target_str:
            raise FileNotFoundError(2, "folded")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", fake)

    with pytest.raises(assemble_changelog.CannotValidate) as exc_info:
        assemble_changelog.collect(directory)
    assert "does not exist" not in str(exc_info.value)


def test_unreadable_fragment_dir_real_chmod(tmp_path):
    """Same must-fire case, reproduced against a real filesystem rather than
    an injected raise -- a permission fixture is a measurement, not a
    given (CLAUDE.md). Self-skips with what went untested when this
    platform's own permission model does not take the deny (root, some
    filesystems, Windows attributes not stopping a listing).
    """
    import os

    parent = tmp_path / "parent"
    parent.mkdir()
    directory = parent / "changelog.d"
    directory.mkdir()
    (directory / "1.added.md").write_text("- something (#1)\n", encoding="utf-8")

    try:
        os.chmod(str(parent), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether the parent-unreadable case reaches CannotValidate on "
            "this platform".format(exc)
        )
    try:
        if os.access(str(directory), os.F_OK):
            pytest.skip(
                "this process can still stat a path under a 0o000 parent "
                "(root, or a filesystem without POSIX modes); what went "
                "untested is whether the unreadable case reaches "
                "CannotValidate on this platform"
            )
        with pytest.raises(assemble_changelog.CannotValidate) as exc_info:
            assemble_changelog.collect(directory)
        assert "does not exist" not in str(exc_info.value)
    finally:
        os.chmod(str(parent), 0o755)


# ---------------------------------------------------------------------------
# Sibling parity. A self-review round of this fix found a third, standalone
# copy of `doctor._dir_state`/`lane_setup.worktree_occupancy`'s classifier
# added here with nothing pinning it against the other two -- the mechanism
# `doctor._dir_state`'s own docstring names as what actually prevents drift
# ("what holds them together is `tests/test_unlookable_absence_380.py`... and
# `tests/test_lane_setup_373.py`, not this paragraph") does not cover this
# third copy. This closes that gap from this file's own side, without
# editing `tests/test_unlookable_absence_380.py` itself -- that file and
# `doctor.py` may be held by another lane at the time this is written, and a
# parity check belongs wherever it can be added without touching either
# sibling's own files.
# ---------------------------------------------------------------------------


def _fold(monkeypatch, target):
    """Emulate the Windows fold on `target` only: `stat` answers ordinary
    absence for a name that is really there. Same construction as
    `tests/test_unlookable_absence_380.py::_fold`, reproduced here rather
    than imported so this file has no test-to-test dependency on a file
    this lane does not own; deliberately patches both `os.stat` and
    `Path.stat`, since `assemble_changelog._absence_confirmed` calls the
    former and `_fragment_dir_state` calls the latter.
    """
    wanted = os.path.normcase(os.path.abspath(str(target)))
    real_os_stat = os.stat
    real_path_stat = Path.stat

    def fake_os_stat(value, *args, **kwargs):
        try:
            key = os.path.normcase(os.path.abspath(os.fspath(value)))
        except (OSError, ValueError, TypeError):
            key = None
        if key == wanted:
            raise FileNotFoundError(
                errno.ENOENT, "No such file or directory", str(value)
            )
        return real_os_stat(value, *args, **kwargs)

    def fake_path_stat(self, *args, **kwargs):
        try:
            key = os.path.normcase(os.path.abspath(str(self)))
        except (OSError, ValueError, TypeError):
            key = None
        if key == wanted:
            raise FileNotFoundError(
                errno.ENOENT, "No such file or directory", str(self)
            )
        return real_path_stat(self, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fake_os_stat)
    monkeypatch.setattr(Path, "stat", fake_path_stat)


def test_all_three_classifiers_agree_on_a_folded_name(monkeypatch, tmp_path):
    """`assemble_changelog`'s copy answers the same third state
    (unreadable/unknown, never a confident absence) as its two siblings on
    the identical folded-name fixture #380 already established the other
    two on. If a future change to one of the three drifts, this fails --
    which is the whole reason the other two have this test and this one
    did not, until now.
    """
    parent = tmp_path / "root"
    parent.mkdir()
    target = parent / "383"
    target.mkdir()
    _fold(monkeypatch, target)

    try:
        os.stat(str(target))
    except FileNotFoundError:
        pass
    else:
        pytest.skip(
            "the injected fold did not take: os.stat succeeded against the "
            "patched target. UNTESTED here: whether the three classifiers "
            "agree on a folded name. platform={} python={}".format(
                sys.platform, sys.version.split()[0]
            )
        )

    doctor_state, _ = doctor._dir_state(target)
    lane_setup_verdict = lane_setup.worktree_occupancy(str(target))
    ac_state, _ = assemble_changelog._fragment_dir_state(target)

    assert doctor_state == "unreadable", doctor_state
    assert lane_setup_verdict is None, lane_setup_verdict
    assert ac_state == "unreadable", (
        "assemble_changelog._fragment_dir_state disagreed with its two "
        "siblings on the identical folded-name fixture: {!r} where both "
        "answered 'could not determine'".format(ac_state)
    )
