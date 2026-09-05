"""The docs duty: `docs_targets` is observed in the report, not gated in CI.

`.oss.json` carries `docs_targets` and both agent-facing documents require it for
anything user-facing. Nothing read it. An unenforced instruction and a satisfied
one render identically in a merged pull request -- this repository's own defect
class aimed at its own process -- which is #164.

The obvious fix is the symmetry with the changelog gate, and it was measured
against this repository's own last thirty merged pull requests before being
rejected rather than after. Six of the thirty changed `README.md` for the docs
duty (two more touched it only as a `version_site` during a release, which is a
different duty and is excluded). Against that base rate:

    candidate rule                  fires  right  wrong  missed  precision
    any product path -- the gate's      27      6     21       0        22%
      own trigger, changelog.yml
    commands/ or bin/ touched           18      6     12       0        33%
    commands/*.md touched               18      6     12       0        33%
    skills/ or commands/ touched        22      6     16       0        27%
    new file under a product path        0      0      0       6        n/a
    .claude-plugin/plugin.json           2      0      2       6         0%

The best rule anyone proposed is wrong two times in three, which earns a blanket
override label inside a week and converts an unmeasured duty into a measured and
routinely-overridden one. The narrowest rule fires on none of the thirty at all,
and a gate that never fires cannot be told from a gate that is broken. So: no
gate. The duty moves from unobservable to observable instead, as a survey in the
agent's report carrying a state per path.

What this file guards is that the third state survives the move. `not-read` and
an absent `docs` survey must not be spellable the same way as "the docs were
fine", and a `no-change-needed` with no reason is exactly what a run that never
opened the file also writes.

Every "must not fire" case below is paired with a "must fire" case built from the
same fixture, so a validator that has stopped validating fails here rather than
reporting every mutation as correctly refused.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import developer_docs  # noqa: E402
import report_schema  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "agent-report.schema.json"
DEVELOPER = developer_docs.DeveloperBrief()  # spine + agents/developer/*.md (#939)


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _example():
    return json.loads(json.dumps(_schema()["examples"][0]))


# --------------------------------------------------------------------------
# The schema carries the field at all
# --------------------------------------------------------------------------


def test_docs_is_a_required_top_level_key():
    """A report that simply omits the survey is the failure mode being closed.

    If `docs` were optional, "nobody looked" and "no report field yet" would be
    the same bytes on disk, which is the state this whole change exists to make
    unspellable.
    """
    schema = _schema()
    assert "docs" in schema["required"], "docs must be required, not optional"
    assert "docs" in schema["properties"]


def test_a_report_without_docs_is_refused():
    report = _example()
    del report["docs"]
    assert report_schema.validate(report), "a report with no docs survey was accepted"


def test_the_shipped_example_carries_a_populated_docs_survey():
    """The example is what a reader copies. An empty one teaches the empty one."""
    docs = _example()["docs"]
    assert docs["state"] == "checked"
    assert docs["items"], "the example ships an empty docs survey"
    assert all("path" in item and "state" in item for item in docs["items"])


# --------------------------------------------------------------------------
# The three states, each with its must-fire / must-not-fire pair
# --------------------------------------------------------------------------


def _with_docs(items, state="checked", reason=None):
    report = _example()
    report["docs"] = {"state": state, "items": items}
    if reason is not None:
        report["docs"]["reason"] = reason
    return report


def test_a_target_left_alone_must_say_what_it_was_read_against():
    """must-not-fire / must-fire pair on `no-change-needed`.

    Without the `why`, this state is precisely what an agent that never opened
    the file would also write, and it is the one most likely to be written.
    """
    without = _with_docs([{"path": "README.md", "state": "no-change-needed"}])
    assert report_schema.validate(without), (
        "a target reported as needing no change, with no reason, was accepted -- "
        "that is the sentence a run which never opened the file also writes"
    )

    withy = _with_docs(
        [
            {
                "path": "README.md",
                "state": "no-change-needed",
                "why": "the command table names each command's outputs; this diff adds none",
            }
        ]
    )
    assert report_schema.validate(withy) == [], report_schema.validate(withy)


def test_an_unread_target_must_say_why_and_is_not_a_pass():
    """must-not-fire / must-fire pair on `not-read`."""
    without = _with_docs([{"path": "README.md", "state": "not-read"}])
    assert report_schema.validate(without), (
        "an unread target with no reason was accepted"
    )

    withy = _with_docs(
        [
            {
                "path": "README.md",
                "state": "not-read",
                "why": "held by another lane this run",
            }
        ]
    )
    assert report_schema.validate(withy) == [], report_schema.validate(withy)


def test_an_updated_target_needs_no_reason_because_the_diff_is_the_reason():
    """The accept path for the third state.

    Every assertion above passes when the validator refuses all input. This one
    fails in that case, so the refusals mean something.
    """
    report = _with_docs([{"path": "README.md", "state": "updated"}])
    assert report_schema.validate(report) == [], report_schema.validate(report)


def test_a_target_state_outside_the_three_is_refused():
    report = _with_docs([{"path": "README.md", "state": "fine"}])
    assert report_schema.validate(report), "an undeclared docs state was accepted"


def test_a_docs_target_may_not_carry_an_undeclared_key():
    report = _with_docs(
        [{"path": "README.md", "state": "updated", "mood": "confident"}]
    )
    assert report_schema.validate(report), (
        "an unknown key on a docs target was accepted"
    )


def test_a_docs_target_must_name_its_path():
    report = _with_docs([{"state": "updated"}])
    assert report_schema.validate(report), "a docs target with no path was accepted"


# --------------------------------------------------------------------------
# The survey's own third state
# --------------------------------------------------------------------------


def test_nobody_looked_is_a_state_and_must_carry_a_reason():
    """`docs` inherits the survey rule, and that is the point of using one.

    `checked` with no items means the repo's config named no targets.
    `not-checked` means nobody opened them. Those must not be the same bytes.
    """
    silent = _with_docs([], state="not-checked")
    assert report_schema.validate(silent), (
        "a not-checked docs survey with no reason was accepted"
    )

    spoken = _with_docs([], state="not-checked", reason="the config could not be read")
    assert report_schema.validate(spoken) == [], report_schema.validate(spoken)

    none_configured = _with_docs([])
    assert report_schema.validate(none_configured) == [], (
        "a repo whose docs_targets is empty must be able to say so -- and that is "
        "not the same value as a run which never looked"
    )


def test_a_survey_nobody_ran_cannot_carry_items():
    report = _with_docs(
        [{"path": "README.md", "state": "updated"}],
        state="not-checked",
        reason="nothing was read",
    )
    assert report_schema.validate(report), (
        "a not-checked docs survey carrying items was accepted"
    )


# --------------------------------------------------------------------------
# The brief states the duty, and did not before
# --------------------------------------------------------------------------
#
# PRIOR is section 5 of agents/developer.md exactly as it stood before this
# change -- the whole section, not an abridgement, so an anchor cannot be
# asserted absent from text that never contained it. Em dashes are folded to
# hyphens here and the anchors below avoid them, because the dash character is
# the one thing in this block most likely to be normalised by an editor.
# LIVE_BEFORE is the must-fire half: wording that was in PRIOR and is still on
# disk. Without it, an empty or mis-read PRIOR would satisfy every "was not
# there before" assertion for the wrong reason.

PRIOR = """
5. **Docs are part of the change.** The repo's `docs_targets` for anything user-facing, the changelog
   always. A change nobody can discover is not shipped. If the repo uses changelog fragments, add
   one; do not hand-edit the assembled file.

   **A change to a file convention is not finished until the repo's diagnostic reports the new
   convention.** `scripts/doctor.py` is what tells a maintainer whether their repo matches what this
   plugin expects, so a convention that moves without it answers confidently against a rule nobody
   follows any more - health measured against the old shape, or a gap reported for what is now
   correct behaviour. It has already happened here, and in the worst way to catch: two individually
   correct commits, one teaching the writer to decline a file and one leaving the diagnostic
   reporting that file as missing with the remedy *run the writer that now declines*. The defect
   existed only in the composition, so neither diff review could see it.

   The rule is **make sure the diagnostic reports it**, not *always edit `doctor.py`*. Say in your
   report which of the three you are in:

   - **updated** - you changed the diagnostic in this diff, and its new output is in the report;
   - **already covered** - the value flows through a derivation the diagnostic already consumes, so
     no edit was needed. **Name the derivation**, and say you confirmed it rather than assumed it;
     the confirmation is the work, and an unnamed one is indistinguishable from a guess;
   - **needed but out of bounds** - the file is **held by another lane**, or the brief did not give
     it to you. Then do not reach into it: another agent's file is not yours to edit mid-run. Write
     the required change precisely enough for the maintainer to sequence it - which check, what it
     says today, what it must say - and report it under `blocked`. An unstated third arm is how this
     becomes a rule that gets skipped silently.
"""

LIVE_BEFORE = [
    "**docs are part of the change.**",
    "a change nobody can discover is not shipped",
    "make sure the diagnostic reports it",
]

ANCHORS = [
    # the duty, stated as an action rather than as a value the config holds
    "open every path in `docs_targets` and report one line per path",
    # why there is no gate: the measurement, not an opinion -- and attributed to
    # the repository it was taken on, because this brief ships into repositories
    # whose merge history is not that one's. A fact about one repository never
    # lives in shared code; a labelled anecdote about a named one does.
    "measured on this plugin's own repository, against its last thirty merged pull requests",
    # the third state, named
    "an absent `docs` survey says nobody looked, not that the docs were fine",
    # the state most likely to be written without having been earned
    "with no reason is the sentence a run that never opened the file also writes",
]


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space.

    These documents wrap at 100 columns, so a multi-word anchor lands across a
    newline the moment a paragraph is reflowed. A checker whose finding is about
    its own reading, dressed as a finding about the file, is the defect this
    plugin is named after pointed at the test suite.
    """
    return " ".join(text.lower().split())


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


def test_the_brief_exists_and_is_prose():
    """Positive control for every `in` assertion below."""
    assert DEVELOPER.is_file(), "agents/developer.md is missing"
    assert len(_flatten(DEVELOPER.read_text(encoding="utf-8"))) > 8000


def test_the_negative_control_is_readable():
    """The must-fire half of the control pair on PRIOR."""
    assert _unmet(PRIOR, LIVE_BEFORE) == [], "PRIOR is not the pre-change section"


@pytest.mark.parametrize("anchor", ANCHORS)
def test_the_anchor_was_not_already_on_disk(anchor):
    """A guard that matched before the change is a guard with no teeth."""
    assert anchor not in _flatten(PRIOR), (
        "{!r} was already in the pre-change section".format(anchor)
    )


def test_the_brief_states_the_docs_duty_as_an_action():
    brief = DEVELOPER.read_text(encoding="utf-8")
    assert _unmet(brief, ANCHORS) == [], _unmet(brief, ANCHORS)


def test_the_brief_routes_the_duty_to_the_report_field():
    """The report-format section lists what goes where. A duty stated in section
    5 and missing from that list is a duty the writer meets twice and records
    once.
    """
    brief = _flatten(DEVELOPER.read_text(encoding="utf-8"))
    marker = "what the old prose report asked for has not changed, only where it goes"
    assert marker in brief, (
        "the report-format mapping sentence was not found -- this assertion is about "
        "its contents, so a mis-read of the document must fail here rather than pass "
        "the check below vacuously"
    )
    mapping = brief.split(marker, 1)[1][:600]
    assert "`docs`" in mapping, (
        "the report-format field mapping does not route the docs duty to `docs`: {!r}".format(
            mapping[:200]
        )
    )
