"""`resolve_config_path` must be able to search from a directory that is not cwd (#70).

Every fixture here deliberately separates the process's current directory from the
directory being asked about, and puts a *different* answer in each. Without that
separation these tests pass on the code that reads only cwd, because the two coincide
in every fixture that existed before this one.
"""

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import oss_config  # noqa: E402


def _clone(root, name):
    """A git clone -- the shape `.oss.json` is git-excluded for."""
    clone = root / name
    clone.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", str(clone)])
    return clone


def _write_config(directory, repo):
    (directory / oss_config.CONFIG_NAME).write_text(
        json.dumps({"repo": repo}), encoding="utf-8"
    )


def _repo_of(resolved):
    return json.loads(Path(resolved).read_text(encoding="utf-8"))["repo"]


def test_the_search_follows_start_and_not_the_process_directory(tmp_path, monkeypatch):
    """Two clones, each with its own config, and the process standing in the wrong one.

    On the code this issue is about, the answer is whichever clone the process happens
    to be in -- which is the defect: no caller can ask about anywhere else.
    """
    here = _clone(tmp_path, "here")
    there = _clone(tmp_path, "there")
    _write_config(here, "owner/where-the-process-stands")
    _write_config(there, "owner/what-was-asked-about")
    (here / "sub").mkdir()
    (there / "sub").mkdir()
    monkeypatch.chdir(here / "sub")

    resolved, origin, detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=there / "sub"
    )

    assert origin == "clone", detail
    assert Path(resolved).resolve() == (there / oss_config.CONFIG_NAME).resolve(), (
        detail
    )
    assert _repo_of(resolved) == "owner/what-was-asked-about"


def test_a_config_at_start_itself_wins_over_the_clone(tmp_path, monkeypatch):
    """Positive control for the widening: it must not reach past a file at `start`."""
    here = _clone(tmp_path, "here")
    there = _clone(tmp_path, "there")
    _write_config(here, "owner/cwd-clone")
    _write_config(there, "owner/clone-half")
    (there / "sub").mkdir()
    _write_config(there / "sub", "owner/start-half")
    monkeypatch.chdir(here)

    resolved, origin, detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=there / "sub"
    )

    assert origin == "here", detail
    assert _repo_of(resolved) == "owner/start-half"


def test_start_outside_any_clone_is_not_the_same_answer_as_a_clone_with_no_config(
    tmp_path, monkeypatch
):
    """The fourth state, paired with the third in one fixture.

    "The clone was searched and has none" and "there was no clone to search" are two
    different sentences to a maintainer, and one value today. The pairing is what makes
    it an assertion: alone, the first half passes for any answer that is not `clone`.
    """
    clone = _clone(tmp_path, "clone")
    (clone / "sub").mkdir()
    loose = tmp_path / "loose"
    loose.mkdir()
    monkeypatch.chdir(clone)

    _, no_clone_origin, no_clone_detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=loose
    )
    _, empty_origin, empty_detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=clone / "sub"
    )

    assert empty_origin == "missing", empty_detail
    assert str(clone) in empty_detail, empty_detail
    assert no_clone_origin == "unsearchable", no_clone_detail
    assert no_clone_origin != empty_origin
    assert str(clone) not in no_clone_detail, (
        "a directory in no repository must not have the caller's clone named at it"
    )


def test_a_start_that_does_not_exist_never_widens_to_the_process_clone(
    tmp_path, monkeypatch
):
    """#62's defect, one layer down: a directory that is not there fell back to `.`, so
    the answer described whatever repo the caller happened to be standing in."""
    clone = _clone(tmp_path, "clone")
    _write_config(clone, "owner/not-what-was-asked-about")
    monkeypatch.chdir(clone)
    absent = tmp_path / "nowhere"

    resolved, origin, detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=absent
    )

    assert resolved is None
    assert origin == "unsearchable", detail
    assert str(clone) not in detail, detail


def test_start_reached_by_a_symlinked_name_still_finds_the_clones_config(
    tmp_path, monkeypatch
):
    """pytest realpaths `tmp_path`, so the `/tmp` -> `/private/tmp` class of failure
    needs a symlink the fixture builds itself (#69's shape).

    This is the near-miss recorded in #70: bridging cwd and `start` with
    `os.path.relpath` produced `../../../../../<clone>/sub/.oss.json` and a clean-looking
    FAIL with the config in that clone the whole time. `start` must make the answer
    depend on cwd in no way at all.
    """
    real = _clone(tmp_path, "real")
    (real / "sub").mkdir()
    _write_config(real, "owner/behind-the-link")
    elsewhere = _clone(tmp_path, "elsewhere")
    _write_config(elsewhere, "owner/where-the-process-stands")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip(
            "this platform will not create a directory symlink without privileges"
        )
    monkeypatch.chdir(elsewhere)

    resolved, origin, detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=link / "sub"
    )

    assert origin == "clone", detail
    assert Path(resolved).is_file(), resolved
    assert ".." not in Path(resolved).parts, (
        "a path walked back up through cwd is the #53 defect reintroduced: {}".format(
            resolved
        )
    )
    assert _repo_of(resolved) == "owner/behind-the-link"


def test_omitting_start_still_answers_about_the_process_directory(
    tmp_path, monkeypatch
):
    """Back-compat, stated rather than assumed: every existing caller passes no `start`."""
    clone = _clone(tmp_path, "clone")
    _write_config(clone, "owner/cwd-clone")
    other = _clone(tmp_path, "other")
    _write_config(other, "owner/not-this-one")
    (clone / "sub").mkdir()
    monkeypatch.chdir(clone / "sub")

    resolved, origin, detail = oss_config.resolve_config_path(oss_config.CONFIG_NAME)

    assert origin == "clone", detail
    assert _repo_of(resolved) == "owner/cwd-clone"


def test_load_from_carries_start_through(tmp_path, monkeypatch):
    """The seam callers actually use. A `start` the resolver takes and `load_from` drops
    is a parameter no caller can reach."""
    here = _clone(tmp_path, "here")
    there = _clone(tmp_path, "there")
    (there / "sub").mkdir()
    _write_config(there, "owner/asked-about")
    monkeypatch.chdir(here)

    config, problems, origin, resolved = oss_config.load_from(
        oss_config.CONFIG_NAME, start=there / "sub"
    )

    assert origin == "clone", problems
    assert config is not None, problems
    assert config["repo"] == "owner/asked-about"
    assert Path(resolved).resolve() == (there / oss_config.CONFIG_NAME).resolve()


def test_a_path_with_an_anchor_of_its_own_is_refused_rather_than_joined(
    tmp_path, monkeypatch
):
    """Windows only, and therefore measured rather than reasoned about.

    `PureWindowsPath("D:/start") / "C:x"` is `C:x`: pathlib drops the base when the
    right-hand side carries an anchor. Under `start` that silently means "search the
    process's directory after all", which is the one thing `start` exists to prevent, so
    it is a stated refusal. The predicate is asserted directly because no POSIX runner
    can build a fixture that reaches this branch.
    """
    assert oss_config._anchored_elsewhere(PureWindowsPath("C:x")), "drive-relative"
    assert oss_config._anchored_elsewhere(PureWindowsPath("/x/.oss.json")), (
        "root-relative"
    )
    assert PureWindowsPath("D:/start") / PureWindowsPath("C:x") == PureWindowsPath(
        "C:x"
    ), "pathlib no longer drops the base, so this guard is guarding nothing"

    # Positive control: the shapes every real caller passes must NOT be refused, or the
    # guard above is satisfied by a predicate that refuses everything.
    assert not oss_config._anchored_elsewhere(PurePosixPath(".oss.json"))
    assert not oss_config._anchored_elsewhere(PurePosixPath("configs/.oss.json"))
    assert not oss_config._anchored_elsewhere(PureWindowsPath("configs/.oss.json"))
    assert not oss_config._anchored_elsewhere(PureWindowsPath("C:/full/.oss.json")), (
        "an absolute path is handled by its own arm, not by this one"
    )
    assert not oss_config._anchored_elsewhere(PurePosixPath("/full/.oss.json"))

    # And end-to-end on this platform, where the predicate is false for every spelling:
    # a start-relative search still works, so the guard cannot have swallowed it.
    clone = _clone(tmp_path, "clone")
    _write_config(clone, "owner/still-reachable")
    (clone / "sub").mkdir()
    monkeypatch.chdir(tmp_path)
    _, origin, detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=clone / "sub"
    )
    assert origin == "clone", detail


def test_an_absolute_path_is_still_an_answer_and_not_a_starting_point(
    tmp_path, monkeypatch
):
    """`start` does not turn a path somebody typed in full into a starting point."""
    clone = _clone(tmp_path, "clone")
    _write_config(clone, "owner/clone-half")
    (clone / "sub").mkdir()
    monkeypatch.chdir(tmp_path)

    resolved, origin, detail = oss_config.resolve_config_path(
        clone / "sub" / oss_config.CONFIG_NAME, start=clone / "sub"
    )

    assert (resolved, origin) == (None, "missing"), detail
    assert "enclosing clone" not in detail, detail
