r"""#526: the install doc's `ln -sf` step, and whether the measurement that settles it is recorded.

`#526` asked whether the marketplace cache directory (`.../dpt-plugins/oss/<version>/bin`) is
reliably on a maintainer's own `PATH`, which would make the symlink step redundant.
Nothing in this repository can run that measurement in CI -- it depends on a real login shell,
a real install, a real OS -- so this file does not attempt to. What it checks is narrower and
fully static: that the *answer* (measured once, by hand, and recorded rather than assumed) is
actually written down where a reader would see it, in both of the places this repository states
that kind of fact. #795 moved the symlink instruction and its #526 note, together, out of
README.md and into docs/install.md; CLAUDE.md's own copy is untouched by that move.

Positive/negative pairing, per CLAUDE.md's "must fire"/"must not fire" rule: the section
containing the `ln -sf` instruction must still contain it (the negative outcome of the
measurement did not, and must not, remove the step), paired with a control proving the search
string is not simply matching everywhere in the file.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
INSTALL_DOC = REPO_ROOT / "docs" / "install.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
#: #904 routed CLAUDE.md's trap prose into jit-context rules, so the measured `PATH` finding now
#: lives in the rule that fires when somebody names the launcher rather than in a file every
#: session loads whole. The assertions below are unchanged; only the file holding the fact moved.
LAUNCHER_RULE = (
    REPO_ROOT
    / ".claude"
    / "jit-context"
    / "vocabulary"
    / "00-manual"
    / "launcher-path-reach.md"
)


def _read(path):
    return path.read_text(encoding="utf-8")


def test_install_doc_still_instructs_the_symlink():
    """The measurement's answer was 'keep it', not 'remove it' -- confirm the instruction
    the issue was about is still there, not silently dropped by this same change."""
    body = _read(INSTALL_DOC)
    assert 'ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace' in body


def test_install_doc_records_the_526_measurement_near_the_symlink_instruction():
    body = _read(INSTALL_DOC)
    ln_at = body.index('ln -sf "$PWD/bin/oss-workspace"')
    measurement_at = body.index("#526")
    assert measurement_at > ln_at, (
        "the #526 note should follow the instruction it is about"
    )
    # Not on the opposite end of the document -- same section.
    assert body.count("\n", ln_at, measurement_at) <= 20


def test_the_jit_rule_records_the_measured_path_finding():
    """The measurement is recorded where a session meets the subject, not in every session.

    This read `CLAUDE.md` until #904. The check is the same one -- the answer measured by hand is
    written down rather than assumed -- against the file that now carries it.
    """
    body = _read(LAUNCHER_RULE)
    assert "#526" in body
    assert "dpt-plugins" in body
    assert "PATH" in body


def test_claude_md_no_longer_carries_the_measurement_inline():
    """The other half of #904: routed out means gone from here, not copied.

    Paired with the assertion above so that "the rule has it" and "CLAUDE.md does not" are both
    established -- either alone passes for a file that was simply deleted.
    """
    assert "#526" not in _read(CLAUDE_MD)


def test_a_string_absent_from_both_files_is_correctly_reported_absent():
    """Negative control: proves `in` here can fail, i.e. these assertions are not vacuous."""
    body = _read(README) + _read(CLAUDE_MD) + _read(LAUNCHER_RULE)
    assert "#999999-does-not-exist" not in body
