"""#1359: `doctor_check_trap_queue.check_trap_queue` was reported as counting
`trap.d/README.md` as a fragment, inflating `/oss:scaffold`'s own queue by one
-- 13 waiting before `/oss:scaffold --apply`, 14 after, the 14th being the
README the scaffold run itself just wrote, not a real fragment.

Investigated against this repository's current `main`: `check_trap_queue`
delegates entirely to `trap_curate.waiting(project_dir)`, which #1348 already
hardened with exactly this exclusion (`OWNED_README = "README.md"`,
`tests/test_trap_curate_owned_readme_1348.py`). Reproducing the issue's own
scenario directly against `trap_curate.waiting` (see that test file) already
shows a clean count. This file closes the gap #1348 left: nothing exercised
the actual entry point `/oss:doctor` calls, `check_trap_queue` itself, so a
future regression in HOW that check calls `trap_curate` (a different
`project_dir`, a raw re-listing instead of delegating) would have nothing
end-to-end to catch it.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_trap_queue as mod  # noqa: E402


def _trap_d(tmp_path, names):
    d = tmp_path / "trap.d"
    d.mkdir()
    for name in names:
        (d / name).write_text("body\n", encoding="utf-8")
    return tmp_path


def test_the_scaffolded_readme_does_not_inflate_the_reported_queue(tmp_path):
    """Must-fire, end to end: a directory holding the scaffolded README plus
    one real fragment must report exactly 1 waiting, at the actual `/oss:doctor`
    entry point -- not 2."""
    doctor.FINDINGS.clear()
    mod.check_trap_queue(str(_trap_d(tmp_path, ["README.md", "904.a-slug.md"])))
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "NOTICE", (state, message)
    assert "1 waiting" in message, message
    assert "README" not in message, message


def test_a_directory_holding_only_the_readme_reports_none_waiting(tmp_path):
    """Positive control: the drained-queue state (only the README present)
    must render OK/none, never a phantom `1 waiting` for the README alone --
    the exact inflation the issue reproduced (13 real fragments read as 14)."""
    doctor.FINDINGS.clear()
    mod.check_trap_queue(str(_trap_d(tmp_path, ["README.md"])))
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "OK", (state, message)
    assert "none waiting" in message, message
