"""#317: one call for the facts a developer lane brief hand-carries and that rot
before they are read -- the resolved base, the derived branch and worktree, and the
live worktree board -- instead of the maintainer retyping a snapshot taken minutes
earlier. `scripts/lane_setup.py` is the script; this file pins its three-state
behaviour.

Deliberately not tested here: the issue read itself. `supertool gh-issue:N:full`
already re-fetches live at call time and is not this script's job -- see the
module docstring in `scripts/lane_setup.py` for the granularity argument.

Every case that asserts a state resolved also has a sibling that asserts the sibling
state fires in the same fixture, one mutation away -- a script that always answers
"resolved" would pass half of this file.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    GIT is None, reason="git is not on PATH, so the fixtures below cannot be built"
)

CONFIG = {
    "repo": "example/example",
    "default_branch": "main",
    "clone": "/tmp/does-not-matter",
    "worktree_root": "/tmp/does-not-matter-wt",
    "branch_pattern": "fix/{issue}",
    "test_command": "pytest",
    "version_sites": [],
    "changelog_dir": None,
    "docs_targets": [],
    "labels": {"priority": [], "lanes": []},
    "state_file": "/tmp/does-not-matter-state.json",
}

OK = 0
COULD_NOT_RUN = 3


def _env():
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git(repo, *args):
    done = subprocess.run(
        [GIT, "-C", str(repo)] + list(args), capture_output=True, text=True, env=_env()
    )
    assert done.returncode == 0, "git {}: {}{}".format(args, done.stdout, done.stderr)
    return done.stdout.strip()


def _commit(repo, name, subject):
    (Path(repo) / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", subject)


def _origin(tmp_path):
    """A repo with one commit on `main`, meant to be cloned as `origin`."""
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "a.txt", "first")
    return repo


def _clone(origin, dest, config=None):
    """Clone `origin` to `dest`, which then carries an `origin` remote automatically,
    and write `.oss.json` there. `config` overrides merge onto CONFIG.
    """
    subprocess.run(
        [GIT, "clone", "-q", origin.as_uri(), str(dest)],
        capture_output=True,
        text=True,
        env=_env(),
        check=True,
    )
    _git(dest, "config", "user.email", "t@example.invalid")
    _git(dest, "config", "user.name", "T")
    merged = dict(CONFIG)
    merged.update(config or {})
    (dest / ".oss.json").write_text(json.dumps(merged), encoding="utf-8")
    return dest


def _run(repo, issue, *extra, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(issue), "--repo", str(repo), "--json"]
        + list(extra),
        capture_output=True,
        text=True,
        env=env if env is not None else _env(),
    )


def _payload(repo, issue, *extra, env=None):
    done = _run(repo, issue, *extra, env=env)
    assert done.stdout.strip(), "no JSON on stdout; stderr was: {}".format(done.stderr)
    return done.returncode, json.loads(done.stdout)


# ------------------------------------------------------------------ the script exists


def test_the_script_exists():
    assert SCRIPT.is_file(), "scripts/lane_setup.py is missing"


# --------------------------------------------------------------------------- config


def test_a_missing_oss_json_could_not_run(tmp_path):
    bare = tmp_path / "nothing"
    bare.mkdir()
    code, payload = _payload(bare, 317)
    assert payload["config"]["state"] == "could-not-run"
    assert code == COULD_NOT_RUN
    assert payload["base"] is None
    assert payload["board"] is None


def test_a_present_oss_json_runs(tmp_path):
    """Control for the case above: the same call, with a config, does not refuse."""
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    code, payload = _payload(repo, 317)
    assert payload["config"]["state"] == "ok"
    assert code == OK


# ----------------------------------------------------------------------------- base


def test_base_resolves_to_the_fetched_default_branch(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    # Move origin's main past the clone's initial fetch, so a stale local copy
    # cannot pass this by accident.
    _commit(origin, "b.txt", "second")
    want = _git(origin, "rev-parse", "main")

    code, payload = _payload(repo, 317)
    assert payload["base"]["state"] == "resolved"
    assert payload["base"]["sha"] == want
    assert len(payload["base"]["sha"]) == 40, "never abbreviated"
    assert code == OK


def test_base_could_not_resolve_when_there_is_nothing_to_fetch_and_no_local_ref(
    tmp_path,
):
    """No origin remote at all, and no prior fetch to fall back on."""
    bare = tmp_path / "lone"
    bare.mkdir()
    _git(bare, "init", "-q", "-b", "main")
    _commit(bare, "a.txt", "first")
    (bare / ".oss.json").write_text(json.dumps(CONFIG), encoding="utf-8")

    code, payload = _payload(bare, 317)
    assert payload["base"]["state"] == "could-not-resolve"
    assert code == COULD_NOT_RUN


def test_base_is_resolved_stale_when_fetch_fails_but_a_local_ref_answers(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    # A control fetch first, so a remote-tracking ref exists to fall back on.
    code, control = _payload(repo, 317)
    assert control["base"]["state"] == "resolved", "control: fetch succeeds normally"

    # Break the remote so the next fetch fails, without touching the ref already
    # fetched above -- that ref is exactly what "stale" is supposed to fall back on.
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist"))

    code, payload = _payload(repo, 317)
    assert payload["base"]["state"] == "resolved-stale"
    assert payload["base"]["detail"], "the staleness must say why, not just flag it"
    assert code == OK, "a stale-but-answered base does not block"


# --------------------------------------------------------------------------- branch


def test_branch_is_derived_from_the_pattern(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    code, payload = _payload(repo, 4242)
    assert payload["branch"]["state"] == "resolved"
    assert payload["branch"]["name"] == "fix/4242"


def test_branch_is_unknown_when_the_pattern_has_no_placeholder(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work", config={"branch_pattern": "fix"})
    code, payload = _payload(repo, 4242)
    assert payload["branch"]["state"] == "unknown"
    assert payload["branch"]["name"] is None
    assert code == OK, "an unresolvable branch does not by itself block the whole call"


def test_branch_occupancy_is_reported_both_ways(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")

    _, fresh = _payload(repo, 999)
    assert fresh["branch"]["exists_local"] is False, "must-not-fire control"

    _git(repo, "branch", "fix/999")
    _, taken = _payload(repo, 999)
    assert taken["branch"]["exists_local"] is True, (
        "must-fire: the branch is already there"
    )


# ------------------------------------------------------------------------- worktree


def test_worktree_is_derived_when_worktree_root_is_configured(tmp_path):
    origin = _origin(tmp_path)
    root = tmp_path / "wt-root"
    repo = _clone(origin, tmp_path / "work", config={"worktree_root": str(root)})
    code, payload = _payload(repo, 317)
    assert payload["worktree"]["state"] == "resolved"
    assert payload["worktree"]["path"] == str((root / "317").resolve())
    assert payload["worktree"]["exists"] is False


def test_worktree_is_unknown_without_worktree_root(tmp_path):
    """The absent-by-construction case: `.oss.local.json` never ships inside a
    worktree this loop cuts, so `worktree_root` is missing there by design.
    """
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work", config={"worktree_root": None})
    code, payload = _payload(repo, 317)
    assert payload["worktree"]["state"] == "unknown"
    assert payload["worktree"]["path"] is None
    assert payload["worktree"]["exists"] is None, "unknown must not render as False"


def test_worktree_exists_is_true_when_something_is_already_there(tmp_path):
    origin = _origin(tmp_path)
    root = tmp_path / "wt-root"
    root.mkdir()
    (root / "317").mkdir()
    repo = _clone(origin, tmp_path / "work", config={"worktree_root": str(root)})
    code, payload = _payload(repo, 317)
    assert payload["worktree"]["exists"] is True


def test_worktree_invalid_when_resolve_worktree_refuses(tmp_path, monkeypatch):
    """`derive_worktree` never re-derives containment itself -- it delegates to
    `oss_config.resolve_worktree`, whose own suite (`test_oss_config.py`) covers the
    symlink-escape fixture a real ContainmentError needs. This pins the wrapping: a
    refusal from that function must surface as `invalid`, path `None`, not raise.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import lane_setup  # noqa: E402
    import oss_config  # noqa: E402

    def _refuse(root, target):
        raise oss_config.ContainmentError(
            "worktree target {!r} escapes the root".format(target)
        )

    monkeypatch.setattr(oss_config, "resolve_worktree", _refuse)
    result = lane_setup.derive_worktree({"worktree_root": str(tmp_path)}, 317)
    assert result["state"] == "invalid"
    assert result["path"] is None
    assert "escapes" in result["detail"]


def test_worktree_bare_issue_number_never_escapes_the_root(tmp_path):
    """Control for the case above: the real function, the real root, an ordinary
    issue number -- containment holds and nothing is refused.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import lane_setup  # noqa: E402

    result = lane_setup.derive_worktree({"worktree_root": str(tmp_path)}, 317)
    assert result["state"] == "resolved"
    assert result["path"] == str((tmp_path / "317").resolve())


# ----------------------------------------------------------------------------- board


def _stub_supertool(tmp_path, text, exit_code=0):
    """A fake `supertool` on PATH that prints `text` and exits `exit_code`.

    Two files, not one: the board text goes in a sidecar `board.txt` and the launcher
    only ever does `cat`/`type` on it, so the launcher itself never has to embed
    arbitrary text in shell or batch syntax -- nothing here needs escaping.

    `shutil.which` resolves an extensionless `supertool` on POSIX, but on Windows it
    only probes names already carrying one of `PATHEXT`'s extensions (`.cmd`, `.exe`,
    ...) unless the bare name already ends in one -- a bare-name file is never found
    at all, which is a different and worse failure than "found but unspawnable"
    (CLAUDE.md's platform-audit checklist names both shapes separately). So the
    launcher is `supertool.cmd` on Windows and plain `supertool` elsewhere, each
    exercising the real `shutil.which` PATHEXT/executable-bit resolution rather than
    being skipped past it.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    board = bindir / "board.txt"
    board.write_text(text, encoding="utf-8")

    if os.name == "nt":
        stub = bindir / "supertool.cmd"
        stub.write_text(
            '@echo off\r\ntype "{0}"\r\nexit /b {1}\r\n'.format(board, exit_code),
            encoding="utf-8",
        )
    else:
        stub = bindir / "supertool"
        stub.write_text(
            '#!/bin/sh\ncat "{0}"\nexit {1}\n'.format(board, exit_code),
            encoding="utf-8",
        )
        stub.chmod(0o755)

    env = _env()
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    return env


def test_board_is_condensed_from_a_stubbed_supertool(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    fake_board = (
        "--- git-worktrees ---\n"
        "PASS (1.00s)\n"
        "# git-worktrees (1)\n"
        "[disclaimer line]\n"
        "\n"
        "occupied     main    /some/path  [merged, clean]  no open PR\n"
        "             . a bullet that must not survive condensing\n"
        "\n"
        "[exit 0] a long paragraph of static help text that must not survive either\n"
        "[result] 1 occupied, 0 idle, 0 cannot tell, 0 DIRTY\n"
    )
    env = _stub_supertool(tmp_path, fake_board)

    code, payload = _payload(repo, 317, env=env)
    assert payload["board"]["state"] == "ok"
    lines = payload["board"]["lines"]

    # Must-fire: the entry line and the result line survive.
    assert any(line.startswith("occupied") and "main" in line for line in lines)
    assert any(line.startswith("[result]") for line in lines)
    # Must-not-fire: the bullet and the static help paragraph do not.
    assert not any("bullet that must not survive" in line for line in lines)
    assert not any("static help text" in line for line in lines)
    assert not any(line.startswith("[exit") for line in lines)
    assert not any(line.startswith("PASS") for line in lines)


def test_board_is_could_not_run_on_a_nonzero_exit_even_when_the_op_name_is_echoed(
    tmp_path,
):
    """A real failure this plugin's own supertool produces: an unavailable-op error
    still echoes the op's own name in its message ("op 'git-worktrees' is
    unavailable here..."), so a substring check on stdout alone cannot tell that
    apart from a real board. The exit code is what actually distinguishes them --
    `git-worktrees` with no PATH argument always exits 0 on success.
    """
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    fake_error = (
        "--- git-worktrees ---\nERROR: op 'git-worktrees' is unavailable here\n"
    )
    env = _stub_supertool(tmp_path, fake_error, exit_code=1)

    code, payload = _payload(repo, 317, env=env)
    assert payload["board"]["state"] == "could-not-run"
    assert payload["board"]["lines"] == []
    assert code == OK, "a board failure does not by itself block the whole call"


def test_board_is_could_not_run_when_supertool_is_absent(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    env = _env()

    # A PATH with no supertool on it at all -- not merely "supertool failed". Any
    # extension (`.cmd`, `.exe`, ...) counts, since `shutil.which` on Windows would
    # find those too.
    def _has_supertool(directory):
        try:
            return any(p.stem == "supertool" for p in Path(directory).iterdir())
        except OSError:
            return False

    stripped = os.pathsep.join(
        p for p in env["PATH"].split(os.pathsep) if p and not _has_supertool(p)
    )
    env["PATH"] = stripped

    code, payload = _payload(repo, 317, env=env)
    assert payload["board"]["state"] == "could-not-run"
    assert payload["board"]["lines"] == []
    assert payload["board"]["detail"]
    assert code == OK, "a board that could not be read does not block the whole call"


def test_board_could_not_run_is_distinct_from_an_empty_board(tmp_path):
    """The two must not render alike: a stub that legitimately reports zero
    worktrees is `ok` with an empty-ish line set, never `could-not-run`.
    """
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    fake_board = (
        "# git-worktrees (0)\n[result] 0 occupied, 0 idle, 0 cannot tell, 0 DIRTY\n"
    )
    env = _stub_supertool(tmp_path, fake_board)

    code, payload = _payload(repo, 317, env=env)
    assert payload["board"]["state"] == "ok"
    assert any(line.startswith("[result]") for line in payload["board"]["lines"])


# ---------------------------------------------------------------------------- exit


def test_receipt_distinguishes_unknown_branch_occupancy_from_confirmed_free(tmp_path):
    """`branch_occupancy` can legitimately answer `None` (git could not be asked),
    and the receipt must not render that the same as a confirmed `False` -- the
    exact collapse this module exists to stop happening to a lane brief.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import lane_setup  # noqa: E402

    base_payload = {
        "remote": "origin",
        "state": "resolved",
        "ref": "origin/main",
        "sha": "a" * 40,
        "detail": "",
    }

    confirmed_free = dict(
        issue=317,
        repo=".",
        config={"state": "ok", "problems": []},
        base=base_payload,
        branch={
            "state": "resolved",
            "pattern": "fix/{issue}",
            "name": "fix/317",
            "exists_local": False,
            "exists_remote": False,
            "detail": "",
        },
        worktree={
            "state": "unknown",
            "root": None,
            "path": None,
            "detail": "",
            "exists": None,
        },
        board={"state": "ok", "lines": [], "detail": ""},
    )
    unknown = dict(confirmed_free)
    unknown["branch"] = dict(
        confirmed_free["branch"], exists_local=None, exists_remote=None
    )

    free_text = lane_setup.receipt(confirmed_free)
    unknown_text = lane_setup.receipt(unknown)

    assert "unknown" not in free_text.split("branch")[1].splitlines()[0]
    assert (
        "unknown" in [l for l in unknown_text.splitlines() if l.startswith("branch")][0]
    )
    assert free_text != unknown_text, (
        "a confirmed-free branch and an unknown one must not render alike"
    )


def test_receipt_mode_prints_text_not_json(tmp_path):
    origin = _origin(tmp_path)
    repo = _clone(origin, tmp_path / "work")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "317", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert done.returncode == OK
    assert "LANE SETUP #317" in done.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(done.stdout)
