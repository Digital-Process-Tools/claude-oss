"""#1350: nothing in the loop could tell a lane branch held by a live sibling
scheduler from one abandoned by a dead session -- see
`scripts/doctor_check_scheduler_processes.py`'s own docstring for the incident
(two live `claude /oss:tick` processes sharing one clone, one running two
days, a green unmerged PR invisible to a third tick's board read).

This is the doctor-line test for `check_scheduler_processes`, the same shape
`test_doctor_check_vanished_worktree_845.py` uses for its own sibling check:
the count only reaches a maintainer through `doctor` and nowhere else that
runs unprompted, so the line is the whole forcing function and is tested
directly rather than assumed.
"""

import contextlib
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor_check_scheduler_processes as dcsp  # noqa: E402


def _doctor_line(project_dir, config, run=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dcsp.check_scheduler_processes(str(project_dir), config, run=run)
    return buf.getvalue().strip()


class _FakeDone(object):
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_which_factory(available):
    def _fake_which(name, path=None):
        return "/usr/bin/{}".format(name) if name in available else None

    return _fake_which


def _ps_lines(*procs):
    header = "  PID COMMAND\n"
    rows = "".join("{} {}\n".format(pid, cmd) for pid, cmd in procs)
    return header + rows


# --- ps unavailable: could-not-tell, never rendered as clean -----------------


def test_ps_unavailable_is_warn_not_ok(tmp_path, monkeypatch):
    """No `ps` on PATH (Windows) must never render as OK -- that would be the
    absence-produced-by-the-tool defect this repo is named after: a check that
    never ran and a check that found nothing must not look identical."""
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({}))
    line = _doctor_line(tmp_path, {"clone": str(tmp_path)})
    assert line.startswith("WARN "), line
    assert "could not" in line.lower()


def test_ps_spawn_failure_is_warn_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))

    def _run(*args, **kwargs):
        raise OSError("ps vanished mid-call")

    line = _doctor_line(tmp_path, {"clone": str(tmp_path)}, run=_run)
    assert line.startswith("WARN "), line
    assert "could not" in line.lower()


# --- the positive control: no matching processes is a real OK ----------------


def test_no_matching_processes_is_ok(tmp_path, monkeypatch):
    """Paired with the WARN cases above: an empty, well-formed `ps` result
    really is clean and must render OK, not silently fold into 'could not
    tell'. This is the fire case for the two must-not-fire cases above."""
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))

    def _run(*args, **kwargs):
        return _FakeDone(0, stdout=_ps_lines((123, "sshd"), (456, "bash")))

    line = _doctor_line(tmp_path, {"clone": str(tmp_path)}, run=_run)
    assert line.startswith("OK "), line


# --- one matching process, resolvable to this clone: OK ----------------------


def test_one_matching_process_against_this_clone_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))
    monkeypatch.setattr(dcsp, "_process_cwd", lambda pid, run: str(tmp_path))

    def _run(*args, **kwargs):
        return _FakeDone(0, stdout=_ps_lines((999, "claude /oss:tick --foo")))

    line = _doctor_line(tmp_path, {"clone": str(tmp_path)}, run=_run)
    assert line.startswith("OK "), line
    assert "1" in line


# --- several matching processes against this clone: WARN, names #1350 -------


def test_several_matching_processes_against_this_clone_is_warn(tmp_path, monkeypatch):
    """The #1350 shape itself: two sibling schedulers sharing one clone."""
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))
    monkeypatch.setattr(dcsp, "_process_cwd", lambda pid, run: str(tmp_path))

    def _run(*args, **kwargs):
        return _FakeDone(
            0,
            stdout=_ps_lines(
                (111, "claude /oss:tick --foo"),
                (222, "claude /oss:tick --bar"),
            ),
        )

    line = _doctor_line(tmp_path, {"clone": str(tmp_path)}, run=_run)
    assert line.startswith("WARN "), line
    assert "2" in line
    assert "#1350" in line


# --- a matching process elsewhere on the machine is not counted here --------


def test_matching_process_against_a_different_clone_is_not_counted(
    tmp_path, monkeypatch
):
    other = tmp_path / "other-clone"
    other.mkdir()
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))
    monkeypatch.setattr(dcsp, "_process_cwd", lambda pid, run: str(other))

    def _run(*args, **kwargs):
        return _FakeDone(0, stdout=_ps_lines((333, "claude /oss:tick --elsewhere")))

    line = _doctor_line(tmp_path, {"clone": str(tmp_path)}, run=_run)
    assert line.startswith("OK "), line


# --- cwd cannot be resolved for any candidate: could-not-tell ----------------


def test_unresolvable_cwd_is_warn_could_not_tell_not_ok(tmp_path, monkeypatch):
    """A candidate process was found but this platform/permission set cannot
    attribute it to a clone -- must not silently render as clean (OK)."""
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))
    monkeypatch.setattr(dcsp, "_process_cwd", lambda pid, run: None)

    def _run(*args, **kwargs):
        return _FakeDone(0, stdout=_ps_lines((444, "claude /oss:tick --unknown")))

    line = _doctor_line(tmp_path, {"clone": str(tmp_path)}, run=_run)
    assert line.startswith("WARN "), line
    assert "could not" in line.lower()


# --- state function's own three states ---------------------------------------


def test_state_function_returns_three_states(tmp_path, monkeypatch):
    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({}))
    state, _detail = dcsp.scheduler_process_state(str(tmp_path))
    assert state == "could-not-tell"

    monkeypatch.setattr(dcsp.gh_which, "safe_which", _fake_which_factory({"ps"}))
    monkeypatch.setattr(dcsp, "_process_cwd", lambda pid, run: str(tmp_path))

    def _run(*args, **kwargs):
        return _FakeDone(0, stdout=_ps_lines((5, "claude /oss:tick")))

    state, detail = dcsp.scheduler_process_state(str(tmp_path), run=_run)
    assert state == "counted"
    assert detail["count"] == 1
