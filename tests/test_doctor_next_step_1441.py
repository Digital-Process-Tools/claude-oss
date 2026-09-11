"""#1441: `commands/doctor.md` named `/oss:tick` as the next step even when
an actionable WARN's own remedy said to run `/oss:scaffold` first, and
nothing checked the condition the prose itself stated. This is the small,
testable derivation `commands/doctor.md` is told to use instead --
`scripts/doctor_next_step.next_step()`.

Each pair below is a positive control for the other: a report full of
scaffold-actionable WARNs must fire the scaffold branch, and a
clean-or-informational-only report must not.

The two scaffold-actionable fixtures below are built through
`doctor.owned_drift_summary()` itself -- the real function
`scripts/doctor.py` calls to produce these WARNs -- rather than hand-typed
strings. A self-review round on this issue found the hand-typed fixture
had drifted from the real output on two counts: `owned_drift_summary()`
groups findings sharing identical detail text into one line rather than
printing one per file, and the "gate could not be determined" WARN ends
its sentence with a comma (`Run /oss:scaffold, which reports what it
could not read.`), not the period the first draft assumed -- a case this
derivation's own docstring already claimed to cover and, before the fix,
silently did not. Building the fixtures from the real function makes both
of those defects visible to this test rather than to a future reader
diffing prose by hand.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_next_step  # noqa: E402


def _report_from(findings):
    """Render `doctor.owned_drift_summary()`'s own output the way
    `doctor.report()` actually prints it: `"{level} {message}"`, one per
    line -- the exact format `commands/doctor.md`'s next-step derivation
    reads.
    """
    lines = [
        "{} {}".format(level, message)
        for level, message in doctor.owned_drift_summary(findings)
    ]
    lines.append("VERDICT: usable with gaps")
    return "\n".join(lines)


CLEAN_REPORT = "\n".join(
    [
        "OK owned files: all present and current",
        "OK supertool: available",
        "VERDICT: ok",
    ]
)

# Two owned files missing entirely -- the "absent" state.
ABSENT_OWNED_FILES_REPORT = _report_from(
    [
        {
            "path": "SECURITY.md",
            "state": "absent",
            "detail": "SECURITY.md: not in this repo. Run /oss:scaffold.",
        },
        {
            "path": ".gitignore",
            "state": "absent",
            "detail": ".gitignore: not in this repo. Run /oss:scaffold.",
        },
    ]
)

# An owned changelog file whose scaffold gate could not itself be read --
# the "unknown" state, real text copied from `scripts/doctor.py`'s own
# `verdict == "unknown"` branch (owned_drift, around line 5742).
GATE_UNKNOWN_REPORT = _report_from(
    [
        {
            "path": "CHANGELOG.md",
            "state": "unknown",
            "detail": "CHANGELOG.md: not in this repo, and whether /oss:scaffold "
            "would write it could not be determined -- so this is neither "
            "a gap nor a decision. Run /oss:scaffold, which reports what "
            "it could not read.",
        }
    ]
)

# Real strings this repo's own doctor.py prints today, copied verbatim from
# `scripts/doctor_check_fragments_readme.py` and
# `scripts/doctor_check_codeql_scan.py` -- WARNs that mention `/oss:scaffold`
# without it being the fix.
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


def test_two_absent_owned_files_fire_the_scaffold_branch():
    state, matched = doctor_next_step.next_step(ABSENT_OWNED_FILES_REPORT)
    assert state == "scaffold", (state, matched)
    assert len(matched) == 1, (
        "owned_drift_summary() groups identical findings into one line -- "
        "expected exactly one grouped WARN, not one per file: {!r}".format(matched)
    )
    assert "Run /oss:scaffold." in matched[0], matched


def test_an_undecidable_changelog_gate_fires_the_scaffold_branch():
    """The bug a self-review round found: the real `unknown`-state WARN ends
    its sentence with a comma, not a period, and an earlier version of
    `SCAFFOLD_REMEDY` required the period -- silently missing a case this
    module's own docstring already claimed to cover."""
    state, matched = doctor_next_step.next_step(GATE_UNKNOWN_REPORT)
    assert state == "scaffold", (state, matched)
    assert len(matched) == 1, matched
    assert "Run /oss:scaffold, which reports what it could not read." in matched[0], (
        matched
    )


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
