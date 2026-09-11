"""#1441: `commands/doctor.md` named `/oss:tick` as the next step even when
an actionable WARN's own remedy said to run `/oss:scaffold` first, and
nothing checked the condition the prose itself stated. This is the small,
testable derivation `commands/doctor.md` is told to use instead --
`scripts/doctor_next_step.next_step()`.

Each pair below is a positive control for the other: a report full of
scaffold-actionable WARNs must fire the scaffold branch, and a
clean-or-informational-only report must not.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor_next_step  # noqa: E402


CLEAN_REPORT = "\n".join(
    [
        "OK owned files: all present and current",
        "OK supertool: available",
        "VERDICT: ok",
    ]
)

# Real strings this repo's own doctor.py prints today, per-line-copied from
# `scripts/doctor.py` (`Run /oss:scaffold.`) and
# `scripts/doctor_check_fragments_readme.py`/`doctor_check_codeql_scan.py`
# (mentions `/oss:scaffold` without it being the fix).
SCAFFOLD_ACTIONABLE_REPORT = "\n".join(
    [
        "OK supertool: available",
        "WARN SECURITY.md: not in this repo. Run /oss:scaffold.",
        "WARN .gitignore: not in this repo. Run /oss:scaffold.",
        "VERDICT: usable with gaps",
    ]
)

INFORMATIONAL_ONLY_REPORT = "\n".join(
    [
        "OK supertool: available",
        "WARN fragments readme: changelog.d/README.md exists and does not document "
        "`- Compatibility: breaking|compatible - <reason>`, which "
        "scripts/release_version.py requires on a `removed` fragment. "
        "/oss:scaffold will not fix it -- the file is a default and is never "
        "replaced once it exists. Paste the section by hand from "
        "`scripts/scaffold.py --show changelog.d/README.md`.",
        "WARN CodeQL coverage: the only CodeQL-supported language(s) present "
        "(python) sit entirely inside scripts/, the path(s) this plugin owns and "
        "rewrites wholesale on every /oss:scaffold run -- a default CodeQL setup "
        "would report only on vendored files. Recommend `languages: actions` (if "
        "any GitHub Actions workflows are real attack surface) or no CodeQL "
        "workflow at all.",
        "VERDICT: usable with gaps",
    ]
)


def test_a_scaffold_actionable_warn_fires_the_scaffold_branch():
    state, matched = doctor_next_step.next_step(SCAFFOLD_ACTIONABLE_REPORT)
    assert state == "scaffold", (state, matched)
    assert len(matched) == 2, matched
    assert all("Run /oss:scaffold." in line for line in matched), matched


def test_a_clean_report_names_tick():
    state, matched = doctor_next_step.next_step(CLEAN_REPORT)
    assert state == "tick", (state, matched)
    assert matched == []


def test_warns_that_merely_mention_scaffold_do_not_fire_the_scaffold_branch():
    """The positive control for the other direction: a WARN that mentions
    `/oss:scaffold` without it being the fix -- one explicitly says the
    command will NOT fix it -- must not be misread as scaffold-actionable."""
    state, matched = doctor_next_step.next_step(INFORMATIONAL_ONLY_REPORT)
    assert state == "tick", (state, matched)
    assert matched == []


def test_a_non_string_report_is_could_not_determine_not_tick():
    state, matched = doctor_next_step.next_step(None)
    assert state == "could-not-determine", (state, matched)
    assert matched == []


def test_an_empty_report_is_could_not_determine_not_tick():
    state, matched = doctor_next_step.next_step("   \n  ")
    assert state == "could-not-determine", (state, matched)
    assert matched == []


def test_a_run_that_never_completed_is_could_not_determine():
    state, matched = doctor_next_step.next_step(
        "OK supertool: available\nVERDICT: could not run -- .oss.json could not be read"
    )
    assert state == "could-not-determine", (state, matched)
    assert matched == []


def test_the_match_is_on_the_warn_line_itself_not_the_whole_report():
    """A `Run /oss:scaffold.` sentence appearing on a non-WARN line (an OK
    or NOTICE explaining what scaffold already did) must not fire the
    branch -- only a live WARN carrying it is actionable."""
    report = "\n".join(
        [
            "OK owned files: all present and current (Run /oss:scaffold. cleared "
            "this on the last pass)",
            "VERDICT: ok",
        ]
    )
    state, matched = doctor_next_step.next_step(report)
    assert state == "tick", (state, matched)
