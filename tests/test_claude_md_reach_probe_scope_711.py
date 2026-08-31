"""#711: the "What is not proven yet" section's reach probe must state its own scope.

`gh repo list Digital-Process-Tools --limit 100` enumerates one GitHub organisation. The section
used to report the count -- "eleven repositories" -- and close with "what has still not been
observed: any repository scaffolded by a maintainer who is not the author of this plugin" as
though the probe had looked at the whole field. It had not: `#705` was filed from `jbkkz/requivo`,
a repository under a personal account the probe cannot enumerate, so a repository outside the org
and a repository that does not exist render identically to it -- this repository's own defect
class, sitting in the section that exists to enumerate what has not been proven.

This does not widen the probe -- `#711` leaves that part deliberately open, and there is no code
to widen: the probe is a command a maintainer runs by hand at each release, not a script this repo
ships. It pins the cheaper half: the sentence that reports the count must say what it counted, so a
reader who knows of a repository outside the org can tell the claim does not cover it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

SECTION_HEADING = "## What is not proven yet"


def _section(text):
    start = text.find(SECTION_HEADING)
    if start < 0:
        return ""
    rest = text[start + len(SECTION_HEADING) :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _reach_probe_paragraph(section):
    marker = "gh repo list Digital-Process-Tools"
    start = section.find(marker)
    if start < 0:
        return ""
    rest = section[start:]
    end = rest.find("\n\n")
    return rest if end < 0 else rest[:end]


def _closing_paragraph(section):
    marker = "not been observed"
    start = section.find(marker)
    if start < 0:
        return ""
    # Back up to the start of the sentence/paragraph containing the marker.
    para_start = section.rfind("\n\n", 0, start)
    rest = section[para_start:] if para_start >= 0 else section[start:]
    end = rest.find("\n\n", 1)
    return rest if end < 0 else rest[:end]


def test_reach_probe_paragraph_names_its_own_organisation_scope():
    section = _section(CLAUDE_MD.read_text(encoding="utf-8"))
    assert section, f"{CLAUDE_MD} must carry {SECTION_HEADING!r}"
    para = _reach_probe_paragraph(section)
    assert para, "the reach-probe command must appear in the section"
    assert re.search(r"organi[sz]ation", para, re.IGNORECASE), (
        "the paragraph reporting the repository count must say it is scoped to one GitHub "
        "organisation, or 'eleven repositories' reads as a claim about the whole field (#711)"
    )


def test_closing_sentence_states_the_probes_scope_rather_than_a_bare_absence():
    section = _section(CLAUDE_MD.read_text(encoding="utf-8"))
    assert section
    para = _closing_paragraph(section)
    assert para, "the 'not been observed' closing sentence must appear in the section"
    assert "#711" in para, (
        "the closing sentence must cite #711 -- the reason a bare 'not observed' does not mean "
        "'does not exist' -- or a reader has no way to know the absence is a property of the "
        "probe rather than of the world"
    )


def test_the_must_fire_control_fires_on_the_pre_711_text():
    """Reconstructs the section's reach-probe paragraph and closing sentence as they read before
    this fix, and proves both assertions above would have failed against that text -- otherwise
    the checks could be passing for a reason unrelated to this fix.
    """
    before_fix = (
        SECTION_HEADING
        + "\n\n"
        + "`gh repo list Digital-Process-Tools --limit 100` returns **eleven** repositories, "
        "unchanged, and each of five artifacts was probed in every one.\n\n"
        + "What has **still** not been observed, across fourteen rounds: any repository "
        "scaffolded **by a maintainer who is not the author of this plugin**.\n\n## Next heading\n"
    )
    section = _section(before_fix)
    assert section
    para = _reach_probe_paragraph(section)
    assert para and not re.search(r"organi[sz]ation", para, re.IGNORECASE), (
        "control text must not already satisfy the scope-naming check"
    )
    closing = _closing_paragraph(section)
    assert closing and "#711" not in closing, (
        "control text must not already satisfy the #711-citation check"
    )
