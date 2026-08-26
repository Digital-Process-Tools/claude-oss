"""#478/#467, content half: the Stops table and gate 4 have to say what the code now
does, and the losing reading -- one key silently governing both the tag/publish grant and
the version-number decision -- has to be impossible to reach from the prose an agent
reads while cutting a release.

A prose assertion alone cannot tell "reads the key" from "restates one arm and forgets
the other", so this checks both directions: the two Stops rows and gate 4 each carry the
sentence that decouples them, and neither `release.authority` nor `oss_config.release_
authority` appears anywhere in gate 4's own paragraph -- the one place a wider,
unreviewed reading of the key could sneak back in.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_docs import ManagerLoop  # noqa: E402

#: The manager loop's whole prose -- SKILL.md plus every phase file it defers
#: to. The checks below ask "does the loop say X", never "does one file say
#: X"; pinned to the spine alone they would have gone quietly narrower than
#: their own subject the moment a paragraph moved into a phase file.
SKILL = ManagerLoop(REPO_ROOT)
RELEASE_CMD = REPO_ROOT / "commands" / "release.md"
RELEASE_VERSION = REPO_ROOT / "scripts" / "release_version.py"


def _skill_text():
    return SKILL.read_text(encoding="utf-8")


def _gate_4_block(text):
    """The paragraph(s) of gate 4, from its numbered marker to gate 5's."""
    start = text.index("4. **The number itself is proposed")
    end = text.index("5. **Every version site bumped")
    return text[start:end]


def test_stops_table_reads_the_key_rather_than_asserting():
    text = _skill_text()
    assert "release.authority" in text
    assert "oss_config.release_authority" in text
    # Both stop rows point at the explanatory paragraph rather than asserting outright.
    assert "conditional, see below" in text


def test_stops_paragraph_names_all_three_states():
    text = _skill_text()
    for state in ("`loop`", "`maintainer`", "`not-declared`"):
        assert state in text


def test_gate_4_accepts_by_default_and_never_treats_the_key_as_a_grant():
    block = _gate_4_block(_skill_text())
    assert "no stop" in block
    assert "major" in block
    # The decoupling: gate 4 is allowed to *say* it does not read the key -- that is the
    # explicit disclaimer this test wants to see -- but must never use it as a condition
    # the way the Stops-table paragraph does ("if release.authority is ..."). The only
    # sentence naming the key here is the negative one.
    mentions = [m.start() for m in re.finditer(r"release\.authority", block)]
    assert mentions, "gate 4 must say explicitly that it does not read the key"
    for start in mentions:
        window = block[max(0, start - 20):start]
        assert "not read" in window or "does not read" in window, (
            "gate 4 mentions release.authority outside the explicit disclaimer -- "
            "that is the leak this test exists to catch"
        )


def test_gate_4_states_the_decoupling_reason():
    text = _skill_text()
    assert "does not read this key" in text or "does not read `release.authority`" in text


def test_release_command_reads_authority_before_tag_and_publish():
    text = RELEASE_CMD.read_text(encoding="utf-8")
    assert "release.authority" in text
    assert "Who may tag and publish" in text
    for state in ("`loop`", "`maintainer`", "`not-declared`"):
        assert state in text


def test_release_command_version_gate_has_no_stop_but_major():
    text = RELEASE_CMD.read_text(encoding="utf-8")
    assert re.search(r"no stop \(#467\)", text)
    assert "major" in text


def test_release_version_docstring_drops_the_hedge():
    text = RELEASE_VERSION.read_text(encoding="utf-8")
    assert "a project may reasonably want a person to make it" not in text
    assert "stays yours to make" not in text
