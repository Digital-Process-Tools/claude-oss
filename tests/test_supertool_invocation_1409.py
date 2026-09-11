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

**#1459: bare two-file existence (`.supertool.json` + `supertool.py`) is not
enough on its own.** `.supertool.json` is a scaffolded DEFAULT in every
managed repo, so a `supertool.py` planted at that repo's root by an ordinary
pull request used to be sufficient to make this walk claim own-tree and hand
that file to `sys.executable`. `_own_supertool_tree` now also requires
`_supertool_tree_identity_confirmed` to agree that the tree's own git
`origin` names claude-supertool's repository (never a tracked file, so a
pull request cannot move it) -- the two "own-tree" tests below now inject
that agreement (`dependency_repos`/`run`), and a new test proves the reverse:
an origin naming some OTHER repository must not be trusted, the exact shape
of the vulnerability this issue is about.
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


#: The repository the installed `supertool` dependency's own manifest
#: declares -- the fixed comparison point every #1459 test below injects
#: via `dependency_repos` rather than reading the real plugin cache, so
#: these tests are hermetic on a machine with no supertool install at all.
_SUPERTOOL_REPOS = {
    "supertool": "https://github.com/Digital-Process-Tools/claude-supertool"
}


def _fake_git_remote(url):
    """A fake `run=` for `subprocess.run`, standing in for `git remote
    get-url origin` and answering with `url` -- #1459's injection seam."""

    def _run(argv, **kwargs):
        class _Result:
            returncode = 0
            stdout = url + "\n"
            stderr = ""

        return _Result()

    return _run


def test_inside_a_supertool_checkout_the_invocation_is_the_own_core(tmp_path):
    """A repo whose own tree carries `.supertool.json` beside `supertool.py`
    (the shape `_own_supertool_tree` walks up for), AND whose own git origin
    names claude-supertool's repository (#1459), must be run with its own
    core through the interpreter, never the bare `supertool` name."""
    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# stand-in core\n")

    argv, detail = doctor.supertool_invocation(
        tmp_path,
        dependency_repos=_SUPERTOOL_REPOS,
        run=_fake_git_remote(
            "https://github.com/Digital-Process-Tools/claude-supertool.git"
        ),
    )
    assert argv[0] == sys.executable, (argv, detail)
    assert argv[1].endswith("supertool.py"), (argv, detail)
    assert "own-tree" in detail


def test_a_worktree_of_a_supertool_checkout_also_resolves_to_its_own_core(tmp_path):
    """The case #1409 was actually filed against: a *worktree*, one directory
    below the tree carrying `.supertool.json`/`supertool.py` -- the walk must
    still find the root's own core rather than stopping at the worktree, once
    #1459's origin check also confirms the root's own identity."""
    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# stand-in core\n")
    worktree = tmp_path / "worktrees" / "fix-1"
    worktree.mkdir(parents=True)

    argv, detail = doctor.supertool_invocation(
        worktree,
        dependency_repos=_SUPERTOOL_REPOS,
        run=_fake_git_remote(
            "https://github.com/Digital-Process-Tools/claude-supertool.git"
        ),
    )
    assert argv[0] == sys.executable, (argv, detail)
    assert argv[1].endswith("supertool.py"), (argv, detail)


def test_a_stray_supertool_py_in_a_managed_repo_is_not_trusted(tmp_path):
    """#1459's own reproduction: `.supertool.json` is a scaffolded DEFAULT in
    every managed repo, so the bare existence test above used to be enough on
    its own -- a `supertool.py` an ordinary pull request adds to a repo that
    is NOT claude-supertool (here: this repo's own origin, claude-oss) must
    not be selected for execution. Paired with the two "must fire" tests
    above, which show the identical shape trusted when the origin actually
    does match."""
    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text(
        "# a stray file added by an ordinary pull request\n"
    )

    argv, detail = doctor.supertool_invocation(
        tmp_path,
        dependency_repos=_SUPERTOOL_REPOS,
        run=_fake_git_remote("https://github.com/Digital-Process-Tools/claude-oss.git"),
    )
    assert argv == ["supertool"], (argv, detail)
    assert "not a supertool checkout" in detail


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
