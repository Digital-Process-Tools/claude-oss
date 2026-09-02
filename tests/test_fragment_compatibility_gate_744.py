"""#744: this issue's own reproduction, checked against the current gate rather
than assumed against the brief that filed it.

The issue asks for the per-PR fragment gate to read a fragment's `Compatibility`
bullet, citing four real fragments from `jbkkz/requivo` (`391.fixed.md`,
`390.fixed.md`, `396.fixed.md`, all merged with a green `fragment` leg on oss
0.16.0, plus `300.removed.md` from the same batch as the control that declared
correctly).

**Reproduced against this repository's current `scripts/assemble_changelog.py`
and found already fixed.** `git log` shows the fix landed in `eb9c04b`
("enforce a fragment's Compatibility line at PR time (#721, #700)", filed as
PR #737) the same day #744 was reported -- #700 is the earlier issue for the
identical defect, `compatibility_finding()` is the function `collect()` already
calls for every fragment, and `tests/test_fragment_compatibility_check_700.py`
already carries the red/green pairing and a corpus parity check against
`release_version.compatibility`. #744's own field report was taken against
oss 0.16.0, which predates that fix.

So there is no code change in this diff: `--check` already refuses all three
unrecognised-verdict fragments named in the issue, still accepts the
correctly-declared `breaking` control from the same batch, and still accepts a
fragment that omits the bullet entirely. This file exists to pin the exact
reported instances -- rather than #700's synthetic ones -- as a regression
test, and as the receipt that #744 was verified rather than assumed to still
be open.

Python 3.9 compatible.
"""

import contextlib
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import assemble_changelog  # noqa: E402

OK = assemble_changelog.OK
REFUSED = assemble_changelog.REFUSED


def _check(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = assemble_changelog.check(root / "changelog.d")
    return code, buf.getvalue()


def _repo(tmp_path, name="repo"):
    root = tmp_path / name
    (root / "changelog.d").mkdir(parents=True)
    return root


def _frag(root, name, body):
    (root / "changelog.d" / name).write_text(body, encoding="utf-8")


# The three from the issue's own comment table, verbatim (trimmed to the part
# quoted in the table -- the full bodies were never posted, and the quoted
# prefix is what the gate has to refuse on).
FIELD_UNREADABLE = {
    "391.fixed.md": (
        "- a fix, see #391.\n"
        "- Compatibility: `doctor --json`'s `locks.unexpected` array is "
        "unchanged in shape.\n"
    ),
    "390.fixed.md": (
        "- a fix, see #390.\n"
        "- Compatibility: a widening only, in one direction. No slug accepted "
        "before.\n"
    ),
    "396.fixed.md": (
        "- a fix, see #396.\n"
        "- Compatibility: a widening only. No slug accepted before is refused "
        "now.\n"
    ),
}


def test_the_three_reported_fragments_are_each_refused(tmp_path):
    """Each of the three -- 391, 390, 396 -- is a finding on its own, not just in
    combination. A gate that only refused once three bad fragments accumulated
    would still merge each of these PRs, since fragments arrive one to a pull
    request (one file per PR is the directory's own convention)."""
    for name, body in FIELD_UNREADABLE.items():
        root = _repo(tmp_path, name)
        _frag(root, name, body)

        code, out = _check(root)

        assert code == REFUSED, "{0}: {1}".format(name, out)
        assert name in out, out
        assert "breaking" in out and "compatible" in out, out


def test_the_batchs_correct_control_still_passes(tmp_path):
    """The table's fourth row, `300.removed.md`, declared correctly in the same
    batch by the same hands -- the must-fire control. Without it, refusing the
    three above could be explained by a check that refuses every `Compatibility`
    bullet, which would also block the declaration the format exists to collect."""
    root = _repo(tmp_path, "control")
    _frag(
        root,
        "300.removed.md",
        "- an external caller loses a field, see #300.\n"
        "- Compatibility: breaking - an external caller holding a reference to "
        "the removed field now gets a KeyError.\n",
    )

    code, out = _check(root)

    assert code == OK, out
    assert "300.removed.md" in out, out


def test_a_fragment_with_no_compatibility_bullet_still_passes(tmp_path):
    """`release_version.py`'s own `assumed compatible` state, mirrored here: a
    fragment that never mentions Compatibility at all is not the defect #744
    reports, and the acceptance criteria say so explicitly -- a gate that refused
    an absent bullet would fail every ordinary fragment in this repository's own
    changelog.d/."""
    root = _repo(tmp_path, "silent")
    _frag(root, "744.fixed.md", "- a fix, see #744.\n")

    code, out = _check(root)

    assert code == OK, out
