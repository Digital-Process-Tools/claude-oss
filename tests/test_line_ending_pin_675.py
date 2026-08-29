"""#675: a size budget measured in raw bytes is a property of the checkout,
not of the file, unless every checkout agrees on line endings. `dispatch.md`
measured 25,980 B as LF (under its 26,100 B budget) and 26,318 B as CRLF
(over it) -- the same bytes, two different verdicts, depending only on which
platform's `git checkout` produced the file on disk.

The fix is `.gitattributes` (`* text=auto eol=lf`), not a change to the
checkers in `scripts/skill_phases.py` / `scripts/agent_budgets.py` -- they
keep counting `len(path.read_bytes())`. So the thing to prove is not "the
checkers do the right arithmetic" (they already did); it is "a real
`git checkout` cannot hand either checker a CRLF file any more". That claim
lives at the git-attributes layer, not in Python, so this test drives an
actual scratch git repository rather than asserting on strings in memory.

Two paired cases in the same fixture (a negative assertion needs a positive
control): a repo carrying this project's own `.gitattributes` must check out
the constructed fixture under budget even when the client's `core.autocrlf`
would otherwise introduce CRLF; a repo with no line-ending pin at all must
reproduce the original bug -- checking out the identical content, under the
identical `core.autocrlf` setting, over budget. If the "must fire" case ever
stopped firing, the "must not fire" case would be proving nothing.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Mirrors the real shape reported in #675: many short lines, LF size under
# budget, CRLF size (LF bytes + one \r per line) over it.
LINE_COUNT = 15
LINE_BODY = "x" * 65  # + "\n" = 66 bytes/line
CONTENT = ((LINE_BODY + "\n") * LINE_COUNT).encode("ascii")
LF_SIZE = len(CONTENT)  # 990
CRLF_SIZE = LF_SIZE + LINE_COUNT  # 1005 -- one extra \r per line
BUDGET = 1000  # LF_SIZE (990) < BUDGET < CRLF_SIZE (1005)

assert LF_SIZE < BUDGET < CRLF_SIZE, "fixture no longer brackets the budget"


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True)


def _measured_checkout_size(tmp_path, *, with_pin, autocrlf):
    """Init a scratch repo, optionally carrying this repo's .gitattributes,
    commit the fixture content as LF, then force a fresh checkout under the
    given core.autocrlf and return the checked-out file's raw byte size --
    the same `len(path.read_bytes())` the real checkers use.
    """
    repo = tmp_path / ("pinned" if with_pin else "unpinned")
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "t@example.com"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    _run(["git", "config", "core.autocrlf", autocrlf], repo)

    if with_pin:
        attrs = (ROOT / ".gitattributes").read_bytes()
        (repo / ".gitattributes").write_bytes(attrs)
        _run(["git", "add", ".gitattributes"], repo)
        _run(["git", "commit", "-q", "-m", "attrs"], repo)

    target = repo / "fixture.md"
    target.write_bytes(CONTENT)
    _run(["git", "add", "fixture.md"], repo)
    _run(["git", "commit", "-q", "-m", "fixture"], repo)

    # Force a fresh checkout so attribute-driven normalization actually runs,
    # rather than trusting whatever bytes `write_bytes` happened to leave.
    target.unlink()
    _run(["git", "checkout", "--", "fixture.md"], repo)

    return len(target.read_bytes())


def test_gitattributes_pin_keeps_checkout_under_budget_675(tmp_path):
    """Must-not-fire: with this repo's own .gitattributes committed, a
    checkout under a Windows-style core.autocrlf still lands at the LF size,
    under budget."""
    size = _measured_checkout_size(tmp_path, with_pin=True, autocrlf="true")
    assert size == LF_SIZE, (
        f"pinned checkout measured {size}B, expected the LF size {LF_SIZE}B "
        "-- .gitattributes did not normalize the checkout to LF"
    )
    assert size <= BUDGET, f"{size}B checkout exceeds budget {BUDGET}B even with the pin"


def test_no_pin_reproduces_the_original_bug_675(tmp_path):
    """Must-fire (positive control): with no .gitattributes at all, the
    identical content checks out as CRLF under the identical core.autocrlf
    and blows the same budget -- reproducing #675 rather than a fixture that
    can never fail."""
    size = _measured_checkout_size(tmp_path, with_pin=False, autocrlf="true")
    assert size == CRLF_SIZE, (
        f"unpinned checkout measured {size}B, expected the CRLF size "
        f"{CRLF_SIZE}B -- the harness stopped reproducing the checkout-"
        "dependent bug this test exists to guard against"
    )
    assert size > BUDGET, (
        f"unpinned checkout measured {size}B, at or under budget {BUDGET}B -- "
        "expected it to reproduce #675's over-budget checkout"
    )


def test_repo_declares_a_line_ending_pin_675():
    """The mechanism itself: this repository ships a .gitattributes that
    normalizes text files to LF on checkout. Presence alone is not the
    contract (the two tests above are), but its absence means neither of
    them has anything to load."""
    path = ROOT / ".gitattributes"
    assert path.exists(), ".gitattributes is missing -- #675 has no pin to test"
    text = path.read_text()
    assert "eol=lf" in text, ".gitattributes does not pin line endings to LF"
