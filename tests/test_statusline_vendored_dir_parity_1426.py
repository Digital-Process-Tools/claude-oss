"""#1426 part 2: `statusline._VENDORED_DIR_NAME` (".oss") and `scaffold.OWNED_DIR`
(".oss") are the same fact typed twice, with nothing tying them together until
this test. `_VENDORED_DIR_NAME` is the guard `_sibling_doctor_candidate_is_trusted`
uses to refuse a `doctor.py` sibling living inside a managed repo's vendored
directory -- its correctness rests entirely on staying equal to `scaffold.
OWNED_DIR`, the one name `scaffold.py` actually vendors into. Change `OWNED_DIR`
without touching `statusline.py` and the guard silently stops recognising the
vendored directory, trusts the sibling, and executes an attacker-planted file.

Same shape as this repo's existing `_safe_which` parity tests
(`tests/test_gh_git_resolution_arms_1295.py`) -- a forced duplicate because
`statusline.py` is vendored standalone with no third-party imports, so this is
the cheapest available check that the two literals have not drifted.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402
import statusline  # noqa: E402


def test_statusline_vendored_dir_name_agrees_with_scaffold_owned_dir():
    assert statusline._VENDORED_DIR_NAME == scaffold.OWNED_DIR


def test_the_guard_compares_case_folded_so_the_agreement_must_hold_folded_too():
    """`_sibling_doctor_candidate_is_trusted` compares `.lower()` on both
    sides (a case-insensitive, case-preserving filesystem can spell the same
    directory two ways) -- the agreement above must survive that fold too,
    not just an exact string match."""
    assert statusline._VENDORED_DIR_NAME.lower() == scaffold.OWNED_DIR.lower()


def test_the_parity_test_itself_would_fail_on_a_real_divergence(monkeypatch):
    """Negative control: prove this file's own assertion is not vacuously
    true by monkeypatching one side away from the other and watching the
    equality actually fail -- otherwise a typo in the assertion itself could
    render as coverage that was never really there."""
    monkeypatch.setattr(scaffold, "OWNED_DIR", ".not-oss")
    assert statusline._VENDORED_DIR_NAME != scaffold.OWNED_DIR
