"""`bin/oss-workspace` runs the setup diagnostic before it opens the session (#269).

`scripts/doctor.py` **exits 0 always, by contract**, and puts its whole answer in one
`VERDICT:` line. So the obvious launcher check --

    doctor.sh || warn "setup is broken"

-- is a check that can never fire: it reads a pass on `VERDICT: not usable -- 4
failure(s)` exactly as loudly as on `VERDICT: ok`. Every test here therefore drives a
**stub** diagnostic that is MADE to produce one state, and asserts the launcher told
those states apart. A stub is the only fixture that can produce `could not run` on
demand, and that state matters more than `ok`: a check that never fired and a check
that found nothing print the same thing.

Two things the launcher must do in every one of them, asserted in every test rather
than once: **open the session anyway** -- a maintainer whose config is broken is
exactly the person who needs a session in which to fix it -- and never let one state
render as another.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# Stated rather than inherited: pytest's default import mode puts this directory on
# sys.path as a side effect, and that stops under `--import-mode=importlib`.
sys.path.insert(0, str(REPO_ROOT / "tests"))

import shell_probe  # noqa: E402

LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

# Measured, not named: `shutil.which("bash")` answers with whatever is called bash
# first, and on a Windows runner that is regularly WSL's bash.exe, which has never
# heard of the paths this suite is about to hand it.
_ATTEMPTS = shell_probe.attempts([LAUNCHER, Path(sys.executable)])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

GIT = shutil.which("git")


def _require_shell():
    if BASH is None:
        pytest.skip(SHELL_REPORT)


def _require_git():
    if GIT is None:
        pytest.skip("no git on PATH, so no repository can be built to open a session over")


def _executable(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _doctor(log, body, status=0):
    """A `doctor.sh` that records its argv and then produces exactly one state.

    The argv log is what proves the launcher passed `--root`: a diagnostic invoked
    with neither `--root` nor `CLAUDE_PROJECT_DIR` prints `WARN project dir guessed
    from cwd` and downgrades an otherwise-`ok` tree, which is a warning manufactured
    by the invocation rather than a fact about the repository.
    """
    return (
        "#!/bin/sh\n"
        + 'for a in "$@"; do echo "$a" >> "' + str(log) + '"; done\n'
        + body
        + "exit %d\n" % status
    )


# `scripts/doctor.sh` is tracked mode 644 -- `git ls-files -s` says `100644` -- so
# its `#!` line is never used and every caller in this plugin invokes it as
# `bash <path>`. The stub is planted at the same mode rather than made executable,
# because a fixture that carries the bit is green against a launcher that execs the
# file directly, and the real tree is not. That is exactly how the first cut of this
# fix passed its own suite and reported COULD NOT BE STARTED on every real launch.
DOCTOR_MODE = 0o644


def _plugin(tmp_path, doctor_body=None, doctor_status=0):
    """A plugin root holding a copy of the launcher and a stub diagnostic.

    `doctor_body=None` plants no `scripts/doctor.sh` at all, which is a different
    state from one that runs and says nothing -- the launcher has to name which.
    """
    root = tmp_path / "_plugin"
    (root / "bin").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(str(LAUNCHER), str(root / "bin" / "oss-workspace"))
    log = tmp_path / "doctor_argv.txt"
    if doctor_body is not None:
        path = root / "scripts" / "doctor.sh"
        path.write_text(_doctor(log, doctor_body, doctor_status), encoding="utf-8")
        path.chmod(DOCTOR_MODE)
    return root, log


def _repo(tmp_path, with_config=True):
    _require_git()
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
    if with_config:
        (tmp_path / ".oss.json").write_text('{"repo": "owner/name"}', encoding="utf-8")
    return tmp_path


def run(repo, plugin_root, env_extra=None):
    """Spawn the launcher with a stub `claude` and a pinned PATH.

    PATH is pinned rather than inherited because with the real `claude` reachable a
    launcher test once FOUND it and executed it -- a suite starting live agent
    sessions in temp directories.
    """
    _require_shell()
    bindir = Path(repo).parent / "_stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = Path(repo).parent / "argv.txt"
    _executable(
        bindir / "claude",
        "#!/bin/sh\n"
        + 'if [ "${1:-}" = "mcp" ]; then exit 1; fi\n'
        + 'for a in "$@"; do echo "$a" >> "' + str(argv_log) + '"; done\n'
        + "exit 0\n",
    )
    home = Path(repo).parent / "_home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("SUPERTOOL_WATCH_NAME", None)
    # Popped rather than left alone: a developer with the skip flag exported would
    # otherwise turn every assertion in this file green without the launcher running
    # a single diagnostic.
    env.pop("OSS_WORKSPACE_SKIP_DOCTOR", None)
    env["PATH"] = os.pathsep.join(
        [str(bindir), str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    )
    if env_extra:
        env.update(env_extra)
    done = subprocess.run(
        [BASH, str(Path(plugin_root) / "bin" / "oss-workspace")],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    argv = argv_log.read_text(encoding="utf-8").splitlines() if argv_log.exists() else []
    return done, argv


def _doctor_argv(log):
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


# --- the diagnostic is run at all, and told where ------------------------------


def test_the_diagnostic_runs_before_the_session_opens(tmp_path):
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert _doctor_argv(log), done.stderr
    assert argv, done.stderr


def test_the_run_is_announced_before_it_starts_with_the_way_out(tmp_path):
    """The diagnostic reaches the network -- 25s per declared dependency, 20s per
    probed binary -- so offline it can turn a 0.4s launch into a minute-long stare at
    nothing. The escape hatch is useless if it is only discoverable from a line that
    prints after the wait, so the notice goes out BEFORE the run and carries the
    variable's name.
    """
    root, _ = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "running the setup diagnostic" in done.stderr, done.stderr
    assert "OSS_WORKSPACE_SKIP_DOCTOR" in done.stderr, done.stderr
    # Ordering is the whole claim: a notice printed after the verdict is a notice
    # nobody waiting ever saw.
    assert done.stderr.index("running the setup diagnostic") < done.stderr.index(
        "VERDICT: ok"
    ), done.stderr


def test_the_announcement_is_not_printed_when_nothing_is_run(tmp_path):
    """The must-not-fire half. A notice that prints unconditionally would say a
    diagnostic is running in the one case where none is.
    """
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(
        _repo(tmp_path / "repo"), root, env_extra={"OSS_WORKSPACE_SKIP_DOCTOR": "1"}
    )
    assert argv, done.stderr
    assert _doctor_argv(log) == []
    assert "running the setup diagnostic" not in done.stderr, done.stderr


def test_the_resolved_root_is_passed_so_no_warning_is_manufactured(tmp_path):
    """Invoked with neither `--root` nor `CLAUDE_PROJECT_DIR` the diagnostic used to
    print `WARN project dir guessed from cwd` and downgrade an otherwise-`ok` tree to
    `usable with gaps -- 1 warning(s)`; #756 moved that line to OK, since guessing
    from cwd is the documented default invocation rather than a failed measurement.
    This test uses a stub diagnostic rather than the real one, so its own assertions
    do not depend on that change -- but the launcher's whole point still holds:
    the root is resolved once, here, and passed explicitly, so nothing about the
    diagnostic's own invocation is left to guess at.
    """
    repo = _repo(tmp_path / "repo")
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, _ = run(repo, root)
    passed = _doctor_argv(log)
    assert "--root" in passed, done.stderr
    assert Path(passed[passed.index("--root") + 1]).resolve() == Path(repo).resolve(), passed


# --- the four verdicts, each told apart ----------------------------------------


def test_ok_is_a_verdict_and_not_the_whole_report(tmp_path):
    """The must-not-fire half. A healthy launch costs the pre-run notice and the
    verdict, and nothing else: furniture on every launch is how the line that matters
    stops being read, while silence would make "ran and was clean" indistinguishable
    from "never ran". The diagnostic's own OK lines stay behind /oss:doctor.
    """
    root, _ = _plugin(tmp_path, "echo 'OK everything'\necho 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "VERDICT: ok" in done.stderr
    assert "UNKNOWN" not in done.stderr, done.stderr
    assert "OK everything" not in done.stderr, done.stderr


def test_warnings_are_reported_whole_and_the_session_still_opens(tmp_path):
    """A warning is not a pass, and it is also not a reason to refuse."""
    body = (
        "echo 'WARN one thing'\n"
        "echo 'WARN another thing'\n"
        "echo 'VERDICT: usable with gaps -- 2 warning(s)'\n"
    )
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "usable with gaps -- 2 warning(s)" in done.stderr
    # Relayed whole rather than summarised to its verdict: once the answer is not
    # `ok`, the launcher has no standing to decide which of the diagnostic's lines
    # the maintainer needed to see.
    assert "WARN one thing" in done.stderr
    assert "WARN another thing" in done.stderr


def test_failures_are_reported_and_the_session_still_opens(tmp_path):
    """The judgement call, pinned. A maintainer whose config is broken is exactly the
    person who needs a session in which to fix it; a launcher that refuses to open
    leaves them with no tool.
    """
    body = (
        "echo 'FAIL clone path does not exist'\n"
        "echo 'VERDICT: not usable -- 1 failure(s), 0 warning(s)'\n"
    )
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert done.returncode == 0, done.stderr
    assert "not usable -- 1 failure(s)" in done.stderr
    assert "FAIL clone path does not exist" in done.stderr


def test_could_not_run_is_not_a_pass(tmp_path):
    """The diagnostic's own third state. It exits 0 while saying it never looked, so
    anything branching on the status reads this as healthy.
    """
    body = "echo 'FAIL no working Python found'\necho 'VERDICT: could not run'\n"
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "could not run" in done.stderr
    assert "UNKNOWN" in done.stderr, done.stderr


# --- and the states the diagnostic cannot report about itself ------------------


def test_no_verdict_line_at_all_is_its_own_state(tmp_path):
    """It started, it exited 0, and it never reached its own report. An empty grep for
    `VERDICT:` is identical here and on a clean run, which is the whole defect class.
    """
    root, _ = _plugin(tmp_path, "echo 'OK something'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "no VERDICT line" in done.stderr, done.stderr
    assert "UNKNOWN" in done.stderr, done.stderr
    assert "VERDICT: ok" not in done.stderr, done.stderr


def test_a_verdict_line_makes_the_same_stub_read_as_ok(tmp_path):
    """The positive control for the test above: identical fixture, one line added.
    Without it, "no VERDICT line" would also pass against a launcher whose parser
    never matched anything at all.
    """
    root, _ = _plugin(tmp_path, "echo 'OK something'\necho 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "no VERDICT line" not in done.stderr, done.stderr
    assert "VERDICT: ok" in done.stderr, done.stderr


def test_a_diagnostic_that_died_is_not_a_diagnostic_that_was_quiet(tmp_path):
    """`doctor.sh` exits 0 always, by contract. A non-zero status therefore says it
    could not be started or died on the way, which is a different sentence from "it
    ran and printed nothing" -- and the launcher can tell them apart, so it must.
    """
    root, _ = _plugin(
        tmp_path, "echo 'Traceback (most recent call last):' >&2\n", doctor_status=3
    )
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "COULD NOT BE STARTED" in done.stderr, done.stderr
    assert "exited 3" in done.stderr, done.stderr
    assert "Traceback" in done.stderr, done.stderr
    assert "no VERDICT line" not in done.stderr, done.stderr


def test_a_missing_diagnostic_says_missing_rather_than_quiet(tmp_path):
    root, log = _plugin(tmp_path, doctor_body=None)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert _doctor_argv(log) == []
    assert "was not found" in done.stderr, done.stderr
    assert "UNKNOWN" in done.stderr, done.stderr


def test_a_diagnostic_with_no_executable_bit_is_still_run(tmp_path):
    """`scripts/doctor.sh` is tracked mode **644** -- `git ls-files -s` says 100644 --
    so its `#!` line is never used and `"$doctor_sh"` dies with `Permission denied`.
    Every other caller in this plugin invokes it as `bash <path>`; `commands/doctor.md`
    does exactly that.

    The first cut of this fix executed it directly. It was green against a fixture
    whose stub carried the bit, and against the real tree it reported
    `COULD NOT BE STARTED` on every launch -- a diagnostic that never ran, wearing
    the third state's clothes. So the mode is the fixture: the stub here is written
    0o644 on purpose, and a launcher that needs the bit fails this test.
    """
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    stub = root / "scripts" / "doctor.sh"
    # A mode fixture is a measurement, not a given. Windows has no execute bit and
    # `os.access(X_OK)` answers True for any existing file there, so the arm this
    # test is about cannot be distinguished on that platform -- it skips loudly with
    # what went untested rather than asserting a POSIX fact as a product verdict.
    if os.access(str(stub), os.X_OK):
        pytest.skip(
            "%s is executable despite mode %o, so this platform cannot tell running "
            "it directly from running it under bash; the launcher's dependence on "
            "the execute bit went untested here" % (stub, DOCTOR_MODE)
        )
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert _doctor_argv(log) != [], done.stderr
    assert "VERDICT: ok" in done.stderr, done.stderr
    assert "COULD NOT BE STARTED" not in done.stderr, done.stderr


def test_an_unrecognised_verdict_does_not_read_as_ok(tmp_path):
    """A verdict word this launcher has never heard of is a state of its own, not a
    pass. If `doctor.py` grows one, the launcher says it does not know what it means
    rather than falling through the `case` in silence.
    """
    root, _ = _plugin(tmp_path, "echo 'VERDICT: gloriously fine'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "gloriously fine" in done.stderr, done.stderr
    assert "UNKNOWN" in done.stderr, done.stderr


def test_the_last_verdict_line_wins(tmp_path):
    """`doctor.py` flattens its findings so an issue title cannot forge one, and its
    contract is one VERDICT line, LAST. Reading the first match would hand the verdict
    to whatever printed earliest.
    """
    body = (
        "echo 'VERDICT: ok'\n"
        "echo 'FAIL a real finding'\n"
        "echo 'VERDICT: not usable -- 1 failure(s), 0 warning(s)'\n"
    )
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "not usable -- 1 failure(s)" in done.stderr, done.stderr


# --- the escape hatch, and its third state -------------------------------------


def test_the_diagnostic_can_be_skipped_and_the_skip_is_announced(tmp_path):
    """The diagnostic costs seconds and touches the network, so it has an off switch.
    A skipped check that says nothing is a check that reads as clean, so the skip is
    stated: this session opens WITHOUT knowing whether the repo is configured, which
    is not the same as knowing that it is.
    """
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(
        _repo(tmp_path / "repo"), root, env_extra={"OSS_WORKSPACE_SKIP_DOCTOR": "1"}
    )
    assert argv, done.stderr
    assert _doctor_argv(log) == [], "the diagnostic ran despite the skip flag"
    assert "OSS_WORKSPACE_SKIP_DOCTOR" in done.stderr, done.stderr
    assert "UNKNOWN" in done.stderr, done.stderr


def test_without_the_flag_the_diagnostic_runs(tmp_path):
    """The must-fire half of the pair above. Asserting only that the flag suppresses
    the run would pass against a launcher that never ran the diagnostic at all.
    """
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert _doctor_argv(log) != [], done.stderr


def test_a_repo_with_no_config_is_still_diagnosed(tmp_path):
    """The session that most needs the answer is the one going to `/oss:setup`."""
    root, log = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo", with_config=False), root)
    assert "/oss:setup" in argv, done.stderr
    assert _doctor_argv(log) != [], done.stderr


# --- #764: a real WARN routes the session into /oss:doctor at its first turn --


def test_a_real_warning_routes_the_session_into_oss_doctor(tmp_path):
    """The must-fire half. `usable with gaps` carries at least one real WARN --
    NOTICE-only runs read `VERDICT: ok` by doctor.py's own arithmetic and never
    reach this arm -- so this is exactly the case #764 says an auto-route is
    readable for."""
    body = (
        "echo 'WARN one thing'\n"
        "echo 'VERDICT: usable with gaps -- 1 warning(s)'\n"
    )
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:doctor" in argv, argv
    assert "/oss:tick" not in argv, argv
    assert "routing this session into /oss:doctor" in done.stderr, done.stderr


def test_a_clean_run_does_not_route_and_keeps_its_own_prompt(tmp_path):
    """The must-not-fire half, in the same fixture family as the test above. A
    NOTICE-only (or genuinely clean) run reads `VERDICT: ok` and opens with
    whatever prompt this launcher already chose -- never routed, never
    silently overridden."""
    root, _ = _plugin(tmp_path, "echo 'VERDICT: ok'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:tick" in argv, argv
    assert "/oss:doctor" not in argv, argv
    assert "routing this session into /oss:doctor" not in done.stderr, done.stderr


def test_a_failure_verdict_also_routes(tmp_path):
    """`not usable` carries at least one FAIL, which is at least as actionable as
    a WARN -- the route must not be gated on `usable with gaps` alone."""
    body = (
        "echo 'FAIL clone path does not exist'\n"
        "echo 'VERDICT: not usable -- 1 failure(s), 0 warning(s)'\n"
    )
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:doctor" in argv, argv


def test_could_not_run_neither_routes_nor_silently_skips(tmp_path):
    """The third state for the route itself (#764): a diagnostic that ran and
    said it could not look must not be routed as though it found a real
    problem, and must not be silently treated as clean either -- both are said
    out loud rather than assumed."""
    body = "echo 'FAIL no working Python found'\necho 'VERDICT: could not run'\n"
    root, _ = _plugin(tmp_path, body)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:doctor" not in argv, argv
    assert "could not be decided either" in done.stderr, done.stderr


def test_a_diagnostic_that_never_started_does_not_route(tmp_path):
    """Same third state, reached through the COULD NOT BE STARTED arm rather
    than through the diagnostic's own `could not run` verdict."""
    root, _ = _plugin(
        tmp_path, "echo 'Traceback (most recent call last):' >&2\n", doctor_status=3
    )
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:doctor" not in argv, argv
    assert "could not be decided either" in done.stderr, done.stderr


def test_no_verdict_line_does_not_route(tmp_path):
    """Same third state again: exited 0, printed nothing this launcher could
    parse as a verdict. Not a clean run, so it must not be routed as one, and
    it carries no WARN this launcher could gate a route on either."""
    root, _ = _plugin(tmp_path, "echo 'OK something'\n")
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:doctor" not in argv, argv
    assert "could not be decided either" in done.stderr, done.stderr
