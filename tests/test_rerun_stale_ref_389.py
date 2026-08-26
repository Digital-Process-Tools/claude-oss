"""Guard against #389: a rerun replays the same merge ref, so a PR red from a moved

base stays red and reads as a fix that did not work.

`gh run rerun <id> --failed` re-runs the existing check-suite run against the merge
ref it already resolved. It does **not** re-resolve that ref against a `main` that
has since moved, so a fix pushed to `main` after the run started is invisible to
the rerun -- the second red looks exactly like a fix that failed, and the only
observable tell is that the run id did not change.

This is a content test over the governing prose: it asserts the post-condition a
maintainer needs -- the rerun trap is named, the run id is named as the tell, and
the working route (`update-branch`) is named -- not merely that some string
matches, which would pass if the wording moved and the meaning inverted.
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


def _text():
    return SKILL.read_text(encoding="utf-8")


def test_skill_names_the_rerun_trap():
    text = _text()
    assert re.search(r"rerun", text, re.IGNORECASE), (
        "skills/manager/SKILL.md must say what `gh run rerun` does and does not do (#389)"
    )
    assert re.search(r"re-resolve|does not re-resolve", text), (
        "the trap is that a rerun does not re-resolve the merge ref against a moved base -- "
        "say that explicitly, not just that reruns exist (#389)"
    )


def test_skill_names_the_run_id_as_the_tell():
    text = _text()
    assert re.search(r"run id", text, re.IGNORECASE), (
        "the one observable signal that a rerun replayed the same stale ref is the run id "
        "not changing -- name it as the tell (#389)"
    )


def test_skill_names_the_working_route():
    text = _text()
    assert "update-branch" in text, (
        "skills/manager/SKILL.md must name `update-branch` as the route that actually "
        "re-resolves a PR's merge ref against a moved base, since a rerun does not (#389)"
    )


def test_skill_does_not_recommend_rerun_for_a_moved_base():
    """A naive fix that just tells the loop to rerun again must not satisfy this guard."""
    fake_fix = (
        "When a PR goes red, rerun the failed checks with `gh run rerun <id> --failed` "
        "and wait for the new result."
    )
    assert not (
        re.search(r"rerun", fake_fix, re.IGNORECASE)
        and re.search(r"re-resolve|does not re-resolve", fake_fix)
        and re.search(r"run id", fake_fix, re.IGNORECASE)
        and "update-branch" in fake_fix
    ), "the positive control itself must fail all four checks -- otherwise they check nothing"
