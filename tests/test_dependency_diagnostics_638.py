"""#638: `/oss:doctor` reports presence and a version per declared dependency
and never relays whether that dependency is actually WORKING -- and every
declared dependency ships a diagnostic of its own that answers exactly that.
Three shapes exist today: `supertool` ships an OP, `remember` and
`claude-jit-context` each ship a versioned SCRIPT under their own install
root. This relays each dependency's own verdict rather than reimplementing
it, in three states -- `relayed` / `not-installed` / `could-not-run` -- and
`could-not-run` must never render as a pass.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


class _FakeCompleted:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _run_answering(text, returncode=0):
    def run(cmd, **kwargs):
        return _FakeCompleted(returncode, text)

    return run


def _run_raising(exc):
    def run(cmd, **kwargs):
        raise exc

    return run


def _install_record(tmp_path, entries):
    """A minimal `installed_plugins.json`, shaped like the real one:
    `{"plugins": {"<name>@<marketplace>": [{"version": ..., "installPath": ...}]}}`.
    """
    record = tmp_path / "installed_plugins.json"
    plugins = {}
    for name, version, install_path in entries:
        plugins.setdefault("{}@dpt-plugins".format(name), []).append(
            {"version": version, "installPath": str(install_path)}
        )
    record.write_text(json.dumps({"plugins": plugins}), encoding="utf-8")
    return record


# --- not-installed: the ordinary state, no active version at all -------------


def test_not_installed_is_the_ordinary_state_for_an_op_shaped_dependency(tmp_path):
    empty_record = tmp_path / "installed_plugins.json"
    empty_record.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    state, detail = doctor.dependency_diagnostic_state(
        "supertool", tmp_path, record=empty_record
    )
    assert state == "not-installed", (state, detail)


def test_not_installed_is_the_ordinary_state_for_a_script_shaped_dependency(tmp_path):
    empty_record = tmp_path / "installed_plugins.json"
    empty_record.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    state, detail = doctor.dependency_diagnostic_state(
        "remember", tmp_path, record=empty_record
    )
    assert state == "not-installed", (state, detail)


# --- op shape (supertool): relayed / could-not-run, never folded together ----


def test_supertool_op_relays_when_it_runs_and_exits_zero(tmp_path):
    root = tmp_path / "cache" / "supertool" / "0.52.0"
    record = _install_record(tmp_path, [("supertool", "0.52.0", root)])
    state, detail = doctor.dependency_diagnostic_state(
        "supertool",
        tmp_path,
        record=record,
        run=_run_answering("line one\nsupertool doctor: ok\n", returncode=0),
        which=lambda name: "/usr/bin/supertool",
    )
    assert state == "relayed", (state, detail)
    assert "supertool doctor: ok" in detail
    assert "0.52.0" in detail


def test_supertool_op_could_not_run_on_a_nonzero_exit(tmp_path):
    """Must-fire control for the test above, on the same fixture shape: a
    nonzero exit must NOT render as `relayed` -- that would be a pass built on
    a diagnostic that did not answer cleanly."""
    root = tmp_path / "cache" / "supertool" / "0.52.0"
    record = _install_record(tmp_path, [("supertool", "0.52.0", root)])
    state, detail = doctor.dependency_diagnostic_state(
        "supertool",
        tmp_path,
        record=record,
        run=_run_answering("traceback or similar\n", returncode=1),
        which=lambda name: "/usr/bin/supertool",
    )
    assert state == "could-not-run", (state, detail)


def test_supertool_op_could_not_run_when_no_executable_on_path(tmp_path):
    root = tmp_path / "cache" / "supertool" / "0.52.0"
    record = _install_record(tmp_path, [("supertool", "0.52.0", root)])
    state, detail = doctor.dependency_diagnostic_state(
        "supertool", tmp_path, record=record, which=lambda name: None
    )
    assert state == "could-not-run", (state, detail)
    assert "PATH" in detail


def test_supertool_op_could_not_run_on_a_timeout(tmp_path):
    root = tmp_path / "cache" / "supertool" / "0.52.0"
    record = _install_record(tmp_path, [("supertool", "0.52.0", root)])
    state, detail = doctor.dependency_diagnostic_state(
        "supertool",
        tmp_path,
        record=record,
        run=_run_raising(subprocess.TimeoutExpired(cmd="supertool", timeout=30)),
        which=lambda name: "/usr/bin/supertool",
    )
    assert state == "could-not-run", (state, detail)
    assert "timed out" in detail


# --- script shape (jit-context): the documented 0/1/2 contract, honoured -----


def _jit_script(tmp_path, body="#!/bin/bash\necho ok\n"):
    root = tmp_path / "cache" / doctor.JIT_PLUGIN / "0.6.0"
    script = root / "scripts" / "jit-doctor.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    record = _install_record(tmp_path, [(doctor.JIT_PLUGIN, "0.6.0", root)])
    return record


@pytest.mark.parametrize("code", [0, 1, 2])
def test_jit_context_relays_every_documented_exit_code(tmp_path, code):
    """0 nothing inert / 1 a layer the matcher can never load / 2 SKIPPED --
    all three are the dependency ANSWERING, and #638 requires each to still
    relay rather than being flattened into a boolean."""
    record = _jit_script(tmp_path)
    state, detail = doctor.dependency_diagnostic_state(
        doctor.JIT_PLUGIN,
        tmp_path,
        record=record,
        run=_run_answering("jit-doctor: some line\n", returncode=code),
        which=lambda name: "/bin/bash",
    )
    assert state == "relayed", (state, detail, code)
    assert "exit {}".format(code) in detail


def test_jit_context_skipped_never_renders_as_clean(tmp_path):
    """#638's own must-not-fire control: exit 2 (SKIPPED) is `relayed`, and the
    detail must say so rather than reading identically to exit 0."""
    record = _jit_script(tmp_path)
    state, detail = doctor.dependency_diagnostic_state(
        doctor.JIT_PLUGIN,
        tmp_path,
        record=record,
        run=_run_answering("jit-doctor: SKIPPED\n", returncode=2),
        which=lambda name: "/bin/bash",
    )
    assert state == "relayed"
    assert "exit 2" in detail
    assert "SKIPPED" in detail


def test_jit_context_could_not_run_outside_its_documented_contract(tmp_path):
    record = _jit_script(tmp_path)
    state, detail = doctor.dependency_diagnostic_state(
        doctor.JIT_PLUGIN,
        tmp_path,
        record=record,
        run=_run_answering("unexpected crash\n", returncode=127),
        which=lambda name: "/bin/bash",
    )
    assert state == "could-not-run", (state, detail)


def test_jit_context_could_not_run_when_script_missing_from_the_resolved_root(tmp_path):
    root = tmp_path / "cache" / doctor.JIT_PLUGIN / "0.6.0"
    root.mkdir(parents=True)
    record = _install_record(tmp_path, [(doctor.JIT_PLUGIN, "0.6.0", root)])
    state, detail = doctor.dependency_diagnostic_state(
        doctor.JIT_PLUGIN, tmp_path, record=record, which=lambda name: "/bin/bash"
    )
    assert state == "could-not-run", (state, detail)
    assert "not on disk" in detail


# --- script shape (remember): always exits 0, the VERDICT: line is the signal


def _remember_script(tmp_path, body):
    root = tmp_path / "cache" / "remember" / "0.23.0"
    script = root / "scripts" / "doctor.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    record = _install_record(tmp_path, [("remember", "0.23.0", root)])
    return record


def test_remember_relays_a_working_verdict(tmp_path):
    record = _remember_script(tmp_path, "#!/bin/bash\necho x\n")
    state, detail = doctor.dependency_diagnostic_state(
        "remember",
        tmp_path,
        record=record,
        run=_run_answering(
            "some report\nVERDICT: capture is working -- last save 2026-08-29\n",
            returncode=0,
        ),
        which=lambda name: "/bin/bash",
    )
    assert state == "relayed", (state, detail)
    assert "capture is working" in detail


def test_remember_relays_a_problem_verdict_without_reclassifying_it(tmp_path):
    """Must-fire control for the test above: a `VERDICT: problem` line still
    relays -- `remember`'s script exits 0 either way, so the exit code alone
    could not distinguish these two, and folding both into `relayed` with no
    visible difference would be exactly the third-state collapse #638 is
    about."""
    record = _remember_script(tmp_path, "#!/bin/bash\necho x\n")
    state, detail = doctor.dependency_diagnostic_state(
        "remember",
        tmp_path,
        record=record,
        run=_run_answering(
            "some report\nVERDICT: problem -- PostToolUse has never fired\n",
            returncode=0,
        ),
        which=lambda name: "/bin/bash",
    )
    assert state == "relayed", (state, detail)
    assert "problem" in detail


def test_remember_could_not_run_on_an_unexpected_nonzero_exit(tmp_path):
    record = _remember_script(tmp_path, "#!/bin/bash\necho x\n")
    state, detail = doctor.dependency_diagnostic_state(
        "remember",
        tmp_path,
        record=record,
        run=_run_answering("crashed\n", returncode=1),
        which=lambda name: "/bin/bash",
    )
    assert state == "could-not-run", (state, detail)


# --- the check-level wiring: could-not-run is a WARN, never an OK ------------


def test_check_dependency_diagnostics_warns_on_could_not_run_never_ok(tmp_path):
    def fake_state(name, project_dir, **kwargs):
        return "could-not-run", "{} broke".format(name)

    original = doctor.dependency_diagnostic_state
    try:
        doctor.dependency_diagnostic_state = fake_state
        doctor.check_dependency_diagnostics(tmp_path)
    finally:
        doctor.dependency_diagnostic_state = original
    states = [state for state, _ in doctor.FINDINGS]
    assert states and all(s == "WARN" for s in states), doctor.FINDINGS


def test_check_dependency_diagnostics_is_ok_on_relayed_and_not_installed(tmp_path):
    """Must-not-fire control for the test above, on the same call shape: a
    clean relay and an ordinary not-installed both render OK, never WARN."""
    names = doctor.declared_dependencies()

    def fake_state(name, project_dir, **kwargs):
        return ("relayed", "{} ok".format(name)) if name == names[0] else (
            "not-installed", "{} absent".format(name)
        )

    original = doctor.dependency_diagnostic_state
    try:
        doctor.dependency_diagnostic_state = fake_state
        doctor.check_dependency_diagnostics(tmp_path)
    finally:
        doctor.dependency_diagnostic_state = original
    states = [state for state, _ in doctor.FINDINGS]
    assert states and all(s == "OK" for s in states), doctor.FINDINGS


def test_check_dependency_diagnostics_unmeasured_with_no_declared_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "declared_dependencies", lambda: [])
    doctor.check_dependency_diagnostics(tmp_path)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "dependency diagnostics" in message


# --- an unknown dependency shape is could-not-run, not silently skipped -----


def test_unknown_dependency_shape_is_could_not_run(tmp_path):
    state, detail = doctor.dependency_diagnostic_state("some-future-dependency", tmp_path)
    assert state == "could-not-run", (state, detail)
