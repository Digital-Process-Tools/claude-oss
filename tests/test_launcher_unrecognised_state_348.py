"""#348: `check_oss_workspace_launcher`'s catch-all `else` unpacks a 3-tuple.

`oss_workspace_launcher_state` documents six states. Five have named arms in
`check_oss_workspace_launcher`; the sixth, `mismatched`, is handled by falling
through a bare `else` that does `resolved, their_version, our_version = detail`.
That is correct for `mismatched` and wrong as a catch-all: a seventh state
added later would carry a `detail` shaped however its own contract says, reach
this unpack, and raise -- turning `scripts/doctor.py`'s `exit 0 always, one
VERDICT line` contract into a traceback three frames from wherever the state
was added.

This is contract rot, not a live defect. The must-fire half below constructs a
state the real producer does not emit today, exactly the way the release
audit did, paired with a must-not-fire control: the known state that already
exercises the tuple-unpacking arm must still work once it is named explicitly.
"""

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


def _plugin_root(tmp_path):
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "oss-workspace").write_bytes(b"# running install\n")
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        '{"name": "oss", "version": "9.9.9"}', encoding="utf-8"
    )
    return root


def test_a_currently_unreachable_state_would_not_crash_the_reporter(
    tmp_path, monkeypatch
):
    """The must-fire half. A seventh state -- one that does not exist in the
    real producer today, constructed the way the release audit did -- reaching
    the bare `else`'s `resolved, their_version, our_version = detail` unpack
    must not raise. `exit 0 always` is the contract this whole script carries;
    a state this consumer does not recognise must be REPORTED, not unpacked
    blind.
    """
    plugin_root = _plugin_root(tmp_path)

    def _fake_state(plugin_root=None, path=None):
        return "an-unrecognised-state", "some detail, not a 3-tuple"

    monkeypatch.setattr(doctor, "oss_workspace_launcher_state", _fake_state)

    # Would raise here if the code did nothing: this is the assertion that
    # makes the test worth having.
    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(tmp_path))

    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "an-unrecognised-state" in message, message


def test_the_known_mismatched_state_still_unpacks_and_does_not_raise(tmp_path):
    """The must-not-fire control in the same fixture shape: the real state this
    arm exists for must still work once it is named explicitly rather than
    caught by the bare `else`."""
    plugin_root = _plugin_root(tmp_path)
    cache_dir = tmp_path / "cache" / "dpt-plugins" / "oss" / "0.1.0" / "bin"
    cache_dir.mkdir(parents=True)
    (cache_dir / "oss-workspace").write_bytes(b"different content\n")

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(cache_dir))

    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "SKEW" in message, message
