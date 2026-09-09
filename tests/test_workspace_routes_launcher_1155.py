"""#1155 -- end-to-end coverage for `bin/oss-workspace`'s new threshold-route
block (the ~60-line addition right after the #764 doctor-route logic), driven
through the REAL launcher shell script the same way `tests/test_workspace_
doctor_route_receipt_1064.py` drives the doctor route: a fake plugin root
carrying real copies of every module the new block's own `scripts/
workspace_routes.py` imports, so the receipt/threshold logic is exercised for
real rather than stubbed.

A self-review finding on the first cut of #1155/#1096 (an `Explore` reviewer
spawn): `tests/test_workspace_routes_1155.py` thoroughly tests `scripts/
workspace_routes.py` in isolation (subprocess calls to the script directly),
but nothing drove `bin/oss-workspace` itself through the new case statement,
its `-gt 3` exit-code branch, or its composition with the doctor-route block
above it and the `$prompt = /oss:tick` gate. This file closes that gap, for
the two routes that need no network call (`curate`, `release`) -- `triage`
needs a real or stubbed `gh`, which is exactly what `bin/oss-workspace`'s own
`gh_which.safe_which` resolves at runtime; the doctor-route suite's own
fixture does not stub `gh` either, so this follows the same precedent rather
than inventing a new one.

The doctor route itself is kept quiet throughout (`VERDICT: ok`), so `$prompt`
stays `/oss:tick` going into the new block -- the one precondition the block's
own guard checks before running at all.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import import_closure  # noqa: E402
import launcher_env  # noqa: E402
import shell_probe  # noqa: E402

LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

_ATTEMPTS = shell_probe.attempts([LAUNCHER, Path(sys.executable)])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

GIT = shutil.which("git")

DOCTOR_MODE = 0o644

#: Everything `scripts/workspace_routes.py` imports, directly or (through
#: `oss_state.py` and, since #1237, the doctor route's own `import doctor`
#: pulled in by the same fixture) transitively -- derived by
#: `import_closure.py` rather than hand-listed, the identical mechanism the
#: doctor-route suite (`test_workspace_doctor_route_receipt_1064.py`, #1229
#: follow-up) already uses for the same reason: a hand-kept list is exactly
#: the gap that shipped once already there, and this file carried it
#: silently until #1237 found `doctor` -> `doctor_check_lane_patterns` ->
#: `lane_pattern_coverage` -> `select_issues_overlap` reaching modules this
#: list never named, so `import doctor` inside `bin/oss-workspace`'s own
#: doctor-route logic (which this fixture also exercises, quietly, ahead of
#: the new block under test) raised `ModuleNotFoundError` and the launcher
#: failed open with none of this file's five tests noticing. Omit a module
#: from the closure's reach and `import workspace_routes`, or `import
#: doctor`, raises `ModuleNotFoundError` inside the launcher's own
#: subprocess -- a real, separate state (`could not evaluate`), not one to
#: trip into by accident here.
_SEED_MODULES = [
    "doctor",
    "oss_config",
    "oss_state",
    "select_issues_rank",
    "gh_which",
    "workspace_routes",
    "trap_curate",
    "release_version",
    "release_delta",
]
_REACHED_MODULES_1326, _UNRESOLVED_IMPORTS_1326 = import_closure.local_import_closure(
    _SEED_MODULES, REPO_ROOT / "scripts"
)
_REAL_MODULES = sorted(name + ".py" for name in _REACHED_MODULES_1326)


def test_the_closure_seeded_here_has_nothing_unresolved():
    """#1326: `local_import_closure` can silently under-report the modules
    this launcher fixture needs -- a call it declined to follow (a
    non-literal `importlib.import_module(...)`/`__import__(...)` argument)
    used to render as the identical `[]` a line with no import call at all
    also renders. `scripts/borrowed_authority.py:224` is exactly this shape
    (`importlib.import_module(module_name)` on a variable) and, per #1236,
    is not reached by any of this fixture's own `_SEED_MODULES` today -- so
    this must stay empty for as long as that holds, and fail loudly, naming
    the site, the day a seed's own import graph starts reaching it, rather
    than silently copying an incomplete `_REAL_MODULES` into the fixture
    forever."""
    assert _UNRESOLVED_IMPORTS_1326 == [], (
        "local_import_closure found an import call it could not resolve "
        "while walking this fixture's own seeds -- _REAL_MODULES may be "
        "missing a transitively-reached module: " + repr(_UNRESOLVED_IMPORTS_1326)
    )


def _require_shell():
    if BASH is None:
        pytest.skip(SHELL_REPORT)


def _require_git():
    if GIT is None:
        pytest.skip(
            "no git on PATH, so no repository can be built to open a session over"
        )


def _executable(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


_OK_DOCTOR_BODY = "echo 'VERDICT: ok'\n"


def _doctor(log, body, status=0):
    return (
        "#!/bin/sh\n"
        + 'for a in "$@"; do echo "$a" >> "'
        + str(log)
        + '"; done\n'
        + body
        + "exit %d\n" % status
    )


def _plugin(tmp_path, doctor_body=_OK_DOCTOR_BODY, omit_module=None):
    """Build the fake plugin root. `omit_module` (a bare name, e.g.
    "select_issues_overlap") drops one module from the derived closure's own
    copy list -- the positive control for the `run()` assertion below: a
    fixture built with a module genuinely missing from the closure's reach
    must make `import doctor` (or `import workspace_routes`) fail loudly
    inside the launcher, proving the assertion can fire and is not a
    "must not fire" case with nothing pairing it (#1237 self-review)."""
    root = tmp_path / "_plugin"
    (root / "bin").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(str(LAUNCHER), str(root / "bin" / "oss-workspace"))
    log = tmp_path / "doctor_argv.txt"
    path = root / "scripts" / "doctor.sh"
    path.write_text(_doctor(log, doctor_body), encoding="utf-8")
    path.chmod(DOCTOR_MODE)
    for name in _REAL_MODULES:
        if omit_module is not None and name == omit_module + ".py":
            continue
        shutil.copy2(str(REPO_ROOT / "scripts" / name), str(root / "scripts" / name))
    return root


def _repo(tmp_path, config_extra=None):
    _require_git()
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
    config = {"repo": "owner/name", "changelog_dir": "changelog.d"}
    if config_extra:
        config.update(config_extra)
    (tmp_path / ".oss.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def run(repo, plugin_root):
    _require_shell()
    bindir = Path(repo).parent / "_stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = Path(repo).parent / "argv.txt"
    _executable(
        bindir / "claude",
        "#!/bin/sh\n"
        + 'if [ "${1:-}" = "mcp" ]; then exit 1; fi\n'
        + 'for a in "$@"; do echo "$a" >> "'
        + str(argv_log)
        + '"; done\n'
        + "exit 0\n",
    )
    home = Path(repo).parent / "_home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("SUPERTOOL_WATCH_NAME", None)
    env.pop("OSS_WORKSPACE_SKIP_DOCTOR", None)
    env["PATH"] = launcher_env.pinned_path(bindir)
    done = subprocess.run(
        [BASH, str(Path(plugin_root) / "bin" / "oss-workspace")],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    argv = (
        argv_log.read_text(encoding="utf-8").splitlines() if argv_log.exists() else []
    )
    # #1237: a module missing from `_SEED_MODULES`'s closure does not fail
    # any of this file's own assertions -- the launcher fails open and every
    # route falls back to `/oss:tick`, which is what "no threshold
    # configured" already asserts. So assert here, once, for every test that
    # calls `run()`: this fixture's own `import doctor` (the doctor-route
    # logic every one of these cases also exercises, ahead of the new block
    # under test) must never raise inside the launcher's subprocess.
    assert "ModuleNotFoundError" not in done.stderr, done.stderr
    return done, argv


def test_a_missing_transitive_module_makes_the_new_assertion_fire(tmp_path):
    """MUST FIRE -- the positive control for `run()`'s own `ModuleNotFoundError`
    assertion (#1237 self-review): with `select_issues_overlap.py` deliberately
    dropped from the fake plugin root's copy (a real transitive dependency of
    `doctor.py`, via `doctor_check_lane_patterns` -> `lane_pattern_coverage`),
    the launcher's own `import doctor` must raise inside its subprocess, and
    `run()`'s assertion must catch it rather than let a broken fixture pass
    silently the way this file's fixture did before #1237."""
    root = _plugin(tmp_path, omit_module="select_issues_overlap")
    repo = _repo(tmp_path / "repo")
    with pytest.raises(AssertionError, match="ModuleNotFoundError"):
        run(repo, root)


def test_no_threshold_configured_opens_the_ordinary_tick(tmp_path):
    """MUST NOT FIRE: with no `*_route_threshold` key set at all, the new
    block must leave `$prompt` exactly as the two routes above it left it."""
    root = _plugin(tmp_path)
    repo = _repo(tmp_path / "repo")
    done, argv = run(repo, root)
    assert argv, done.stderr
    assert "/oss:tick" in argv, argv
    assert "ROUTE: none" in done.stderr, done.stderr


def test_curate_route_fires_through_the_real_launcher(tmp_path):
    """MUST FIRE: `trap.d/` over threshold routes the whole launcher into
    `/oss:curate`, driven through the actual shell block rather than the
    python module alone."""
    root = _plugin(tmp_path)
    repo = _repo(tmp_path / "repo", {"curate_route_threshold": 1})
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    (repo / "trap.d" / "2.b.md").write_text("x\n")

    done, argv = run(repo, root)

    assert argv, done.stderr
    assert "/oss:curate" in argv, argv
    assert "/oss:tick" not in argv, argv
    assert "ROUTE: curate" in done.stderr, done.stderr


def test_release_route_takes_precedence_over_curate_through_the_launcher(tmp_path):
    """MUST FIRE, and prove precedence end to end: both `curate` and
    `release` are over threshold, and the real launcher must still open
    `/oss:release` -- not whichever the shell `case` happened to test
    first, and not `/oss:curate`."""
    root = _plugin(tmp_path)
    repo = _repo(
        tmp_path / "repo",
        {"curate_route_threshold": 1, "release_route_threshold": 1},
    )
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    (repo / "trap.d" / "2.b.md").write_text("x\n")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "1.fixed.md").write_text("- x\n")
    (repo / "changelog.d" / "2.added.md").write_text("- x\n")

    done, argv = run(repo, root)

    assert argv, done.stderr
    assert "/oss:release" in argv, argv
    assert "/oss:curate" not in argv, argv
    assert "ROUTE: release" in done.stderr, done.stderr


def test_a_warn_from_the_doctor_route_takes_precedence_over_this_block(tmp_path):
    """MUST NOT FIRE: the new block's own guard is `$prompt = /oss:tick`.
    When the doctor route above it has already moved `$prompt` to
    `/oss:doctor` (a real WARN), this block must leave that alone even
    though a threshold route is also over."""
    root = _plugin(
        tmp_path,
        "echo 'WARN one thing'\necho 'VERDICT: usable with gaps -- 1 warning(s)'\n",
    )
    repo = _repo(tmp_path / "repo", {"curate_route_threshold": 1})
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    (repo / "trap.d" / "2.b.md").write_text("x\n")

    done, argv = run(repo, root)

    assert argv, done.stderr
    assert "/oss:doctor" in argv, argv
    assert "/oss:curate" not in argv, argv


def test_the_receipt_suppresses_a_repeat_route_through_the_launcher(tmp_path):
    """MUST FIRE the first time, MUST NOT the second: the same #1064-shaped
    receipt the doctor route already gets, now proven for this block too,
    end to end rather than only inside `workspace_routes.py`'s own CLI
    tests."""
    root = _plugin(tmp_path)
    repo = _repo(tmp_path / "repo", {"curate_route_threshold": 1})
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    (repo / "trap.d" / "2.b.md").write_text("x\n")

    first, argv1 = run(repo, root)
    assert "/oss:curate" in argv1, argv1
    (Path(repo).parent / "argv.txt").unlink(missing_ok=True)

    second, argv2 = run(repo, root)
    assert "/oss:curate" not in argv2, argv2
    assert "/oss:tick" in argv2, argv2
    assert "unchanged" in second.stderr, second.stderr

    # Positive control: one more fragment moves the count, so the route
    # must re-arm rather than staying suppressed forever.
    (repo / "trap.d" / "3.c.md").write_text("x\n")
    (Path(repo).parent / "argv.txt").unlink(missing_ok=True)
    third, argv3 = run(repo, root)
    assert "/oss:curate" in argv3, argv3
