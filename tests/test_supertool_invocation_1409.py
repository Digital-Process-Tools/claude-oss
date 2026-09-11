"""#1409: the brief's mandatory supertool blockquote says "on PATH, from any
directory" -- wrong inside a supertool checkout's own worktree.

That is correct for every managed repo except claude-supertool itself: inside
a worktree of that checkout the global `supertool` on PATH resolves to
whichever clone the SessionStart hook last linked (ordinarily the live
checkout at `master`), and running it from a worktree runs master's core
against the worktree's own branch-local presets -- silently wrong for a
read-class op, and refused outright for a write-class one
(claude-supertool#1942). A lane dispatched with the verbatim blockquote,
followed literally, cost three round-trips, one of them
`lane_setup.py`'s own board-line shelling out to bare `supertool` and
producing "COULD NOT RUN -- mixed supertool trees".

`doctor.supertool_invocation` is the detection this closes: reusing
`_own_supertool_tree`'s own walk (the same one `check_supertool_entry_point`
already uses to decide the `own-tree` diagnostic state) rather than adding a
second, drifting copy of "is this repo a supertool checkout" (CLAUDE.md's own
rule against a fact about one repository living in shared code).

Two halves, and the second is the positive control CLAUDE.md requires beside
any "must not fire" assertion.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import doctor  # noqa: E402
import lane_setup  # noqa: E402


def test_outside_a_supertool_checkout_the_invocation_is_unchanged(tmp_path):
    """Positive control: every other managed repo's blockquote stays correct
    exactly as written, and this function must not special-case it."""
    argv, detail = doctor.supertool_invocation(tmp_path)
    assert argv == ["supertool"], (argv, detail)
    assert "not a supertool checkout" in detail


def test_inside_a_supertool_checkout_the_invocation_is_the_own_core(tmp_path):
    """A repo whose own tree carries `.supertool.json` beside `supertool.py`
    (the shape `_own_supertool_tree` walks up for) must be run with its own
    core through the interpreter, never the bare `supertool` name."""
    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# stand-in core\n")

    argv, detail = doctor.supertool_invocation(tmp_path)
    assert argv[0] == sys.executable, (argv, detail)
    assert argv[1].endswith("supertool.py"), (argv, detail)
    assert "own-tree" in detail


def test_a_worktree_of_a_supertool_checkout_also_resolves_to_its_own_core(tmp_path):
    """The case #1409 was actually filed against: a *worktree*, one directory
    below the tree carrying `.supertool.json`/`supertool.py` -- the walk must
    still find the root's own core rather than stopping at the worktree."""
    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# stand-in core\n")
    worktree = tmp_path / "worktrees" / "fix-1"
    worktree.mkdir(parents=True)

    argv, detail = doctor.supertool_invocation(worktree)
    assert argv[0] == sys.executable, (argv, detail)
    assert argv[1].endswith("supertool.py"), (argv, detail)


def test_read_board_uses_the_own_tree_core_inside_a_supertool_checkout(
    tmp_path, monkeypatch
):
    """`lane_setup.read_board` routes through `doctor.supertool_invocation`
    rather than shelling out to the bare `supertool` name unconditionally --
    the fix for the `COULD NOT RUN -- mixed supertool trees` receipt line
    #1409 reported."""
    core = tmp_path / "supertool.py"
    monkeypatch.setattr(
        lane_setup.doctor,
        "supertool_invocation",
        lambda repo: ([sys.executable, str(core)], "own-tree: {0}".format(core)),
    )

    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv

        class _Result:
            returncode = 0
            stdout = "--- git-worktrees ---\n"
            stderr = ""

        return _Result()

    monkeypatch.setattr(lane_setup.subprocess, "run", _fake_run)

    result = lane_setup.read_board(tmp_path)
    assert result["state"] == "ok", result
    assert captured["argv"][0] == sys.executable
    assert captured["argv"][1] == str(core)
    assert captured["argv"][2] == "git-worktrees"


def test_read_board_still_uses_the_bare_name_outside_a_supertool_checkout(
    tmp_path, monkeypatch
):
    """Positive control: every other managed repo keeps the original
    `gh_which.safe_which("supertool")` path unchanged."""
    monkeypatch.setattr(
        lane_setup.doctor,
        "supertool_invocation",
        lambda repo: (["supertool"], "not a supertool checkout"),
    )
    monkeypatch.setattr(
        lane_setup.gh_which, "safe_which", lambda name: "/usr/local/bin/supertool"
    )

    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv

        class _Result:
            returncode = 0
            stdout = "--- git-worktrees ---\n"
            stderr = ""

        return _Result()

    monkeypatch.setattr(lane_setup.subprocess, "run", _fake_run)

    result = lane_setup.read_board(tmp_path)
    assert result["state"] == "ok", result
    assert captured["argv"] == ["/usr/local/bin/supertool", "git-worktrees"]
