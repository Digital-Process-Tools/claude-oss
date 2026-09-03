"""#785: `agents/developer.md` pins collision-free destinations for the final
report (`:927`) and the pull request payload (`:1061`) by folding branch and timestamp
into the filename, but said nothing about staged intermediates -- and every lane in a
dispatched fleet shares one scratchpad directory (this loop mandates concurrent lanes,
see `skills/manager/phases/dispatch.md`). A real collision was observed: one lane staged
an intermediate at a fixed scratchpad path, a second lane on a different branch wrote its
own intermediate to the identical path, and the first lane's file was silently
overwritten -- caught only because a downstream schema validator rejected the wrong
content's shape.

This file checks the brief now says intermediates need the same discriminators the
destination paths already use, and that a fixed name under a shared scratchpad is unsafe
under a fleet -- not that any code enforces it, since this is prose read by an agent.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from developer_docs import DeveloperBrief  # noqa: E402

DEVELOPER_MD = DeveloperBrief()  # spine + agents/developer/*.md (#939)


def _flat():
    return " ".join(DEVELOPER_MD.read_text(encoding="utf-8").split())


def test_intermediates_must_be_uniquely_named_too():
    text = _flat()
    assert "scratchpad" in text
    assert "intermediate" in text, (
        "agents/developer.md never mentions staged intermediates near the destination "
        "rule -- the #785 gap"
    )


def test_says_a_fixed_name_under_a_shared_scratchpad_is_unsafe_under_a_fleet():
    text = _flat()
    assert "shared" in text and "scratchpad" in text
    assert "fleet" in text or "concurrent" in text, (
        "agents/developer.md does not say a fixed filename under the shared scratchpad "
        "is unsafe when several lanes run concurrently"
    )
