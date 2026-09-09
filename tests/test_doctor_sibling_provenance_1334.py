"""#1334: `_statusline_sibling_doctor_path()` returned a candidate whose only
gate was `Path.is_file()`. In a managed repository the vendored copy of this
module lives at `<repo>/.oss/statusline.py` (see `_owned_statusline` /
`OWNED_DIR` in `scaffold.py`), so the sibling candidate resolves to
`<repo>/.oss/doctor.py` -- a path INSIDE the repository under inspection,
not gitignored, and addable by an ordinary pull request. `_doctor_reading`
then executes whatever is there with `sys.executable`, in the maintainer's
own session, reachable with no user action (`gather()` forks a refresh
whenever the board is stale).

Fix: `_doctor_script_path` no longer trusts a sibling candidate that sits in
a directory named like `scaffold.py`'s `OWNED_DIR` (".oss") -- the one
location this file's own module docstring says it is vendored into standalone
and nowhere else. That directory name is not attacker-controlled: `scaffold.py`
is the only writer of it and always uses the literal ".oss". A candidate
anywhere else (this repository's own `scripts/` checkout, a pytest tmp dir,
the plugin's own installed `scripts/` directory) is still trusted exactly as
before.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def test_sibling_candidate_inside_the_vendored_directory_is_not_trusted(
    tmp_path, monkeypatch
):
    """The positive control for the bug (#1334's own 'partially exercised'
    fixture): an attacker-plantable `.oss/doctor.py` inside the repo under
    inspection must NOT be returned as the doctor.py to execute, even though
    it exists on disk and would previously have passed the bare `is_file()`
    check."""
    vendored_dir = tmp_path / ".oss"
    vendored_dir.mkdir()
    planted = vendored_dir / "doctor.py"
    planted.write_text("# attacker-planted stand-in\n", encoding="utf-8")
    monkeypatch.setattr(statusline, "_statusline_sibling_doctor_path", lambda: planted)
    # No installed plugin resolves either, so if the sibling were (wrongly)
    # trusted this would return `planted`; the fix must return `None` instead.
    empty_plugins_root = tmp_path / "empty-plugins"
    empty_plugins_root.mkdir()
    monkeypatch.setattr(statusline, "plugins_root_default", lambda: empty_plugins_root)
    assert statusline._doctor_script_path(str(tmp_path)) is None


def test_sibling_candidate_outside_the_vendored_directory_is_still_trusted(
    tmp_path, monkeypatch
):
    """Positive control the other way: a genuine dev-checkout sibling (any
    directory NOT named `.oss`) must still win, unchanged from before this
    fix -- this is the same case `test_script_path_prefers_the_sibling_file_
    when_it_exists` already covers in test_statusline_doctor_marker_1314.py,
    repeated here as this issue's own paired positive control."""
    sibling = tmp_path / "doctor.py"
    sibling.write_text("# stand-in", encoding="utf-8")
    monkeypatch.setattr(statusline, "_statusline_sibling_doctor_path", lambda: sibling)
    assert statusline._doctor_script_path(str(tmp_path)) == sibling


def test_vendored_sibling_falls_back_to_the_installed_plugin_copy(
    tmp_path, monkeypatch
):
    """When the untrusted vendored sibling is rejected, `_doctor_script_path`
    still falls through to the installed-plugin-root candidate exactly as it
    already does when the sibling is simply missing -- the fix changes which
    candidates are trusted, not the fallback chain itself."""
    vendored_dir = tmp_path / ".oss"
    vendored_dir.mkdir()
    planted = vendored_dir / "doctor.py"
    planted.write_text("# attacker-planted stand-in\n", encoding="utf-8")
    monkeypatch.setattr(statusline, "_statusline_sibling_doctor_path", lambda: planted)

    plugins_root = tmp_path / "plugins"
    install_dir = tmp_path / "installed-oss"
    (install_dir / "scripts").mkdir(parents=True)
    doctor_stub = install_dir / "scripts" / "doctor.py"
    doctor_stub.write_text("# real stand-in", encoding="utf-8")
    plugins_root.mkdir()
    (plugins_root / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@owner/repo": [
                        {"scope": "user", "installPath": str(install_dir)}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(statusline, "plugins_root_default", lambda: plugins_root)
    assert statusline._doctor_script_path(str(tmp_path)) == doctor_stub
