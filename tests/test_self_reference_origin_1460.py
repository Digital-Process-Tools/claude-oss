"""self_reference_finding's message should point at why the rule exists (#1460).

`self_reference_finding()` raises when a changelog fragment's own body never names the issue
number in its own filename. The rule itself has an origin -- `claude-supertool#1251`, the issue
that first found fragments were not findable this way -- and the raised message used to say
nothing about it: a reader saw only "you forgot to cite yourself" with no pointer to why the rule
exists at all. `claude-supertool`'s own retired local copy of this assembler carried that pointer;
the port to this owned copy dropped it.

`.oss/assemble_changelog.py` is a byte-for-byte copy of this file, vendored into every scaffolded
repo (see `scaffold._owned_assembler`), so the origin issue is cited by an absolute URL rather than
a bare `#1251` -- a bare citation would resolve against whichever tracker a scaffolded repo's own
reader is standing in, which `tests/test_assemble_changelog_citations.py` already guards against
for exactly this file.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assemble_changelog as ac  # noqa: E402


def test_self_reference_finding_names_the_originating_issue():
    """Must fire: a fragment whose body never cites its own issue gets a finding
    that also names #1251, the issue that motivated the rule."""
    finding = ac.self_reference_finding(
        "1192.security.md", "some unrelated body text\n"
    )
    assert finding is not None
    assert "1251" in finding, (
        "self_reference_finding's message should point at claude-supertool#1251, the "
        "issue that motivated this rule -- got: " + finding
    )


def test_self_reference_finding_silent_when_the_issue_is_named():
    """Must not fire: a fragment that DOES cite its own issue gets no finding at all,
    the positive control paired with the assertion above."""
    finding = ac.self_reference_finding(
        "1192.security.md", "fixes the bug from #1192\n"
    )
    assert finding is None
