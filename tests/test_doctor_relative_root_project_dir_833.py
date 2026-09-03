"""#833 -- `doctor.py --root .` hands a script-shaped dependency's own
diagnostic the literal string `.` as `CLAUDE_PROJECT_DIR`, so `remember`'s
`scripts/doctor.sh` derives a session-directory slug from `.`, gets `-`, finds
no transcript directory, and reports a false `VERDICT: problem` that
`dependency_diagnostic_state` relays verbatim -- the verdict is real, the fact
it describes is not.

`--root .` is the documented invocation in six places across `commands/tick.md`,
`commands/scaffold.md` and `commands/setup.md`; `bin/oss-workspace` always
passes an absolute root, which is why this stayed invisible on that path.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _capturing_run(captured, text="VERDICT: capture is working\n", returncode=0):
    def run(cmd, cwd=None, env=None, **kwargs):
        captured["env"] = env
        captured["cwd"] = cwd
        return _FakeCompleted(returncode, text)

    return run


def _remember_record(tmp_path, root):
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps(
            {"plugins": {"remember@dpt-plugins": [{"version": "0.23.0", "installPath": str(root)}]}}
        ),
        encoding="utf-8",
    )
    return record


def _remember_install(tmp_path):
    root = tmp_path / "cache" / "remember" / "0.23.0"
    script = root / "scripts" / "doctor.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\necho x\n", encoding="utf-8")
    return root


def test_a_relative_root_reaches_the_child_process_absolutised(tmp_path, monkeypatch):
    """Red before the fix: this asserted `env["CLAUDE_PROJECT_DIR"] == "."` and
    passed. Now the child sees an absolute path derivable to a real transcript
    directory rather than the literal dot `remember`'s own script cannot use."""
    root = _remember_install(tmp_path)
    record = _remember_record(tmp_path, root)
    project = tmp_path / "requivo"
    project.mkdir()
    monkeypatch.chdir(project)

    captured = {}
    state, detail = doctor.dependency_diagnostic_state(
        "remember",
        ".",
        record=record,
        run=_capturing_run(captured),
        which=lambda name: "/bin/bash",
    )

    assert state == "relayed", (state, detail)
    seen = captured["env"]["CLAUDE_PROJECT_DIR"]
    assert seen != ".", "CLAUDE_PROJECT_DIR was handed the relative root verbatim"
    assert os.path.isabs(seen), seen
    assert os.path.abspath(seen) == os.path.abspath(str(project))


def test_an_already_absolute_root_is_unchanged(tmp_path, monkeypatch):
    """Positive control: `bin/oss-workspace`'s own path, already absolute, must
    keep behaving exactly as it did before -- the fix must not perturb the
    already-correct case."""
    root = _remember_install(tmp_path)
    record = _remember_record(tmp_path, root)
    project = tmp_path / "requivo"
    project.mkdir()

    captured = {}
    state, detail = doctor.dependency_diagnostic_state(
        "remember",
        str(project),
        record=record,
        run=_capturing_run(captured),
        which=lambda name: "/bin/bash",
    )

    assert state == "relayed", (state, detail)
    assert captured["env"]["CLAUDE_PROJECT_DIR"] == str(project)
