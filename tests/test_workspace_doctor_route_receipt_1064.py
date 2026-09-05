"""#1064 -- bin/oss-workspace's #764 doctor-route now carries a receipt (verdict
word + plugin version), so a WARN nothing can clear (#1062 is the worked example)
does not pin every future launch to /oss:doctor forever.

Unlike `tests/test_workspace_doctor_gate.py`, this drives the launcher against a
REAL `scripts/doctor.py`/`oss_config.py`/`oss_state.py`/`dispatch_rank.py` copied
into the fake plugin root -- the receipt logic imports those modules by name, and
`test_workspace_doctor_gate.py`'s own stub-only plugin root deliberately has none
of them, which is exactly the fixture asserting the launcher FAILS OPEN (routes,
as though no receipt exists) when those modules cannot be found; the existing
suite already covers that arm and stays green unmodified after this fix.

The diagnostic's own `VERDICT:` line still comes from a hand-written stub
`doctor.sh`, same as the sibling suite -- only the plugin version comparison
needs the real `doctor.py`.
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

import shell_probe  # noqa: E402

LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

_ATTEMPTS = shell_probe.attempts([LAUNCHER, Path(sys.executable)])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

GIT = shutil.which("git")

DOCTOR_MODE = 0o644

# Everything the receipt logic actually imports by name: doctor.py for
# `plugin_identity`, oss_config.py to resolve `state_file`, oss_state.py for the
# receipt itself, dispatch_rank.py because oss_state.py imports it
# unconditionally at module scope, and every `doctor_check_*.py` because
# doctor.py imports each of THOSE unconditionally too (the per-check module
# convention, #497/#630) -- omit even one and `import doctor` itself raises
# ModuleNotFoundError, which is a real state this suite tests separately
# (`real_modules=False`), not one to trip into by accident here.
_REAL_MODULES = ["doctor.py", "oss_config.py", "oss_state.py", "dispatch_rank.py"]
_REAL_MODULES += sorted(p.name for p in (REPO_ROOT / "scripts").glob("doctor_check_*.py"))


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
    return (
        "#!/bin/sh\n"
        + 'for a in "$@"; do echo "$a" >> "' + str(log) + '"; done\n'
        + body
        + "exit %d\n" % status
    )


def _plugin(tmp_path, doctor_body, real_modules=True):
    """A plugin root holding the launcher, a stub `scripts/doctor.sh` for the
    VERDICT text, and (unless `real_modules=False`) real copies of the modules
    the receipt logic imports.
    """
    root = tmp_path / "_plugin"
    (root / "bin").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(str(LAUNCHER), str(root / "bin" / "oss-workspace"))
    log = tmp_path / "doctor_argv.txt"
    path = root / "scripts" / "doctor.sh"
    path.write_text(_doctor(log, doctor_body), encoding="utf-8")
    path.chmod(DOCTOR_MODE)
    if real_modules:
        for name in _REAL_MODULES:
            shutil.copy2(str(REPO_ROOT / "scripts" / name), str(root / "scripts" / name))
    return root, log


def _repo(tmp_path):
    _require_git()
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".oss.json").write_text('{"repo": "owner/name"}', encoding="utf-8")
    return tmp_path


def run(repo, plugin_root, env_extra=None):
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


_WARN_BODY = "echo 'WARN one thing'\necho 'VERDICT: usable with gaps -- 1 warning(s)'\n"


def test_first_launch_still_routes_and_records_a_receipt(tmp_path):
    """MUST FIRE: nothing was recorded yet, so the very first launch in this
    state routes exactly as #764 always did -- the receipt is additive, not a
    new way to suppress the very first WARN anybody sees."""
    root, _ = _plugin(tmp_path, _WARN_BODY)
    done, argv = run(_repo(tmp_path / "repo"), root)
    assert argv, done.stderr
    assert "/oss:doctor" in argv, argv
    assert "no-receipt" in done.stderr, done.stderr
    state_file = tmp_path / "repo" / ".max" / "name-watch.json"
    assert state_file.exists(), done.stderr
    assert "doctor_route_verdict" in state_file.read_text(encoding="utf-8")


def test_a_second_launch_in_the_identical_state_does_not_route_again(tmp_path):
    """The issue's own worked example: a WARN nothing can clear (#1062) must
    not repin every subsequent launch once the maintainer has already seen
    it once on this exact plugin version."""
    root, _ = _plugin(tmp_path, _WARN_BODY)
    repo = _repo(tmp_path / "repo")
    first, _ = run(repo, root)
    assert "no-receipt" in first.stderr, first.stderr
    # `run()` appends to one shared argv log per repo -- cleared here so the
    # second call's own assertions see only what THIS launch passed, not the
    # first launch's `/oss:doctor` left sitting in the same file.
    (Path(repo).parent / "argv.txt").unlink(missing_ok=True)

    second, argv = run(repo, root)
    assert argv, second.stderr
    assert "/oss:doctor" not in argv, argv
    assert "/oss:tick" in argv, argv
    assert "unchanged" in second.stderr, second.stderr

    # Self-review finding: an `unchanged` launch already compares correctly
    # against the FIRST launch's own receipt, so it must not write a second
    # one -- growing this shared, un-rotated state file by one entry on
    # every launch, forever, for as long as an uncleared WARN persists.
    state_file = repo / ".max" / "name-watch.json"
    entries = json.loads(state_file.read_text(encoding="utf-8"))
    receipts = [e for e in entries if "doctor_route_verdict" in (e.get("detail") or {})]
    assert len(receipts) == 1, entries


def test_a_changed_verdict_re_arms_the_route(tmp_path):
    """MUST FIRE, positive control for the test above: the receipt gates on
    the PAIR, so a verdict that actually moved must still route even though a
    receipt already exists."""
    root, _ = _plugin(tmp_path, _WARN_BODY)
    repo = _repo(tmp_path / "repo")
    run(repo, root)
    (Path(repo).parent / "argv.txt").unlink(missing_ok=True)

    # A different stub verdict, written over the SAME plugin root's
    # doctor.sh -- reusing the same repo (and therefore the same state_file)
    # keeps the receipt comparison against the first launch's own entry.
    changed_body = (
        "echo 'WARN a different thing'\n"
        "echo 'VERDICT: usable with gaps -- 1 warning(s), a different one'\n"
    )
    doctor_sh = root / "scripts" / "doctor.sh"
    log2 = tmp_path / "doctor_argv2.txt"
    doctor_sh.write_text(_doctor(log2, changed_body), encoding="utf-8")
    doctor_sh.chmod(DOCTOR_MODE)
    second, argv = run(repo, root)
    assert argv, second.stderr
    assert "/oss:doctor" in argv, argv
    assert "changed" in second.stderr, second.stderr


def test_without_the_real_modules_the_route_fails_open(tmp_path):
    """MUST NOT FIRE the suppression at all when the receipt machinery cannot
    even be imported -- the same fail-open direction `test_workspace_doctor_
    gate.py`'s whole stub-only fixture already exercises for every OTHER test
    in this file's own sibling. Run twice: if this silently suppressed on the
    second launch it would mean the receipt got written anyway despite the
    import failure, which is not what 'fails open' is supposed to mean."""
    root, _ = _plugin(tmp_path, _WARN_BODY, real_modules=False)
    repo = _repo(tmp_path / "repo")
    first, argv1 = run(repo, root)
    assert "/oss:doctor" in argv1, argv1
    assert "could not be told" in first.stderr, first.stderr

    second, argv2 = run(repo, root)
    assert "/oss:doctor" in argv2, argv2
    assert "could not be told" in second.stderr, second.stderr
