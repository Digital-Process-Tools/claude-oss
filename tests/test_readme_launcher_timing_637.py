"""The launcher-timing receipt names a method and a date (#637).

Before #795 trimmed `README.md`, it stated -- as a measurement -- how much the
launcher's `/oss:doctor` diagnostic costs to run at session-open. #795 moved that
receipt to `docs/install.md`, alongside the rest of the launcher setup material it
sits next to; the fact this test pins did not move with it. The figures went stale
silently once before this issue: they were taken before #621 added a `claude mcp
get` subprocess to every doctor run, and the sentence did not move when that
landed. This does not assert *what* the numbers are -- a timing assertion is
flaky by construction, the kind of test this repository does not tune until
it passes. It pins the weaker, durable thing instead: that the receipt
carries a date and a described method, so the next time the underlying cost
changes, an unmoved sentence is visibly stale rather than silently wrong.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_DOC = REPO_ROOT / "docs" / "install.md"

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _timing_sentence():
    text = INSTALL_DOC.read_text(encoding="utf-8")
    # The paragraph opens with "Measured" and runs to the next blank line --
    # not pinned to any of its own wording past that, so a reword of the
    # method or the numbers does not itself break this test.
    match = re.search(r"^Measured .*?(?=\n\n)", text, re.DOTALL | re.MULTILINE)
    assert match, "README.md has no launcher-timing receipt to check"
    return match.group(0)


def test_launcher_timing_receipt_exists():
    _timing_sentence()


def test_launcher_timing_receipt_carries_a_date():
    sentence = _timing_sentence()
    assert DATE_RE.search(sentence), (
        "the launcher-timing receipt in README.md names no date -- a receipt "
        "with no date cannot be told from a fresh one"
    )


def test_launcher_timing_receipt_names_a_method():
    """Not a fixed string -- the method is free to be reworded -- but the
    receipt has to say more than a platform and a figure, or a reader has
    nothing to repeat and no way to tell a measurement from a guess.
    """
    sentence = _timing_sentence()
    assert "claude" in sentence.lower(), (
        "the launcher-timing receipt does not mention claude's own startup "
        "cost, which is most of what it is measuring"
    )
