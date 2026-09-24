"""#905: `trap.d/` fragments, and the three states of asking how many are waiting.

A curation pass that was silently skipped and a cycle with nothing to curate must not render
identically -- that is this repository's own defect class pointed at its own queue. So
`scripts/trap_curate.py` answers `waiting` / `none` / `could-not-read`, never a bare integer, and
never `0` for a directory it could not open.

The filename check is deliberately the only thing validated about a fragment. Content structure,
a required dimension, a match pattern and a firing proof are all *absent on purpose*: every one of
them is friction at the moment friction stops the lesson being written, which is what #905 exists
to remove. A test asserting a fragment has a heading would be re-adding the thing being removed.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import trap_curate  # noqa: E402


def _write(d, name, body="- something cost time\n"):
    (d / name).write_text(body, encoding="utf-8")


def test_a_directory_with_fragments_reports_waiting_and_names_them(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.find-first-locator.md")
    _write(d, "888.rglob-swallows.md")
    r = trap_curate.waiting(tmp_path)
    assert r["state"] == "waiting"
    assert r["count"] == 2
    assert sorted(f["name"] for f in r["fragments"]) == [
        "888.rglob-swallows.md",
        "904.find-first-locator.md",
    ]


def test_an_empty_directory_reports_none_which_is_a_finding_not_an_absence(tmp_path):
    (tmp_path / "trap.d").mkdir()
    r = trap_curate.waiting(tmp_path)
    assert r["state"] == "none"
    assert r["count"] == 0


def test_an_absent_directory_reports_none_and_says_so(tmp_path):
    r = trap_curate.waiting(tmp_path)
    assert r["state"] == "none"
    assert r["count"] == 0
    assert "trap.d" in r["why"]


def test_an_unreadable_directory_never_renders_as_zero(tmp_path):
    """The whole point. A directory that cannot be listed is not an empty one.

    The deny is confirmed by attempting the exact operation the code under test performs, per this
    repository's rule that a permission fixture is a measurement and not a given.
    """
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.x.md")
    os.chmod(d, 0o000)
    try:
        try:
            os.listdir(d)
        except PermissionError:
            pass
        else:
            pytest.skip(
                "this platform still listed a 0o000 directory (root, or a filesystem ignoring the "
                "mode bit), so the unreadable arm went untested here"
            )
        r = trap_curate.waiting(tmp_path)
        assert r["state"] == "could-not-read"
        assert r["count"] is None, (
            "a count that could not be taken must never render as a number"
        )
    finally:
        os.chmod(d, 0o755)


def test_a_filename_that_does_not_parse_is_reported_not_ignored(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.good-one.md")
    _write(d, "no-issue-number.md")
    _write(d, "904.md")
    r = trap_curate.waiting(tmp_path)
    assert r["count"] == 3, (
        "a malformed name is still a logged trap and must not be dropped"
    )
    bad = sorted(f["name"] for f in r["fragments"] if not f["parses"])
    assert bad == ["904.md", "no-issue-number.md"]
    good = [f for f in r["fragments"] if f["parses"]]
    assert good[0]["issue"] == 904 and good[0]["slug"] == "good-one"


def test_non_markdown_and_dotfiles_are_not_counted_as_fragments(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.real.md")
    _write(d, ".DS_Store", "")
    _write(d, "notes.txt", "")
    r = trap_curate.waiting(tmp_path)
    assert r["count"] == 1


def test_this_repository_s_own_trap_d_answers_one_of_the_three_states():
    """The positive control for the negative assertions above: the real directory is readable."""
    r = trap_curate.waiting(REPO_ROOT)
    assert r["state"] in {"waiting", "none", "could-not-read"}
    assert r["state"] != "could-not-read", r.get("why")


def test_every_fragment_in_this_repository_parses_as_issue_dot_slug_dot_md():
    """This is the CI leg. It is the whole of the per-PR validation, on purpose.

    Nothing here checks content: no required heading, no dimension, no match pattern, no firing
    proof. A lane logs prose and moves on; the routing decision belongs to `/oss:curate`, taken
    later with every fragment visible at once.
    """
    r = trap_curate.waiting(REPO_ROOT)
    if r["state"] == "could-not-read":
        pytest.skip("could not read trap.d/ here: {}".format(r.get("why")))
    bad = [f["name"] for f in r["fragments"] if not f["parses"]]
    assert not bad, (
        "trap.d/ fragments must be named <issue>.<slug>.md so two lanes never collide on a path: "
        "{}".format(", ".join(bad))
    )


# --- the doctor line, in all three states -------------------------------------------------
#
# The count reaches a maintainer through `doctor` and nowhere else that runs unprompted, because
# #905 chose reported-never-blocking: a gate here would refuse a security fix over a typo somebody
# logged on Friday. That makes this line the whole forcing function, so it is tested rather than
# assumed, and tested in the state that matters most -- the one where nothing could be read.

import io  # noqa: E402
import contextlib  # noqa: E402

import doctor  # noqa: E402


def _doctor_line(root, config=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor.check_trap_queue(str(root), config=config)
    return buf.getvalue().strip()


def test_doctor_reports_a_waiting_queue_as_notice_naming_the_fragments(tmp_path):
    """`curate_route_threshold` configured -- the ordinary case #905 exists
    to cover. #1610's own not-configured WARN is a distinct case, tested
    separately below."""
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.one.md")
    line = _doctor_line(tmp_path, config={"curate_route_threshold": 15})
    assert line.startswith("NOTICE "), line
    assert "1 waiting" in line and "904.one.md" in line
    assert "/oss:curate" in line


def test_doctor_warns_when_waiting_queue_has_no_curate_route_configured(tmp_path):
    """#1610: a non-empty trap.d/ with no `curate_route_threshold` set is a
    check that could look, had the facts (the count), and must not render
    identically to the ordinary NOTICE reading -- the loop's own curate
    trigger cannot fire on this backlog at all."""
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.one.md")
    line = _doctor_line(tmp_path, config={})
    assert line.startswith("WARN "), line
    assert "1 waiting" in line
    assert (
        "904.one.md" in line
    )  # self-review finding, Explore reviewer: named as in NOTICE
    assert "curate_route_threshold" in line
    assert "#1610" in line


def test_doctor_warns_when_waiting_queue_has_no_config_at_all(tmp_path):
    """Same as above, `config=None` (no .oss.json read at all) rather than an
    empty dict -- both are "could not tell this is configured", never
    "configured"."""
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.one.md")
    line = _doctor_line(tmp_path, config=None)
    assert line.startswith("WARN "), line
    assert "curate_route_threshold" in line


def test_doctor_reports_an_empty_queue_as_ok_and_says_none(tmp_path):
    (tmp_path / "trap.d").mkdir()
    line = _doctor_line(tmp_path)
    assert line.startswith("OK "), line
    assert "none waiting" in line


def test_doctor_never_reports_an_unreadable_queue_as_empty(tmp_path):
    """The state this repository is named after. `could not be read` must not read as `none`."""
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.one.md")
    os.chmod(d, 0o000)
    try:
        try:
            os.listdir(d)
        except PermissionError:
            pass
        else:
            pytest.skip(
                "this platform still listed a 0o000 directory, so the WARN arm went untested here"
            )
        line = _doctor_line(tmp_path)
        assert line.startswith("WARN "), line
        assert "could not be read" in line
        assert "UNKNOWN, not zero" in line
        assert "none waiting" not in line
    finally:
        os.chmod(d, 0o755)


# --- #1723: producer, counter and consumer agreeing on the same set --------------------------
#
# A lane, the releaser and `worktree_reap.py`'s own `harvest_fragments` all write `trap.d/*.md`
# fragments straight into the clone's working tree as a plain filesystem copy, never a commit.
# `untracked_fragments` is the read that sees them; `copy_stray_into` and `sweep_resolved` are
# how a curate pass, cut fresh from `origin/<default_branch>`, evaluates and then reconciles them.

import subprocess  # noqa: E402

import workspace_routes  # noqa: E402


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(args, cwd, env=None):
    return subprocess.run(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env or _git_env(),
    )


@pytest.fixture
def clone(tmp_path):
    """A real git repo on `main`, with `origin/main` faked at the same clean
    commit -- the same shape `test_workspace_routes_1155.py`'s own
    `repo_on_main` fixture uses, kept local here so this module does not
    depend on that one."""
    root = tmp_path / "clone"
    root.mkdir()
    env = _git_env()
    done = _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "checkout", "--quiet", "-B", "main"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    _run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=root,
        env=env,
    )
    return root


def test_untracked_fragments_sees_a_plain_filesystem_copy(clone):
    """The producer side (`harvest_fragments`, a releaser session): a
    fragment written straight into `trap.d/` with no `git add` is
    untracked, and this is the read that reports it, distinctly from
    `waiting()`'s own bare `os.listdir` (which would count it too, but
    with no way to tell it apart from a committed one)."""
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.stray.md").write_text("x\n")
    r = trap_curate.untracked_fragments(clone)
    assert r["state"] == "waiting"
    assert r["count"] == 1
    assert r["fragments"][0]["name"] == "1.stray.md"


def test_untracked_fragments_ignores_a_committed_one(clone):
    env = _git_env()
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.committed.md").write_text("x\n")
    _run(["git", "add", "trap.d"], cwd=clone, env=env)
    _run(["git", "commit", "--quiet", "-m", "committed fragment"], cwd=clone, env=env)
    r = trap_curate.untracked_fragments(clone)
    assert r["state"] == "none"
    assert r["count"] == 0


def test_untracked_fragments_does_not_descend_into_a_subdirectory(clone):
    """Mirrors `waiting_at_ref`'s own deliberately-not-recursive note
    (self-review finding, Explore reviewer, #1476): `--untracked-files=all`
    is needed to see a fragment inside a wholly-untracked `trap.d/` at all,
    but it also expands one level deeper than `waiting()`'s own
    `os.listdir` ever would -- a fragment nested inside a subdirectory of
    `trap.d/` must not be counted."""
    (clone / "trap.d" / "sub").mkdir(parents=True)
    (clone / "trap.d" / "1.top.md").write_text("x\n")
    (clone / "trap.d" / "sub" / "2.nested.md").write_text("y\n")
    r = trap_curate.untracked_fragments(clone)
    assert r["count"] == 1, r
    assert r["fragments"][0]["name"] == "1.top.md"


def test_untracked_fragments_counts_a_non_ascii_filename(clone):
    """Self-review finding (oss:auditor spawn, #1723): git C-quotes any
    path holding a non-ASCII byte by default (`core.quotePath=true`) --
    e.g. an octal-escaped, double-quoted entry -- and the first version of
    this parser stripped only the outer quote and then ran a blanket
    backslash-to-slash replace that corrupted the escape rather than
    decoding it, silently dropping the fragment from the count entirely.
    `-c core.quotePath=false` on the `git status` call sidesteps this by
    never quoting a non-ASCII path in the first place."""
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1723.café.md").write_text("x\n")
    r = trap_curate.untracked_fragments(clone)
    assert r["state"] == "waiting", r
    assert r["count"] == 1, r
    assert r["fragments"][0]["name"] == "1723.café.md"


def test_untracked_fragments_on_a_missing_git_binary_is_could_not_read(clone):
    def _boom(command, **kwargs):
        raise FileNotFoundError("git not on PATH")

    r = trap_curate.untracked_fragments(clone, run=_boom)
    assert r["state"] == "could-not-read"
    assert r["count"] is None


def test_copy_stray_into_copies_without_touching_the_clone(clone, tmp_path):
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.stray.md").write_text("stray body\n")
    worktree = tmp_path / "curate-worktree"
    worktree.mkdir()
    state, copied, skipped, why = trap_curate.copy_stray_into(clone, worktree)
    assert state == "ok", why
    assert copied == ["1.stray.md"]
    assert not skipped
    assert (worktree / "trap.d" / "1.stray.md").read_text() == "stray body\n"
    # never touches the clone
    assert (clone / "trap.d" / "1.stray.md").exists()


def test_copy_stray_into_skips_a_name_collision_rather_than_overwriting(
    clone, tmp_path
):
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.same.md").write_text("clone body\n")
    worktree = tmp_path / "curate-worktree"
    (worktree / "trap.d").mkdir(parents=True)
    (worktree / "trap.d" / "1.same.md").write_text("worktree body\n")
    state, copied, skipped, why = trap_curate.copy_stray_into(clone, worktree)
    assert state == "ok", why
    assert not copied
    assert skipped and skipped[0][0] == "1.same.md"
    assert (worktree / "trap.d" / "1.same.md").read_text() == "worktree body\n"


def test_sweep_resolved_removes_only_names_now_absent_from_the_worktree(
    clone, tmp_path
):
    """The end-of-pass cleanup: `1.resolved.md` was copied in and then
    deleted from the worktree as part of a promote/merge/decline
    disposition -- its stale original in the clone is removed.
    `2.deferred.md` is still sitting in the worktree (deferred), so its
    clone-side original is left exactly where it was."""
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.resolved.md").write_text("x\n")
    (clone / "trap.d" / "2.deferred.md").write_text("y\n")
    worktree = tmp_path / "curate-worktree"
    (worktree / "trap.d").mkdir(parents=True)
    (worktree / "trap.d" / "2.deferred.md").write_text("y\n")  # still here -- deferred

    state, removed, failures, why = trap_curate.sweep_resolved(
        clone, worktree, ["1.resolved.md", "2.deferred.md"]
    )
    assert state == "ok", why
    assert removed == ["1.resolved.md"]
    assert not failures
    assert not (clone / "trap.d" / "1.resolved.md").exists()
    assert (clone / "trap.d" / "2.deferred.md").exists()


def test_sweep_resolved_is_idempotent_on_an_already_removed_name(clone, tmp_path):
    """A name that is already gone from the clone (swept once already, or
    never actually copied) is not a failure -- the goal state is 'absent',
    and it already is. #1741: it also must not be counted as `removed` --
    that word means "deleted a real file this pass" and a name that was
    never actually present in the clone's own untracked set was never
    deleted at all, so it is silently skipped rather than falsely
    reported."""
    (clone / "trap.d").mkdir()
    worktree = tmp_path / "curate-worktree"
    worktree.mkdir()
    state, removed, failures, why = trap_curate.sweep_resolved(
        clone, worktree, ["1.never-there.md"]
    )
    assert state == "ok", why
    assert removed == []
    assert not failures


def test_sweep_resolved_ignores_a_path_traversal_name(clone, tmp_path):
    """#1741: `sweep_resolved`'s earlier version built
    `Path(clone_dir) / DIRNAME / name` for every `--copied` name with no
    check that `name` is a bare filename and no intersection against what
    the clone's own `trap.d/` actually, physically holds -- so a name like
    `../victim.txt` walked outside `trap.d/` entirely and deleted a file
    that was never copied by this pass at all. A name not present in the
    clone's own untracked set (`untracked_fragments`) must never reach
    `.unlink()`, no matter what string arrives in `--copied`."""
    victim = clone / "victim.txt"
    victim.write_text("do not delete me\n")
    (clone / "trap.d").mkdir()
    worktree = tmp_path / "curate-worktree"
    worktree.mkdir()

    state, removed, failures, why = trap_curate.sweep_resolved(
        clone, worktree, ["../victim.txt"]
    )
    assert state == "ok", why
    assert removed == []
    assert not failures
    assert victim.exists(), (
        "a traversal name must never delete anything outside trap.d/"
    )


def test_sweep_resolved_ignores_a_copied_name_the_clone_never_actually_had(
    clone, tmp_path
):
    """#1741: `--copied` is untrusted caller input, not a verified record of
    what this pass copied. A name that survives the worktree-side
    `still_here` filter but was never really untracked in the clone (a
    transcription error, or content-steered composition of the argument)
    must not be treated as removed -- it must be re-checked against the
    clone's own real untracked set before anything is attempted."""
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.real.md").write_text("x\n")
    worktree = tmp_path / "curate-worktree"
    worktree.mkdir()

    state, removed, failures, why = trap_curate.sweep_resolved(
        clone, worktree, ["1.real.md", "2.fabricated.md"]
    )
    assert state == "ok", why
    assert removed == ["1.real.md"]
    assert not failures
    assert not (clone / "trap.d" / "1.real.md").exists()


# --- CLI argv robustness (self-review finding, oss:auditor spawn, #1723) ---------------------


def _main_output(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = trap_curate.main(argv)
    return rc, buf.getvalue()


def test_cli_copy_stray_from_with_no_value_is_an_error_not_a_crash(tmp_path):
    """The first version indexed straight past the end of argv
    (`rest[rest.index(flag) + 1]`), raising an uncaught `IndexError` --
    `commands/run/curate.md`'s own literal invocations can produce exactly
    this shape. Must be a reported `could-not-read`, never a Python
    traceback."""
    rc, out = _main_output(["trap_curate.py", str(tmp_path), "--copy-stray-from"])
    assert rc == 1
    assert "could-not-read" in out
    assert "--copy-stray-from" in out


def test_cli_sweep_resolved_in_with_no_value_is_an_error_not_a_crash(tmp_path):
    rc, out = _main_output(["trap_curate.py", str(tmp_path), "--sweep-resolved-in"])
    assert rc == 1
    assert "could-not-read" in out
    assert "--sweep-resolved-in" in out


def test_cli_sweep_resolved_in_with_copied_flag_but_no_value_is_an_error_not_a_crash(
    tmp_path,
):
    """The exact shape `commands/run/curate.md`'s own literal
    `--sweep-resolved-in <clone> --copied <copied names>` invocation
    produces whenever nothing was copied in and `<copied names>` is
    threaded through as a bare, empty trailing token."""
    rc, out = _main_output(
        [
            "trap_curate.py",
            str(tmp_path),
            "--sweep-resolved-in",
            str(tmp_path),
            "--copied",
        ]
    )
    assert rc == 1
    assert "could-not-read" in out
    assert "--copied" in out


def test_cli_copy_stray_from_prints_a_machine_readable_stray_names_line(
    clone, tmp_path
):
    """#1723 self-review finding (Explore reviewer): the first version
    folded the copied-name list into a human sentence that printed the
    placeholder word "(none)" when the list was empty -- and
    `commands/run/curate.md` told the caller to capture that exact
    sentence's comma-list verbatim, so an empty result threaded the
    literal string "(none)" into the sweep step's `--copied` value rather
    than an empty one. `STRAY-NAMES:` is a dedicated line whose value is
    the real, possibly-empty comma list."""
    worktree = tmp_path / "curate-worktree"
    worktree.mkdir()
    rc, out = _main_output(
        ["trap_curate.py", str(worktree), "--copy-stray-from", str(clone)]
    )
    assert rc == 0
    assert "STRAY-NAMES: \n" in out or out.rstrip("\n").endswith("STRAY-NAMES: ")
    assert "(none)" not in out

    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.stray.md").write_text("x\n")
    rc, out = _main_output(
        ["trap_curate.py", str(worktree), "--copy-stray-from", str(clone)]
    )
    assert rc == 0
    assert "STRAY-NAMES: 1.stray.md" in out


def test_the_counter_and_the_curate_pass_report_the_same_number_on_one_fixture(
    clone, tmp_path
):
    """#1723's own literal ask: the count that decides a curate pass is due
    and what that pass actually evaluates, on one fixture with both a
    committed fragment and an untracked one, must agree -- the disagreement
    this issue was filed against."""
    env = _git_env()
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.committed.md").write_text("x\n")
    _run(["git", "add", "trap.d"], cwd=clone, env=env)
    _run(["git", "commit", "--quiet", "-m", "committed fragment"], cwd=clone, env=env)
    _run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=clone,
        env=env,
    )
    (clone / "trap.d" / "2.stray.md").write_text("y\n")  # untracked

    count, why = workspace_routes.curate_count(
        str(clone), config={"default_branch": "main"}
    )
    assert count == 2, why

    # the curate pass's own setup: a fresh worktree from origin/main sees
    # only the committed fragment until it copies the clone's strays in
    worktree = tmp_path / "curate-worktree"
    _run(
        ["git", "worktree", "add", str(worktree), "origin/main"],
        cwd=clone,
        env=env,
    )
    before = trap_curate.waiting(worktree)
    assert before["count"] == 1, before

    state, copied, skipped, copy_why = trap_curate.copy_stray_into(clone, worktree)
    assert state == "ok", copy_why
    assert not skipped

    after = trap_curate.waiting(worktree)
    assert after["count"] == count, (after, count, why)
