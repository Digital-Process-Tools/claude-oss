"""#788: the dispatch-time claim call the docs used to spell as
`lane_setup.py <issue> --claim`, with no `--lane`, wrote a fileless lane
record. A fileless record then poisoned every later `--derive-held` call this
tick -- `derive_held_set` cannot trust the held set is complete while a lane
with no known files is live, so it returns `could-not-derive` and names the
cause: "recorded without --lane".

The fix asked for by the issue: `--claim` refuses (rather than silently
accepting) a claim with no `--lane`, the same shape `fleet_label.py` already
uses to refuse an incomplete label bundle instead of composing one from a
missing piece. This does not change what `--claim` means beyond requiring the
files be named -- a `--claim --lane <pattern>` call still records exactly as
it always has.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup  # noqa: E402
import spawn_guard  # noqa: E402


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def test_claim_with_no_lane_is_refused():
    result = _run("999999", "--claim")
    assert result.returncode == 2
    assert "--claim requires --lane" in result.stderr
    assert "#788" in result.stderr


def test_claim_with_lane_is_not_refused_at_the_argparse_level():
    """Control: a well-formed --claim --lane call must not be caught by the
    new refusal -- it may still fail downstream (no config, no worktree_root
    in this bare repo), but not with the argparse usage error the fileless
    case gets."""
    result = _run("999999", "--claim", "--lane", "some/file.py")
    assert result.returncode != 2 or "--claim requires --lane" not in result.stderr


def test_release_with_claim_and_no_lane_is_not_refused():
    """Control: --release ignores every other flag (documented), so a stray
    --claim beside it must not trip the new refusal."""
    result = _run("999999", "--release", "--claim")
    assert "--claim requires --lane" not in result.stderr


def test_probe_calls_with_no_claim_are_unaffected():
    """Control: the ordinary read-only probe form (--lane/--against, no
    --claim) is completely untouched by this refusal."""
    result = _run("999999", "--lane", "some/file.py", "--against", "other/file.py")
    assert "--claim requires --lane" not in result.stderr
