"""#853 -- the fix for the #753/#810 review findings (5b292bd) introduced a NEW
Windows-only failure: every launcher test's stub-driven receipt ended up reporting
`/oss:doctor` unconditionally, including three explicit must-not-fire controls in
`tests/test_workspace_auto_update_753.py` whose own stubs asked for no update at
all. The stderr in every failure named a version transition (`0.1.0` to `0.2.0`)
belonging to a DIFFERENT test's fixture -- the signature of one test reading
another test's leftover state, not of a fixture bug local to any one assertion.

`scripts/plugin_update.receipt_dir()` reads `LOCALAPPDATA` first on Windows and
never falls back to `HOME`/`USERPROFILE` while it is set. Both
`tests/test_workspace_launcher.py`'s `run()` and
`tests/test_workspace_auto_update_753.py`'s `_run_with_stub()` isolate HOME and
USERPROFILE per test -- which fully isolates the POSIX branch of `receipt_dir()`
-- but neither used to isolate LOCALAPPDATA, so on a real Windows runner (which
always has LOCALAPPDATA set) every subprocess launched by either file read and
wrote the SAME real, machine-scoped receipt file. `plugin_update.main()`'s own
debounce (`DEBOUNCE_SECONDS = 120`) then let one test's genuine update survive,
unopted-out and unconditionally, into any other test's launch that landed inside
the same 120-second window -- which is why the failures spanned both files and
included cases (`test_the_prompt_precedes_the_channel_flag`, etc.) that are not
about auto-update at all.

This module reproduces the SAME defect class on whatever platform runs it, using
the POSIX-side counterpart of the missing override: `XDG_CACHE_HOME`, which
`receipt_dir()` checks with an identical priority over `HOME` on non-Windows.
Setting it ambiently (as a real CI runner's own environment might, and as
LOCALAPPDATA always is on a real Windows runner) and then driving two INDEPENDENT
launcher invocations proves the leak without needing a Windows box: before the
LOCALAPPDATA/XDG_CACHE_HOME isolation was added to `_run_with_stub`, an ambient
`XDG_CACHE_HOME` made the second, unrelated invocation inherit the first one's
receipt via debounce. After the fix, each call's `home`-scoped override wins over
the ambient value and the two invocations never share a receipt.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_workspace_launcher import _repo  # noqa: E402
from test_workspace_auto_update_753 import _run_with_stub  # noqa: E402


def test_ambient_xdg_cache_home_does_not_leak_a_receipt_across_invocations(
    tmp_path, monkeypatch
):
    """The must-fire half: repo1's genuine update must still switch its own
    prompt to /oss:doctor -- the isolation fix must not have broken that."""
    ambient = tmp_path / "ambient_machine_cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(ambient))

    repo1 = _repo(tmp_path / "repo1")
    done1, argv1 = _run_with_stub(repo1, before="0.1.0", after="0.2.0")
    assert "/oss:doctor" in argv1, (argv1, done1.stderr)


def test_a_second_unrelated_invocation_is_not_contaminated(tmp_path, monkeypatch):
    """The must-not-fire control, in the SAME ambient-cache fixture as above: a
    second, unrelated repo whose own stub reports no change at all must keep the
    ordinary prompt, even though it launches inside the first call's debounce
    window and even though both processes inherit the identical ambient
    XDG_CACHE_HOME. Before LOCALAPPDATA/XDG_CACHE_HOME were pinned per-call in
    `_run_with_stub`, this failed: repo2 read repo1's real receipt (state
    "updated", to "0.2.0") off the shared ambient cache path and reported
    /oss:doctor for a repo whose own fixture asked for nothing to change --
    exactly the shape of the six Windows CI failures in #853.
    """
    ambient = tmp_path / "ambient_machine_cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(ambient))

    repo1 = _repo(tmp_path / "repo1")
    _run_with_stub(repo1, before="0.1.0", after="0.2.0")

    repo2 = _repo(tmp_path / "repo2")
    done2, argv2 = _run_with_stub(repo2, before="0.1.0", after="0.1.0")
    assert "/oss:tick" in argv2, (argv2, done2.stderr)
    assert "/oss:doctor" not in argv2, argv2
