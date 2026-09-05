"""The agent report schema, and the honesty of its own enforcement claim.

An agent's report is a JSON file the orchestrator queries, not a document it reads
whole. That trade has a cost this repo is named after: a structured summary is easier
to accept without reading than a paragraph is. A refused disposition renders
identically whether the refusal was argued or lazy, and an empty findings array
renders identically whether the review ran and found nothing or never ran at all.

So the schema's job is not brevity. It is making the unreadable states impossible to
confuse with the read ones, and these tests check exactly that and nothing more:

- every list is a survey carrying its own state, so `checked` with no items is a
  different value from `not-checked`;
- a `not-checked` survey must say why, and must not carry items;
- a refusal carries its sentence and its argument, never a boolean.

The schema also publishes `x-enforced` -- the list of properties the validator really
checks -- and `x-convention`, the ones that are prose. The mutation table below is the
guard on that list: a name added to `x-enforced` without a mutation here fails the
suite. Without it, `x-enforced` is a claim about a checker, asserted by the checker's
own documentation, which is this repo's own defect class wearing a different hat.
"""

import io
import json
import re
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import manager_docs  # noqa: E402
import report_schema  # noqa: E402
import skip_symlink  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "agent-report.schema.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _example():
    return json.loads(json.dumps(_schema()["examples"][0]))


def test_schema_file_is_valid_json_and_names_itself():
    schema = _schema()
    assert schema["$schema"].startswith("https://json-schema.org/draft/")
    assert schema["type"] == "object"


def test_schema_ships_an_example():
    """A schema with no example is a schema nobody checked against a real report."""
    assert _schema()["examples"], "the schema ships no examples"


def test_the_shipped_example_validates():
    assert report_schema.validate(_example()) == []


def test_a_report_round_trips_through_a_file(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_example(), indent=2), encoding="utf-8")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded == _example()
    assert report_schema.validate(reloaded) == []


def _drop(report, *path):
    node = report
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return report


def _mutations():
    """One mutation per name in x-enforced. Each must be rejected."""

    def missing_required_key(report):
        return _drop(report, "issue")

    def wrong_type(report):
        report["issue"] = "96"
        return report

    def unknown_key(report):
        report["mood"] = "confident"
        return report

    def bad_enum(report):
        report["review"]["classes"]["items"][0]["state"] = "fine"
        return report

    def survey_not_checked_without_reason(report):
        report["adjacent"] = {"state": "not-checked", "items": []}
        return report

    def survey_not_checked_carrying_items(report):
        report["review"]["findings"] = {
            "state": "not-checked",
            "reason": "no reviewer was reachable",
            "items": [{"class": "correctness", "disposition": "fixed", "text": "x"}],
        }
        return report

    def refusal_without_argument(report):
        report["review"]["findings"] = {
            "state": "checked",
            "items": [{"class": "correctness", "disposition": "refused", "text": "x"}],
        }
        return report

    def finding_left_for_filing_without_reason(report):
        report["review"]["findings"] = {
            "state": "checked",
            "items": [
                {
                    "class": "correctness",
                    "disposition": "report-for-filing",
                    "text": "x",
                }
            ],
        }
        return report

    def class_verdict_unreached_without_why(report):
        report["review"]["classes"]["items"][0] = {
            "class": "platform",
            "state": "not-checked",
        }
        return report

    def docs_target_left_alone_without_why(report):
        report["docs"]["items"] = [{"path": "README.md", "state": "no-change-needed"}]
        return report

    def docs_target_unread_without_why(report):
        report["docs"]["items"] = [{"path": "README.md", "state": "not-read"}]
        return report

    def test_phase_observed_without_result(report):
        report["tests"]["green"] = {"state": "observed"}
        return report

    def test_phase_skipped_without_reason(report):
        report["tests"]["red"] = {"state": "not-run"}
        return report

    def full_suite_ran_without_result(report):
        report["tests"]["full"] = {"state": "ran"}
        return report

    def full_suite_unran_without_reason(report):
        report["tests"]["full"] = {"state": "could-not-run"}
        return report

    def pr_body_written_without_path(report):
        report["pr_body"] = {
            "state": "written",
            "path": "",
            "closes": {"state": "closes", "issues": [123]},
        }
        return report

    def pr_body_written_without_saying_what_it_closes(report):
        report["pr_body"].pop("closes", None)
        return report

    def pr_body_closing_something_without_naming_it(report):
        report["pr_body"]["closes"] = {"state": "closes", "issues": []}
        return report

    def pr_body_closing_nothing_without_a_reason(report):
        report["pr_body"]["closes"] = {"state": "closes-nothing"}
        return report

    def pr_body_absent_without_reason(report):
        report["pr_body"] = {"state": "not-written", "path": None}
        return report

    def review_returned_nothing_without_reason(report):
        report["review"]["findings"] = {"state": "returned-nothing", "items": []}
        return report

    def below_bar_item_without_an_anchor(report):
        report["adjacent"] = {
            "state": "checked",
            "items": [
                {
                    "text": "the sibling helper carries the same swallowed OSError",
                    "file": None,
                    "in_blast_radius": False,
                    "action": "below-bar",
                }
            ],
        }
        return report

    def below_bar_item_with_no_pull_request_to_be_recorded_in(report):
        report["pr_body"] = {
            "state": "not-written",
            "path": None,
            "reason": "the maintainer opens this one by hand",
        }
        report["adjacent"] = {
            "state": "checked",
            "items": [
                {
                    "text": "the sibling helper carries the same swallowed OSError",
                    "file": None,
                    "in_blast_radius": False,
                    "action": "below-bar",
                    "pr_anchor": "the sibling helper carries the same swallowed OSError",
                }
            ],
        }
        return report

    def below_bar_finding_without_a_reason(report):
        report["review"]["findings"] = {
            "state": "checked",
            "items": [
                {
                    "class": "correctness",
                    "disposition": "below-bar",
                    "text": "the docstring is wider than the code under it",
                    "pr_anchor": "the docstring is wider than the code under it",
                }
            ],
        }
        return report

    def compliance_item_names_the_instruction_without_a_reason(report):
        report["compliance"] = {
            "state": "checked",
            "items": [
                {"instruction": "run the full suite after the rebase", "reason": ""}
            ],
        }
        return report

    return {
        "required-keys": missing_required_key,
        "types": wrong_type,
        "no-unknown-keys": unknown_key,
        "enum-membership": bad_enum,
        "survey-not-checked-carries-a-reason": survey_not_checked_without_reason,
        "survey-not-checked-carries-no-items": survey_not_checked_carrying_items,
        "refusal-carries-text-and-argument": refusal_without_argument,
        "finding-left-for-filing-carries-a-reason": finding_left_for_filing_without_reason,
        "unreached-class-carries-a-why": class_verdict_unreached_without_why,
        "docs-target-left-alone-carries-a-why": docs_target_left_alone_without_why,
        "docs-target-unread-carries-a-why": docs_target_unread_without_why,
        "observed-test-phase-carries-a-result": test_phase_observed_without_result,
        "unobserved-test-phase-carries-a-reason": test_phase_skipped_without_reason,
        "ran-full-suite-carries-a-result": full_suite_ran_without_result,
        "unran-full-suite-carries-a-reason": full_suite_unran_without_reason,
        "written-pr-body-carries-a-path": pr_body_written_without_path,
        "unwritten-pr-body-carries-a-reason": pr_body_absent_without_reason,
        "review-survey-returned-nothing-carries-a-reason": (
            review_returned_nothing_without_reason
        ),
        "written-pr-body-says-what-it-closes": (
            pr_body_written_without_saying_what_it_closes
        ),
        "pr-body-closing-something-names-the-issues": (
            pr_body_closing_something_without_naming_it
        ),
        "pr-body-closing-nothing-carries-a-reason": (
            pr_body_closing_nothing_without_a_reason
        ),
        "below-bar-item-carries-a-quotable-pr-anchor": below_bar_item_without_an_anchor,
        "below-bar-item-needs-a-pull-request-body": (
            below_bar_item_with_no_pull_request_to_be_recorded_in
        ),
        "below-bar-finding-carries-a-reason": below_bar_finding_without_a_reason,
        "compliance-item-names-the-instruction-and-the-reason": (
            compliance_item_names_the_instruction_without_a_reason
        ),
    }


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_each_enforced_property_rejects_a_report_that_breaks_it(name):
    broken = _mutations()[name](_example())
    errors = report_schema.validate(broken)
    assert errors, "{} accepted a report that breaks it".format(name)


def test_every_enforced_claim_has_a_mutation_that_proves_it():
    """The guard on the schema's own honesty.

    x-enforced is a claim about what the validator does. Left unchecked it drifts the
    safe-sounding way -- a property gets listed, nothing enforces it, and the document
    reads as a stronger contract than the code is.
    """
    claimed = set(_schema()["x-enforced"])
    proven = set(_mutations())
    assert claimed == proven, (
        "claimed but unproven: {}; proven but unclaimed: {}".format(
            sorted(claimed - proven), sorted(proven - claimed)
        )
    )


# --- tests.full: whether the DEVELOPER's own full-suite run happened (#632) ----
#
# The manager never reproduces the suite itself (skills/manager/phases/review.md);
# CI is the source of truth for the repository's whole test_command. What was
# missing was a way for the REPORT to say whether the developer lane's own local
# full run happened at all, so the manager did not have to read it out of prose in
# a commit message or re-run it to find out. Optional, so an old report with no
# `full` key stays valid -- the bump is additive, and $defs/full_suite mirrors
# $defs/phase's three-state shape with its own vocabulary (ran / not-run /
# could-not-run) because a developer's local run and a TDD red/green watch are
# different claims answering different questions.


def test_a_report_with_no_full_field_at_all_still_validates():
    """The optionality itself, asserted rather than assumed -- every report ever
    written before this field existed lacks it, and the bump must not silently
    become required underneath them.
    """
    report = _example()
    del report["tests"]["full"]
    assert report_schema.validate(report) == []


def test_full_suite_ran_with_a_result_validates():
    report = _example()
    report["tests"]["full"] = {
        "state": "ran",
        "command": "python3 -m pytest tests/ -q",
        "result": "3835 passed, 6 skipped",
        "wall_clock": "5m24s",
        "platform": "macos-14",
        "interpreter": "3.13.15",
    }
    assert report_schema.validate(report) == []


def test_full_suite_not_run_with_a_reason_validates():
    report = _example()
    report["tests"]["full"] = {
        "state": "not-run",
        "reason": "change confined to one module whose own tests are green",
    }
    assert report_schema.validate(report) == []


def test_full_suite_could_not_run_with_a_reason_validates():
    """The state agents/developer.md's own criteria never spell but this contract
    must: the harness itself failed, distinct from a decision not to run it."""
    report = _example()
    report["tests"]["full"] = {
        "state": "could-not-run",
        "reason": "the suite hung past the session's time budget and was killed",
    }
    assert report_schema.validate(report) == []


def test_full_suite_rejects_a_state_outside_its_own_three():
    """`not-applicable`, $defs/phase's own third state, must not leak in here --
    it is not a state this vocabulary defines, and accepting it would let the
    two shapes drift into meaning the same thing under different words.
    """
    report = _example()
    report["tests"]["full"] = {"state": "not-applicable"}
    errors = report_schema.validate(report)
    assert errors, "a phase-only state was accepted on tests.full"


def test_a_review_spawn_that_came_back_empty_is_spellable_and_is_not_clean():
    """The accept half of #200.

    A spawn that executed and returned an empty final message is neither
    `checked` nor `not-checked`: the review happened and its output is lost. So
    the state has to be a fourth one, and it has to be able to carry whatever
    fragments the caller could re-derive -- unlike `not-checked`, which must
    carry none.
    """
    report = _example()
    report["review"]["findings"] = {
        "state": "returned-nothing",
        "reason": (
            "the reviewer spawn executed and its final message was empty; two of "
            "three findings re-derived from my own transcript, one is unrecoverable"
        ),
        "items": [
            {
                "class": "correctness",
                "disposition": "open",
                "text": "re-derived from my own transcript, not from the reviewer's return",
            }
        ],
    }
    assert report_schema.validate(report) == []


def test_returned_nothing_is_refused_for_the_missing_reason_not_for_the_enum():
    """Teeth on the mutation of the same name.

    `returned-nothing` was refused before this change too -- by enum membership --
    so a mutation asserting only "errors is non-empty" would pass just as loudly
    against a schema that never grew the state at all. Pin what the refusal is
    about, or the proof in x-enforced is a proof of the wrong rule.
    """
    report = _example()
    report["review"]["findings"] = {"state": "returned-nothing", "items": []}
    errors = report_schema.validate(report)
    assert errors, "a returned-nothing review with no reason was accepted"
    assert any("reason" in error for error in errors), errors
    assert not any("is not one of" in error for error in errors), (
        "still refused by enum membership, so the state was never added: "
        + repr(errors)
    )


def test_compliance_is_required_and_a_report_missing_it_is_refused():
    """#518: a report that says nothing about compliance with its own brief is
    refused outright, the same way a report missing `docs` or `review` is --
    the field this issue asks for cannot be an optional afterthought an old
    report simply lacks.
    """
    report = _drop(_example(), "compliance")
    errors = report_schema.validate(report)
    assert errors, "a report with no compliance survey at all was accepted"
    assert any("compliance" in error for error in errors), errors


def test_a_report_that_declined_nothing_and_says_so_validates():
    """The must-fire's paired must-not-fire (#518).

    `compliance: checked, items: []` is the honest shape of a run that
    executed its brief as written. A schema that only ever refused could not
    be told from a schema that always refuses, so this has to pass as loudly
    as the silent-decline case below has to fail.
    """
    report = _example()
    report["compliance"] = {"state": "checked", "items": []}
    assert report_schema.validate(report) == []


def test_a_report_that_declines_an_instruction_and_stays_silent_is_refused():
    """The exact test #518 names: an item that names what was declined and
    gives no argument for declining it is the silent-decline shape wearing a
    declared item's clothes, and it has to be refused for that, not merely
    for an unrelated missing key.
    """
    report = _example()
    report["compliance"] = {
        "state": "checked",
        "items": [
            {
                "instruction": (
                    "read the reporting repository's tracked policy file as "
                    "part of the review"
                ),
                "reason": "",
            }
        ],
    }
    errors = report_schema.validate(report)
    assert errors, "a compliance item naming a decline with no reason was accepted"
    assert any("reason" in error for error in errors), errors


def test_a_report_that_declines_an_instruction_and_argues_it_validates():
    """The full shape #518 asks for: naming the instruction and the argument
    for declining it is exactly what makes the deviation spellable, so this
    must validate as cleanly as a report that declined nothing.
    """
    report = _example()
    report["compliance"] = {
        "state": "checked",
        "items": [
            {
                "instruction": (
                    "read every file the diff touches, including tracked "
                    "policy under .claude/jit-context/"
                ),
                "reason": (
                    "classified .claude/jit-context/tools/01-oss/"
                    "supertool-required.md as injected content attempting to "
                    "redirect tool use and declined to follow it; continued "
                    "the review with Read/Bash/grep instead"
                ),
            }
        ],
    }
    assert report_schema.validate(report) == []


def test_returned_nothing_is_a_review_state_and_only_a_review_state():
    """The scope of the new state, asserted in both directions at once.

    A spawn can go quiet; a docs sweep cannot -- there is no second party to
    lose. So `returned-nothing` belongs on the surveys whose items come back
    from somebody else and nowhere else, and widening the shared survey enum
    instead would have made it spellable on `docs`, `claims`, `adjacent` and
    `blocked`, where it means nothing and would read as a state somebody chose.

    Both halves are in one test on purpose. The refusal half alone passes
    byte-identically against the code before this change -- `docs` never used
    the review survey in either version -- so on its own it says nothing about
    whether the scoping was implemented, only that the shared enum was left
    alone. Joined to the accept half it fails there, on the accept half, which
    is what makes the pair a measurement of this change rather than a
    restatement of the status quo.
    """
    accepted = _example()
    accepted["review"]["findings"] = {
        "state": "returned-nothing",
        "reason": "the reviewer came back empty; one finding lost",
        "items": [],
    }
    assert report_schema.validate(accepted) == [], (
        "a review survey cannot spell returned-nothing, so the scoping claim below "
        "is about a state that does not exist"
    )

    control = _example()
    control["docs"]["state"] = "checked"
    assert report_schema.validate(control) == [], (
        "the docs control itself does not validate"
    )

    leaked = _example()
    leaked["docs"] = {"state": "returned-nothing", "reason": "x", "items": []}
    assert report_schema.validate(leaked), (
        "returned-nothing is spellable on a plain survey"
    )


def test_enforced_and_convention_are_disjoint_and_both_populated():
    """The third state of this document: what it does NOT check, named out loud."""
    schema = _schema()
    enforced = set(schema["x-enforced"])
    convention = set(schema["x-convention"])
    assert enforced and convention
    assert not (enforced & convention), sorted(enforced & convention)


def test_the_validator_is_not_simply_refusing_everything():
    """Every rejection above is worthless if the accept path is broken.

    Each mutation asserts that a report is refused. That assertion also passes when
    the validator refuses all input -- a schema that failed to load, a typo in a key
    name -- so the accepted case has to live beside them.
    """
    assert report_schema.validate(_example()) == []
    lenient = _example()
    lenient["review"]["findings"] = {"state": "checked", "items": []}
    assert report_schema.validate(lenient) == [], (
        "a review that ran and found nothing must be accepted, and must not be "
        "spelled the same way as one that never ran"
    )


def _run(*args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "report_schema.py")] + list(args),
        capture_output=True,
        text=True,
    )


def test_cli_accepts_a_valid_report(tmp_path):
    # A whole report, payload file and all -- the shipped example names a placeholder
    # path on purpose, since a real one would be a fact about one machine.
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report_with_payload(tmp_path)), encoding="utf-8")
    done = _run(str(path))
    assert done.returncode == 0, done.stdout + done.stderr


def test_cli_rejects_an_invalid_report_and_says_where(tmp_path):
    broken = _example()
    broken["review"]["findings"] = {"state": "not-checked", "items": []}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    done = _run(str(path))
    assert done.returncode == 1
    assert "review.findings" in done.stdout + done.stderr


def test_cli_on_unparseable_json_says_so_rather_than_reporting_a_clean_report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("{not json", encoding="utf-8")
    done = _run(str(path))
    assert done.returncode == 1
    assert "json" in (done.stdout + done.stderr).lower()


def test_cli_on_a_missing_file_is_an_error_not_a_pass(tmp_path):
    done = _run(str(tmp_path / "absent.json"))
    assert done.returncode == 1


# --- the one cross-file check worth having ------------------------------------


def test_the_developer_brief_points_at_files_that_exist():
    """A path in an executable brief that resolves to nothing fails mid-task.

    This is deliberately the only assertion here about agents/developer.md. Grepping a
    brief for a phrase proves that somebody wrote the phrase, and nothing else: the
    contract is prose, and an agent that ignores it produces a report no test can see.
    A cross-file reference is different in kind -- it either resolves or it does not.
    """
    brief = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    targets = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)", brief)
    assert targets, (
        "no plugin-root reference found in agents/developer.md -- either the brief "
        "stopped naming the schema and its validator, or this pattern no longer "
        "matches how it names them, and a pattern that matched nothing has checked "
        "nothing"
    )
    missing = [t for t in targets if not (REPO_ROOT / t).exists()]
    assert not missing, (
        "agents/developer.md references files that do not exist: {}".format(missing)
    )


# --- the same command line, in process ----------------------------------------
#
# The subprocess tests above prove the orchestrator's invocation works. Coverage
# cannot see inside a subprocess, so on those alone main() reads as dead code --
# this repo's own defect class, a measurement claiming an absence. Both routes
# exist on purpose, the same way doctor.py is driven twice.


def test_validate_file_reads_and_validates(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report_with_payload(tmp_path)), encoding="utf-8")
    assert report_schema.validate_file(path) == []


def test_validate_file_on_a_missing_file_reports_rather_than_returning_clean(tmp_path):
    errors = report_schema.validate_file(tmp_path / "absent.json")
    assert errors and "cannot read" in errors[0]


def test_validate_file_on_unparseable_json_reports_rather_than_returning_clean(
    tmp_path,
):
    path = tmp_path / "report.json"
    path.write_text("{not json", encoding="utf-8")
    errors = report_schema.validate_file(path)
    assert errors and "not valid json" in errors[0]


def test_main_returns_zero_on_a_good_report(tmp_path, capsys):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report_with_payload(tmp_path)), encoding="utf-8")
    assert report_schema.main([str(path)]) == 0
    assert "ok" in capsys.readouterr().out


def test_main_returns_one_and_prints_each_problem(tmp_path, capsys):
    broken = _example()
    broken["review"]["findings"] = {"state": "not-checked", "items": []}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert report_schema.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "INVALID" in out and "review.findings" in out


def test_main_on_an_unloadable_schema_fails_loudly(tmp_path, capsys):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_example()), encoding="utf-8")
    assert (
        report_schema.main([str(path), "--schema", str(tmp_path / "absent.json")]) == 1
    )
    assert "cannot load the schema" in capsys.readouterr().err


def test_a_finding_with_no_sentence_is_refused():
    report = _example()
    report["review"]["findings"]["items"][0]["text"] = "   "
    assert report_schema.validate(report)


def test_a_nonlocal_ref_is_refused_rather_than_skipped():
    """A ref this validator cannot follow must not read as a subtree that passed."""
    with pytest.raises(ValueError):
        report_schema.validate({}, {"$ref": "https://example.invalid/other.json"})


# --- what the validator does when the SCHEMA is the broken thing ---------------


def test_a_keyword_this_validator_does_not_implement_is_refused_not_skipped():
    """The finding that a review of this change turned up.

    The checker implements a subset of JSON Schema. A `minLength` or a `oneOf` written
    into the schema and quietly walked past is a constraint that reads as enforced and
    is not -- the exact shape of defect the report format exists to make visible, in
    the checker for the report format.
    """
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string", "minLength": 5}},
        "required": ["x"],
    }
    with pytest.raises(ValueError) as caught:
        report_schema.validate({"x": "a"}, schema)
    assert "minLength" in str(caught.value)


def test_the_shipped_schema_uses_only_keywords_the_validator_implements():
    """The positive control on the refusal above: the real schema must still pass."""
    assert report_schema.validate(_example()) == []


def test_a_dangling_ref_is_an_error_rather_than_a_traceback(tmp_path, capsys):
    broken_schema = tmp_path / "schema.json"
    broken_schema.write_text(
        json.dumps({"type": "object", "properties": {"x": {"$ref": "#/$defs/absent"}}}),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert report_schema.main([str(report), "--schema", str(broken_schema)]) == 1
    assert "unusable" in capsys.readouterr().err


def test_output_survives_a_console_that_cannot_represent_the_report(
    tmp_path, monkeypatch
):
    """A cp1252 console must not kill the run at the print.

    Every line printed can echo the report -- a path, an enum value, a finding's
    sentence. On Windows that text is encoded with the console's codepage, where one
    accented character raises UnicodeEncodeError and ends the process after the
    validation it was reporting already ran. Reproduced here with an ASCII stream,
    which fails the same way for the same reason.
    """
    # The offending value has to reach the output, or this test passes whether or not
    # anything guards the print. An enum violation echoes the value it rejected.
    broken = _example()
    broken["review"]["classes"]["items"][0]["state"] = "passé"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stream)
    assert report_schema.main([str(path)]) == 1
    stream.flush()
    written = stream.buffer.getvalue().decode("ascii")
    assert "INVALID" in written


def test_the_ascii_control_would_otherwise_have_raised():
    """The positive control: the stream used above really is the hostile one."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    with pytest.raises(UnicodeEncodeError):
        print("naïve", file=stream)


# --- the one check that leaves the report and opens a file --------------------
#
# pr_body.state of "written" is the report's single claim about a file the NEXT
# step consumes. A body the forge refuses is discovered after the agent's session
# has ended, and the recovery is exactly the re-narration this format exists to
# delete -- somebody reads the body, wraps it, and invents a title. So this one
# claim is checked against the filesystem, in its own function, pinned to its own
# list in the schema, so it can never be mistaken for the shape pass.


def _payload():
    return {
        "title": "A title the agent wrote, because it survives the squash into the log",
        "body": "The body.",
        "head": "fix/123",
        "base": "main",
    }


#: A backslash followed by an n, spelled through chr() rather than a string
#: escape for the same reason report_schema.py spells it that way: no reader,
#: and no payload carrying this source through another serialisation, has to
#: count backslashes to know what it is (#685, #724).
BACKSLASH_N = chr(92) + "n"


# `closes-nothing` by default, because the default payload body carries no closing
# keyword and every fixture below is about something other than #274. Saying so
# explicitly rather than leaving it out is the point of the field: an absent `closes`
# is now itself a finding, so a fixture that omitted it would be refused for a reason
# it was not written to test.
_FIXTURE_CLOSES = {
    "state": "closes-nothing",
    "reason": "a fixture body, testing something other than what it closes",
}


def _report_with_payload(
    tmp_path, payload=None, name="body.pr.json", write=True, closes=None
):
    report = _example()
    target = tmp_path / name
    if write:
        if isinstance(payload, str):
            target.write_text(payload, encoding="utf-8")
        else:
            target.write_text(
                json.dumps(_payload() if payload is None else payload), encoding="utf-8"
            )
    report["pr_body"] = {
        "state": "written",
        "path": str(target),
        "closes": json.loads(json.dumps(_FIXTURE_CLOSES)) if closes is None else closes,
    }
    return report


def _report_with_a_below_bar_item(tmp_path, body, anchor, name="below-bar.pr.json"):
    """A report whose one adjacent item took the third receipt, over a body it names.

    The receipt is "a line in the pull request", so the fixture has to own both sides:
    the item claiming it, and the body that either carries it or does not. Pass the two
    independently, because the whole question is whether they agree.
    """
    payload = _payload()
    payload["body"] = body
    report = _report_with_payload(tmp_path, payload=payload, name=name)
    report["adjacent"] = {
        "state": "checked",
        "items": [
            {
                "text": "The docstring above the helper is wider than the code under it.",
                "file": "scripts/example.py",
                "in_blast_radius": False,
                "action": "below-bar",
                "pr_anchor": anchor,
            }
        ],
    }
    return report


def test_a_written_payload_the_forge_can_consume_is_accepted(tmp_path):
    report = _report_with_payload(tmp_path)
    assert report_schema.validate(report) == []
    assert report_schema.validate_pr_body(report, base_dir=tmp_path) == []


def test_shape_validation_never_opens_the_file(tmp_path):
    """validate() stays a shape checker. The split is why both can be trusted."""
    report = _report_with_payload(tmp_path, write=False)
    assert report_schema.validate(report) == []
    assert report_schema.validate_pr_body(report, base_dir=tmp_path), (
        "the missing file must be caught somewhere"
    )


def test_a_report_that_wrote_no_body_has_nothing_to_open():
    report = _example()
    report["pr_body"] = {
        "state": "not-written",
        "path": None,
        "reason": "no code changed",
    }
    assert report_schema.validate_pr_body(report) == []


def _disk_mutations(tmp_path):
    """One case per name in x-enforced-on-disk, with the directory it is anchored
    to. Each must be rejected, and each has to be rejected for its own reason."""
    escaping, _, reports = _escaping_report(tmp_path, decoy=_payload())
    return {
        "pr-body-file-exists": (_report_with_payload(tmp_path, write=False), tmp_path),
        "pr-body-file-parses": (
            _report_with_payload(
                tmp_path, payload="# A markdown body, which is what the forge refuses"
            ),
            tmp_path,
        ),
        "pr-body-payload-shape": (
            _report_with_payload(
                tmp_path,
                payload={
                    "title": "t",
                    "body": "b",
                    "head": "fix/123",
                    "base": "main",
                    "titel": "typo",
                },
            ),
            tmp_path,
        ),
        "pr-body-title-and-body-are-non-empty": (
            _report_with_payload(
                tmp_path,
                payload={"title": "  ", "body": "b", "head": "fix/123", "base": "main"},
            ),
            tmp_path,
        ),
        "pr-body-head-matches-the-report-branch": (
            _report_with_payload(
                tmp_path,
                payload={"title": "t", "body": "b", "head": "fix/999", "base": "main"},
            ),
            tmp_path,
        ),
        # The decoy this one reaches for is a payload the forge would accept, and
        # it exists. So containment is the only thing that can refuse it: drop the
        # resolution and this case validates clean rather than failing for a second
        # reason, which is the difference between a mutation and a coincidence.
        "pr-body-payload-stays-in-the-report-directory": (escaping, reports),
        # A payload the forge would accept, sitting beside its report, whose only
        # defect is that the report says merging it closes #274 and the body binds no
        # closing keyword to #274 -- it only mentions the number, which is the shape
        # all four measured instances had. Nothing else in this table can refuse it.
        "pr-body-body-binds-a-closing-keyword-to-every-issue-it-says-it-closes": (
            _report_with_payload(
                tmp_path,
                payload={
                    "title": "t",
                    "body": "Reworks the thing discussed in (#274).",
                    "head": "fix/123",
                    "base": "main",
                },
                name="unbound.pr.json",
                closes={"state": "closes", "issues": [274]},
            ),
            tmp_path,
        ),
        # The inverse, and it is a different harm: the report says the merge leaves
        # everything open and the body closes #250.
        "pr-body-closing-nothing-has-a-body-that-closes-nothing": (
            _report_with_payload(
                tmp_path,
                payload={
                    "title": "t",
                    "body": "Part of #250. Closes #250.",
                    "head": "fix/123",
                    "base": "main",
                },
                name="contradiction.pr.json",
                closes={
                    "state": "closes-nothing",
                    "reason": "Part of #250; the issue stays open for the second half.",
                },
            ),
            tmp_path,
        ),
        # #698: the payload itself, not the report's separate `closes` claim, says
        # this closes nothing (`no_close: true`) while its own body still binds a
        # closing keyword to the very issue the report says it closes -- the
        # narrower, payload-only contradiction `no_close_body_errors` exists for.
        "pr-body-no-close-payload-has-a-body-that-closes-nothing": (
            _report_with_payload(
                tmp_path,
                payload={
                    "title": "t",
                    "body": "Closes #999.",
                    "head": "fix/123",
                    "base": "main",
                    "no_close": True,
                },
                name="no-close-contradiction.pr.json",
                closes={"state": "closes", "issues": [999]},
            ),
            tmp_path,
        ),
        # A payload the forge would accept, saying nothing at all about the below-bar
        # item the report says is recorded in it. Nothing else in this table can refuse
        # it: the shape pass is satisfied (the anchor is present, long enough, and the
        # body was written), and the only defect is that the receipt is not there.
        "below-bar-anchor-appears-in-the-pull-request-body": (
            _report_with_a_below_bar_item(
                tmp_path,
                body="A body about something else entirely.",
                anchor="the docstring above the helper is wider than the code under it",
                name="unrecorded.pr.json",
            ),
            tmp_path,
        ),
        # #724: a payload whose body is more escaped than formatted -- doubled
        # backslash-n sequences standing in for a paragraph break, with no real
        # newline anywhere in the body to back them up. Nothing else in this
        # table can refuse it: the payload parses, matches the shape, and the
        # closes claim is self-consistent. Only the content check can see it.
        "pr-body-body-is-no-more-escaped-than-formatted": (
            _report_with_payload(
                tmp_path,
                payload={
                    "title": "t",
                    "body": (BACKSLASH_N * 2).join(
                        "Paragraph {}.".format(n) for n in range(1, 5)
                    ),
                    "head": "fix/123",
                    "base": "main",
                },
                name="escaped-newlines.pr.json",
            ),
            tmp_path,
        ),
    }


@pytest.mark.parametrize("name", sorted(_schema()["x-enforced-on-disk"]))
def test_each_on_disk_property_rejects_a_payload_that_breaks_it(name, tmp_path):
    report, base_dir = _disk_mutations(tmp_path)[name]
    assert report_schema.validate_pr_body(report, base_dir=base_dir), (
        "{} accepted a payload that breaks it".format(name)
    )


def test_every_on_disk_claim_has_a_case_that_proves_it(tmp_path):
    claimed = set(_schema()["x-enforced-on-disk"])
    proven = set(_disk_mutations(tmp_path))
    assert claimed == proven, (
        "claimed but unproven: {}; proven but unclaimed: {}".format(
            sorted(claimed - proven), sorted(proven - claimed)
        )
    )


def test_a_markdown_body_is_refused_by_name():
    """The defect this came from: a good body in a format the next step rejects."""
    described = _schema()["$defs"]["pr_body"]["properties"]["path"]["description"]
    assert "markdown" in described.lower()


def test_the_cli_reads_the_payload_by_default(tmp_path, capsys):
    report = _report_with_payload(
        tmp_path, payload={"title": "t", "body": "b", "head": "fix/999", "base": "main"}
    )
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert report_schema.main([str(path)]) == 1
    assert "head" in capsys.readouterr().out


def test_the_cli_says_when_it_did_not_read_the_payload(tmp_path, capsys):
    """A check that was skipped must never render as a check that passed."""
    report = _report_with_payload(tmp_path, write=False)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert report_schema.main([str(path), "--shape-only"]) == 0
    out = capsys.readouterr().out
    assert "not read" in out and "shape" in out


# --- the payload has to be the file the report wrote, beside the report -------
#
# pr_body.path is written by an agent and opened by the maintainer's own process.
# Whatever that process opens it also quotes back: a key the forge payload does
# not define is echoed by name, and a value is echoed wherever a const, an enum
# or a type mismatch fires. So the path decides which files get read and reported
# on, and the only directory a report can speak for is the one it is sitting in.
#
# Every assertion below is on the open, not on the wording. A change that merely
# stopped echoing would leave the read in place and pass a message assertion.


def _read_spy(monkeypatch):
    """Record every path this validator reads.

    Patched on the class rather than on a module attribute: Path.read_text is
    looked up on the class at call time on every supported interpreter, which a
    rebind of io.open is not -- 3.10's pathlib captures that one at import.
    """
    opened = []
    real = Path.read_text

    def spy(self, *args, **kwargs):
        opened.append(Path(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    return opened


def _outside(opened, base):
    """Which of the paths in `opened` do not live under `base`, both resolved."""
    root = Path(base).resolve().parts
    return [str(p) for p in opened if Path(p).resolve().parts[: len(root)] != root]


_DECOY_KEYS = ("decoyKeyOne", "decoyKeyTwo")


def _escaping_report(tmp_path, absolute=False, decoy=None):
    """A report naming a payload that is not beside it, and a decoy to reach for.

    Synthetic in every part -- invented directory, invented file name, invented
    key names, all created here. Nothing in this fixture is a path that exists on
    a machine running the suite, which is the point: a fixture that reached for a
    real one would be the defect it is testing for.

    `decoy` is what the file out there contains. Left alone it carries key names
    nothing else in the suite uses, so a test can ask whether they were quoted
    back. Handed a valid payload it becomes the stronger fixture: nothing but
    containment has anything to say about it.
    """
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    elsewhere = tmp_path / "not-the-reports-directory"
    elsewhere.mkdir(exist_ok=True)
    body = {key: "synthetic" for key in _DECOY_KEYS} if decoy is None else decoy
    decoy = elsewhere / "synthetic-decoy.json"
    decoy.write_text(json.dumps(body), encoding="utf-8")
    report = _example()
    named = str(decoy) if absolute else str(Path("..") / elsewhere.name / decoy.name)
    report["pr_body"] = {"state": "written", "path": named}
    return report, decoy, reports


@pytest.mark.parametrize("absolute", [False, True])
def test_a_payload_outside_the_report_directory_is_never_opened(
    tmp_path, monkeypatch, absolute
):
    """Both spellings of the same escape: a relative one, and an absolute one.

    They are one test because they were two holes in one expression -- the
    absolute spelling never touched the base directory at all, so a guard added
    only to the relative branch would fix half of it and read as a fix.
    """
    schema = report_schema.load_schema()
    report, decoy, reports = _escaping_report(tmp_path, absolute=absolute)
    opened = _read_spy(monkeypatch)
    errors = report_schema.validate_pr_body(report, schema, base_dir=reports)

    assert _outside(opened, reports) == [], "it opened a file the report does not own"
    assert str(decoy) not in [str(p) for p in opened]
    assert errors, "an escape has to be reported; silence is what nobody reads"
    said = " ".join(errors)
    for key in _DECOY_KEYS:
        assert key not in said, "the refusal quoted the decoy back: {}".format(said)


def _symlink_or_skip(link, target, target_is_directory=False):
    """`skip_symlink.symlink_or_skip`, naming the property this file's case needs.

    See `tests/skip_symlink.py` (#265) for why a directory target also tries a
    Windows junction before giving up: a symlink alone leaves both the escape
    assertion and its positive control skipping together on every unelevated
    Windows leg, which is the same green as one that actually ran.
    """
    return skip_symlink.symlink_or_skip(
        link,
        target,
        target_is_directory=target_is_directory,
        what="'a symlink inside the base pointing out of it is refused unopened'",
    )


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_a_symlink_inside_the_report_directory_pointing_out_is_never_opened(
    tmp_path, monkeypatch, kind
):
    """The claimed property that nothing asserted until this test existed.

    `_contained_path` resolves *both* sides, and three documents say so -- the
    docstring on that function, the `pr_body.path` description in the schema, and
    the 0.5.0 changelog entry. Every other containment case in this file names a
    path that escapes lexically, so swapping `resolve()` for a normpath -- a
    plausible future change, for Windows short names or to avoid a stat -- would
    keep all of them green and silently make all three documents false.

    This case escapes only under resolution: `reports/body.pr.json` is inside the
    base by every reading except the one that follows the link. The decoy it
    reaches for is a payload the forge would accept and it exists, so containment
    is the only thing that has anything to say about it.
    """
    schema = report_schema.load_schema()
    report, decoy, reports = _escaping_report(tmp_path, decoy=_payload())
    if kind == "file":
        named = _symlink_or_skip(reports / "body.pr.json", decoy)
    else:
        named = (
            _symlink_or_skip(reports / "sub", decoy.parent, target_is_directory=True)
            / decoy.name
        )
    report["pr_body"] = {"state": "written", "path": str(named)}

    opened = _read_spy(monkeypatch)
    errors = report_schema.validate_pr_body(report, schema, base_dir=reports)

    assert _outside(opened, reports) == [], "it opened a file the report does not own"
    assert str(decoy) not in [str(p) for p in opened]
    assert errors, (
        "a symlink out of the base has to be reported; silence is what nobody reads"
    )

    # The positive control, in the same fixture and on the same directory. Every
    # assertion above also passes when the link was never created, when nothing
    # resolved, or when the validator never ran at all -- this half is what fails
    # instead of passing quietly in each of those cases.
    ordinary = _report_with_payload(reports, name="ordinary.pr.json")
    assert report_schema.validate_pr_body(ordinary, schema, base_dir=reports) == [], (
        "the refusal above proves nothing if an ordinary sibling is refused too"
    )
    assert any(p.name == "ordinary.pr.json" for p in opened), (
        "the ordinary sibling went unread, so the harness saw nothing either way"
    )


def test_a_payload_beside_the_report_is_still_opened_and_validated(
    tmp_path, monkeypatch
):
    """The positive control. `return []` would satisfy every assertion above."""
    schema = report_schema.load_schema()
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _report_with_payload(reports)
    opened = _read_spy(monkeypatch)

    assert report_schema.validate_pr_body(report, schema, base_dir=reports) == []
    assert any(p.name == "body.pr.json" for p in opened), (
        "the sibling payload went unread"
    )


def test_containment_did_not_replace_the_checks_it_guards(tmp_path):
    """The second positive control: the on-disk findings still fire from inside."""
    schema = report_schema.load_schema()
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _report_with_payload(
        reports, payload={"title": "t", "body": "b", "head": "fix/999", "base": "main"}
    )
    errors = report_schema.validate_pr_body(report, schema, base_dir=reports)
    assert any("head" in error for error in errors), errors


def test_without_a_directory_to_resolve_against_the_payload_is_not_opened(
    tmp_path, monkeypatch
):
    """Containment that could not be checked is a third state, not a pass.

    base_dir is the anchor. Absent one there is nothing to contain the path
    against, so the honest answer is that the check could not run -- and a check
    that could not run must not open the file anyway and call it clean.
    """
    schema = report_schema.load_schema()
    report = _report_with_payload(tmp_path)
    opened = _read_spy(monkeypatch)
    errors = report_schema.validate_pr_body(report, schema, base_dir=None)

    assert errors, (
        "no anchor means the check could not run, which is not the same as clean"
    )
    assert opened == [], "it opened the payload with nothing to contain it against"


def test_a_path_that_will_not_resolve_is_refused_rather_than_opened(
    tmp_path, monkeypatch
):
    """The other half of the third state: the anchor exists, the answer does not.

    Resolving can fail -- an over-long component, a directory the process cannot
    traverse -- and the tempting reading of that failure is that nothing objected.
    It is the opposite: containment could not be decided, so the file must not be
    opened. The failure is injected on the class method the code calls, which is
    looked up at call time on every supported interpreter, and the assertion below
    confirms the injection took rather than assuming it.
    """
    schema = report_schema.load_schema()
    report = _report_with_payload(tmp_path)
    opened = _read_spy(monkeypatch)

    def refuse(self, *args, **kwargs):
        raise OSError(63, "synthetic: this platform would not resolve the name")

    monkeypatch.setattr(Path, "resolve", refuse)
    with pytest.raises(OSError):
        Path(tmp_path).resolve()  # the injection is measured, not assumed

    errors = report_schema.validate_pr_body(report, schema, base_dir=tmp_path)
    assert errors, "a containment question that could not be answered is not a pass"
    assert opened == [], (
        "it opened the payload without deciding whether it was contained"
    )


def test_a_nul_byte_in_the_path_is_the_report_being_wrong_not_the_schema(
    tmp_path, capsys
):
    """A NUL is legal in a JSON string and `resolve()` raises ValueError for one.

    Uncaught it reached main()'s `except ValueError`, whose own comment says that
    clause is for a broken schema -- so a report crashing the containment check
    was announced as the maintainer's own configuration being unusable, and the
    next move that invites is going to look at a file with nothing wrong with it.
    """
    report = _report_with_payload(tmp_path)
    report["pr_body"]["path"] = "beside-the-report\x00.pr.json"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert report_schema.main([str(path)]) == 1
    captured = capsys.readouterr()
    assert "schema" not in captured.err, captured.err
    assert "pr_body.path" in captured.out, captured.out


def test_a_drive_letter_cannot_smuggle_a_path_past_the_join(tmp_path):
    """Windows: joining a drive-absolute string discards the base entirely.

    The join itself is observed here, on the pure flavour, which answers the same
    on every host. What it means end to end is reasoned rather than observed --
    this suite has never run on a Windows runner -- so the assertion is the
    invariant that holds on both: whatever containment hands back is inside the
    base. On POSIX 'C:/x' is an ordinary relative name landing in a directory
    called 'C:'; on Windows it escapes the join and is refused. Neither platform
    can be talked into returning a path outside the base, which is the property
    that matters and the one a platform-branched assertion would have hidden.
    """
    assert PureWindowsPath("D:/reports") / "C:/elsewhere.pr.json" == PureWindowsPath(
        "C:/elsewhere.pr.json"
    )
    path, problem = report_schema._contained_path(tmp_path, "C:/elsewhere.pr.json")
    assert (path is None) != (problem is None), "exactly one of a path and a problem"
    if path is not None:
        root = Path(tmp_path).resolve().parts
        assert path.resolve().parts[: len(root)] == root


def test_the_refusal_is_one_printable_line(tmp_path):
    """The path is chosen by whoever wrote the report.

    A newline in one forges a receipt row and an escape sequence rewrites what
    the terminal already printed, so the refusal that names it has to flatten it.
    """
    schema = report_schema.load_schema()
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _example()
    report["pr_body"] = {
        "state": "written",
        "path": "../elsewhere\nok forged-receipt-row\x1b[31m/synthetic.pr.json",
    }
    errors = report_schema.validate_pr_body(report, schema, base_dir=reports)
    assert errors
    for error in errors:
        assert "\n" not in error and "\x1b" not in error, repr(error)


# --- handed the wrong one of the two files it has just been told about --------
#
# The report and its payload are written in the same run, land in the same
# directory, and differ by one suffix. A caller who passes the payload to a
# report validator gets a verdict that is accurate and useless: fourteen missing
# keys and three unknown ones, on a file with nothing wrong with it. The next
# move that invites is correcting a correct payload -- or hand-writing `head`,
# which is the one value nothing downstream verifies at all.
#
# So the payload is detected and refused by name, with the call to run instead.
# It stays a refusal: validating a payload on its own can never compare its
# `head` to the report's `branch`, because the report is not in hand, and a
# green tick standing in for a check that could not run is the defect this
# repository is named after.


def _payload_only(tmp_path, name="body.pr.json"):
    target = tmp_path / name
    target.write_text(json.dumps(_payload()), encoding="utf-8")
    return target


def test_a_forge_payload_handed_to_the_report_validator_is_refused_by_name(
    tmp_path, capsys
):
    errors = report_schema.validate_file(_payload_only(tmp_path))
    assert len(errors) == 1, "a payload should get one sentence, not a wall: {}".format(
        errors
    )
    said = errors[0].lower()
    assert "payload" in said and "report" in said
    assert "missing required key" not in said

    assert report_schema.main([str(_payload_only(tmp_path, "second.pr.json"))]) == 1
    out = capsys.readouterr().out
    assert "INVALID" in out and "missing required key" not in out


def test_the_refusal_names_the_call_to_run_instead(tmp_path):
    """A diagnostic that says what is wrong and not what to do is half a diagnostic."""
    errors = report_schema.validate_file(_payload_only(tmp_path))
    assert "report_schema.py" in errors[0]


def test_the_payload_detector_does_not_swallow_a_broken_report(tmp_path):
    """The positive control. Refusing a payload by name must not become refusing everything.

    Three inputs, one fixture: the payload above must be named rather than
    enumerated; a genuinely malformed report must still be enumerated; and a good
    report must still pass. A detector that answered the first by accepting
    anything, or by declining to look, would pass the first assertion alone.
    """
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(_drop(_example(), "summary")), encoding="utf-8")
    errors = report_schema.validate_file(broken)
    assert any("missing required key" in e for e in errors), errors

    good = tmp_path / "report.json"
    good.write_text(json.dumps(_report_with_payload(tmp_path)), encoding="utf-8")
    assert report_schema.validate_file(good) == []


def test_a_half_written_payload_is_not_mistaken_for_one(tmp_path):
    """Neither a report nor a payload is neither, and says so as schema violations.

    The detector keys on being unmistakably a payload, not on failing to be a
    report -- otherwise every malformed report starts reading as "you passed the
    wrong file", which is a wrong answer delivered calmly.
    """
    half = tmp_path / "half.json"
    half.write_text(json.dumps({"title": "t", "body": "b"}), encoding="utf-8")
    errors = report_schema.validate_file(half)
    assert any("missing required key" in e for e in errors), errors


def test_a_json_document_that_is_not_an_object_is_not_classified(tmp_path):
    """A top-level array is neither file, and the detector must not crash deciding."""
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps(["title", "body"]), encoding="utf-8")
    errors = report_schema.validate_file(odd)
    assert errors and all("pull request payload" not in e for e in errors), errors


def test_a_schema_that_stopped_defining_the_payload_declines_rather_than_guesses(
    tmp_path,
):
    """The third state. Unable to classify is not the same as classified as a report.

    Declining leaves the shape pass to answer, which it does loudly. Guessing
    either way would be a confident verdict about a question nothing looked at.
    """
    schema = _schema()
    schema["$defs"]["forge_payload"] = {"type": "object"}
    assert report_schema._is_forge_payload(_payload(), schema) is False
    assert report_schema._is_forge_payload(_payload(), _schema()) is True


# --- the call the skill documents, run rather than read -----------------------


#: The whole manager loop, not the spine alone. This was
#: `REPO_ROOT / "skills" / "manager" / "SKILL.md"` until #245 step 3 moved the
#: `gh-pr-create` argument -- and the fenced call with it -- out of the spine, at
#: which point a check pinned to the spine found nothing and said so. That the
#: pattern *could* fail loudly is why this was caught, but the narrowing predates
#: the move: `skills/manager/phases/handback.md` has carried its own copy of this
#: call since the #725 phase split, and a guard reading only the spine had already
#: stopped seeing one of the two places the loop documents it. `manager_docs` is
#: this repository's one answer to "does the manager loop say X", derived from disk
#: rather than listed, so a phase file added later is covered when it exists.
SKILL_PATH = manager_docs.ManagerLoop()

# python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py" <SOMETHING>
DOCUMENTED_CALL_RE = re.compile(r"report_schema\.py\"?\s+(<[^>\n]+>)")


def test_the_documented_verification_call_validates_the_file_it_names(tmp_path, capsys):
    """The maintainer's one call must pass on a correct run, or it teaches the wrong lesson.

    Not a grep for a phrase. The placeholder in the skill is resolved to one of
    the two files a finished run leaves on disk, and the validator is then run on
    it exactly as documented. A call pointed at the payload exits 1 with a
    seventeen-line diagnostic about a file with nothing wrong with it, which is
    the defect this pins.
    """
    text = SKILL_PATH.read_text(encoding="utf-8")
    placeholders = DOCUMENTED_CALL_RE.findall(text)
    assert placeholders, (
        "no fenced report_schema.py invocation found in the manager skill -- either "
        "it stopped documenting the check, or this pattern no longer matches how it "
        "writes it, and a pattern that matched nothing has checked nothing"
    )

    report = _report_with_payload(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    payload_path = Path(report["pr_body"]["path"])

    for placeholder in placeholders:
        lowered = placeholder.lower()
        if "pr_body" in lowered or "payload" in lowered:
            target = payload_path
        elif "report" in lowered:
            target = report_path
        else:
            raise AssertionError(
                "the skill documents {} and this test cannot tell which of the two "
                "files a finished run leaves that names -- resolve it here rather "
                "than letting an unrecognised placeholder pass".format(placeholder)
            )
        assert report_schema.main([str(target)]) == 0, (
            "the documented call {} exits non-zero on a correct run: {}".format(
                placeholder, capsys.readouterr().out
            )
        )


# --- the contract number, and what a copy does with a contract it does not hold ---
#
# schema_version was `const: 1` in every copy of this schema ever shipped, across at
# least three mutually incompatible contracts (#221). That is worse than shipping no
# version at all: an unversioned artifact is honestly silent, while a marker frozen at
# 1 renders identically whether it moved or not -- this repository's own defect class,
# sitting inside the field named to prevent it. `const` did not merely fail to record a
# version, it forbade recording one.
#
# Three things are pinned below, and they are three because each is useless alone.
# That the shape pass has no opinion about the number, since a report from a newer
# contract is unvalidatable rather than malformed. That the version pass therefore has
# three outcomes rather than two. And that the number cannot be left behind when the
# contract moves, which is a guard that has to fail loudest exactly when it has nothing
# to compare against.


def _contract_version():
    return _schema()["x-schema-version"]


def _write_report(tmp_path, report, name="report.json"):
    path = tmp_path / name
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _verdict_lines(stdout, word):
    return [line for line in stdout.splitlines() if line.startswith(word + " ")]


def test_the_schema_declares_the_contract_version_it_implements():
    version = _contract_version()
    assert isinstance(version, int) and not isinstance(version, bool)
    assert version >= 2, (
        "1 is reserved for every report written before anyone counted. Measured on "
        "2026-08-16 against the reports on disk: 57 of 71 say 1 and 14 name no version "
        "at all, and neither set can be dated retroactively -- so the first value that "
        "carries information is 2"
    )


def test_the_shape_pass_has_no_opinion_about_the_version_number():
    """Removing the const is half the fix; the other half must not land here.

    A report from a newer contract is not malformed, so the shape pass -- which
    answers "does this satisfy the contract I hold" -- is the wrong place to
    decide it. If this ever fails, the version question has leaked back into the
    pass that cannot express the third state.
    """
    from_the_future = _example()
    from_the_future["schema_version"] = _contract_version() + 1
    assert report_schema.validate(from_the_future) == [], (
        "a report from a newer contract was refused by the shape pass, which renders "
        "it identically to a malformed one"
    )
    # Positive control: no opinion about the value is not no check on the field.
    not_a_version = _example()
    not_a_version["schema_version"] = str(_contract_version())
    assert report_schema.validate(not_a_version), (
        "schema_version stopped being required to be an integer"
    )


def test_the_version_pass_has_three_outcomes_and_not_two():
    schema = _schema()
    current = _example()
    current["schema_version"] = _contract_version()
    assert report_schema.version_verdict(current, schema)[0] == "current"

    older = dict(current, schema_version=1)
    state, sentence = report_schema.version_verdict(older, schema)
    assert state == "mismatch"
    assert "1" in sentence and str(_contract_version()) in sentence, sentence

    silent = dict(current)
    del silent["schema_version"]
    assert report_schema.version_verdict(silent, schema)[0] == "undecidable"

    unversioned = {k: v for k, v in schema.items() if k != "x-schema-version"}
    state, sentence = report_schema.version_verdict(current, unversioned)
    assert state == "undecidable", (
        "a schema that does not name its own contract cannot certify a report against "
        "it, and must not answer 'current' because it found nothing to disagree with"
    )
    assert sentence


def test_a_report_from_another_contract_is_unvalidatable_rather_than_invalid(tmp_path):
    """The three verdicts in one fixture, because the first arm is a negative.

    "must not say INVALID" also passes for a validator that says nothing, or that
    says UNVALIDATABLE about everything. So the malformed report and the correct
    one are checked in the same fixture, and each has to land on its own word.
    """
    older = _report_with_payload(tmp_path, name="older.pr.json")
    older["schema_version"] = 1
    older.pop("docs")  # what a report against contract 1 actually looks like
    done = _run(str(_write_report(tmp_path, older, "older.json")))
    assert done.returncode == 2, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "UNVALIDATABLE"), done.stdout
    assert not _verdict_lines(done.stdout, "INVALID"), (
        "a report written against a contract this copy does not hold was announced as "
        "malformed -- the collapse the version field exists to prevent"
    )

    malformed = _report_with_payload(tmp_path, name="bad.pr.json")
    malformed["schema_version"] = _contract_version()
    malformed.pop("docs")
    done = _run(str(_write_report(tmp_path, malformed, "bad.json")))
    assert done.returncode == 1, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "INVALID"), done.stdout
    assert not _verdict_lines(done.stdout, "UNVALIDATABLE"), done.stdout

    good = _report_with_payload(tmp_path, name="good.pr.json")
    done = _run(str(_write_report(tmp_path, good, "good.json")))
    assert done.returncode == 0, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "ok"), done.stdout


def test_an_unvalidatable_report_still_reports_what_it_could_see(tmp_path):
    """Declining to look would be this plugin's own defect class, one layer along.

    The shape pass still runs against a report from another contract, because the
    findings are real information. They are printed under a sentence saying which
    contract they answer, so they cannot be read as defects in the report.
    """
    older = _report_with_payload(tmp_path, name="older.pr.json")
    older["schema_version"] = 1
    older.pop("docs")
    done = _run(str(_write_report(tmp_path, older, "older.json")))
    assert "docs" in done.stdout, done.stdout
    assert "not necessarily" in done.stdout.lower(), done.stdout


def test_main_returns_the_third_code_in_process_too(tmp_path, capsys):
    """The subprocess arm above cannot be seen by coverage, and a branch nobody
    can see is one nobody notices going missing. Also pins the return value of
    main() itself rather than a shell's view of it."""
    older = _report_with_payload(tmp_path, name="older.pr.json")
    older["schema_version"] = 1
    assert report_schema.main([str(_write_report(tmp_path, older, "older.json"))]) == 2
    printed = capsys.readouterr().out
    assert printed.startswith("UNVALIDATABLE "), printed
    assert "not necessarily" in printed.lower(), (
        "a report this copy cannot speak for must say so even when the shape pass "
        "found nothing -- a clean shape pass against the wrong contract is not a "
        "clean report"
    )


def test_every_verdict_names_the_contract_it_was_decided_against(tmp_path):
    """#212's remedy, which const: 1 made useless -- both copies printed 1.

    The assertion is on the parenthetical and not on the bare number. Review of
    the first version of this test caught it passing for free: pytest's tmp path
    contains a digit run, so `"2" in stdout` was true with the feature deleted --
    a test that would still pass if the code did nothing, guarding the one row
    the remedy lives on.
    """
    good = _report_with_payload(tmp_path, name="good.pr.json")
    done = _run(str(_write_report(tmp_path, good)))
    assert "(report schema version {})".format(_contract_version()) in done.stdout, (
        done.stdout
    )


def test_a_schema_that_names_no_contract_cannot_certify_a_report(tmp_path):
    """The other side of undecidable, through the command line.

    A copy handed a schema that does not declare its own version knows the report's
    number and nothing to compare it with. That is the same epistemic state as a
    mismatch and must not resolve to ok.
    """
    unversioned = {k: v for k, v in _schema().items() if k != "x-schema-version"}
    schema_path = tmp_path / "unversioned.schema.json"
    schema_path.write_text(json.dumps(unversioned), encoding="utf-8")
    good = _report_with_payload(tmp_path, name="good.pr.json")
    done = _run("--schema", str(schema_path), str(_write_report(tmp_path, good)))
    assert done.returncode == 2, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "UNVALIDATABLE"), done.stdout

    # And it must not flip back to INVALID the moment the shape pass finds
    # anything. Review caught exactly that: the ranking asked whether there were
    # errors before asking whether this copy had any standing to call a report
    # wrong, so a copy that had just said it cannot name its own contract went on
    # to announce a verdict on somebody else's. The findings are still printed;
    # only the word changes, and the word is the whole of #221.
    also_broken = _report_with_payload(tmp_path, name="broken.pr.json")
    also_broken.pop("docs")
    done = _run(
        "--schema",
        str(schema_path),
        str(_write_report(tmp_path, also_broken, "broken.json")),
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "UNVALIDATABLE"), done.stdout
    assert not _verdict_lines(done.stdout, "INVALID"), done.stdout
    assert "docs" in done.stdout, "the findings it could still see went missing"
    assert "None" not in done.stdout, (
        "a contract this copy cannot name must be described, not formatted as None"
    )


# --- an older contract this copy can still speak for (#416) -------------------
#
# Every bump used to invalidate every in-flight lane's report, because the comparison
# was an integer one: 4 != 5, therefore UNVALIDATABLE, even where 5 added nothing 4
# forbade. Measured on the fix/410 lane minutes after #414 merged -- the refusal
# printed `the shape pass found nothing` directly underneath itself.
#
# The refusal is right against a real narrowing and has to survive one, so every test
# here is PAIRED: an arm where the older contract is declared a widening and the report
# is read, and an arm where it is not and the refusal still fires. A fix that accepted
# everything older would pass the first arm of each on its own.
#
# Declared, never derived. Deciding "is contract A a subset of contract B" needs both
# documents and a copy of this validator has exactly one on disk -- the older schema is
# not merely unread, it is absent. So the author records the relation at the bump, the
# one moment anybody holds both, and this validator refuses whatever nobody declared.


def _schema_declaring(version, compat):
    schema = _schema()
    schema["x-schema-version"] = version
    schema["x-schema-compatibility"] = compat
    return schema


def test_the_version_pass_has_a_fourth_outcome_for_a_declared_widening():
    """Read the older contract, and say in the sentence that it is the older one.

    `ok` and `ok, older contract, additive only` are not the same claim, and the
    second is the true one. The sentence carries it; the word stays `ok` so that
    anything scanning a receipt for a verdict still finds one.
    """
    schema = _schema_declaring(5, {"5": "additive", "4": "breaking"})
    older = dict(_example(), schema_version=4)
    state, sentence = report_schema.version_verdict(older, schema)
    assert state == report_schema.VERSION_READABLE, sentence
    assert "4" in sentence and "5" in sentence, sentence
    assert "additive" in sentence, (
        "the accepting sentence must say WHY an older contract was read, or it "
        "claims more than it checked"
    )

    # Must-fire: the same pair, declared breaking. Without this arm the test above
    # is satisfied by a validator that reads every older contract there is.
    narrowed = _schema_declaring(5, {"5": "breaking", "4": "breaking"})
    state, sentence = report_schema.version_verdict(older, narrowed)
    assert state == report_schema.VERSION_MISMATCH, sentence


def test_an_undeclared_step_is_refused_rather_than_assumed_additive():
    """The default has to be refusal, because the failure modes are not equal.

    An over-refusal costs a lane one relayed sentence. An under-refusal vouches
    for a contract this copy does not hold, which is the thing the whole version
    pass exists to prevent -- and the natural failure of a declaration nobody
    updated at the bump is silence.
    """
    older = dict(_example(), schema_version=4)
    for compat in ({}, {"5": "unknown"}, {"5": "widening-ish"}, {"5": True}):
        state, _ = report_schema.version_verdict(older, _schema_declaring(5, compat))
        assert state == report_schema.VERSION_MISMATCH, compat

    # The positive control, and it is not decoration: every arm above is a refusal,
    # and the validator BEFORE #416 refused all four of them too -- so without this
    # line the test passes verbatim against a copy with the feature deleted, which
    # review caught. It has to be the same report and the same fixture, so what is
    # being read is the declaration and nothing else.
    assert (
        report_schema.version_verdict(older, _schema_declaring(5, {"5": "additive"}))[0]
        == report_schema.VERSION_READABLE
    )


def test_a_chain_is_only_as_readable_as_its_weakest_step():
    """Two steps back is two declarations, not one.

    A version-3 report against a version-5 copy is readable only if BOTH 4 and 5
    were widenings. Reading the nearest step and stopping would accept a document
    from a contract two removals ago on the strength of one claim about the last.
    """
    schema = _schema_declaring(5, {"5": "additive", "4": "breaking"})
    assert report_schema.readable_from(schema) == 4

    reachable = dict(_example(), schema_version=4)
    assert report_schema.version_verdict(reachable, schema)[0] == (
        report_schema.VERSION_READABLE
    )
    unreachable = dict(_example(), schema_version=3)
    assert report_schema.version_verdict(unreachable, schema)[0] == (
        report_schema.VERSION_MISMATCH
    )

    # And the must-fire the other way: declare the middle step additive too and
    # the same version-3 report becomes readable. Without this, the assertion
    # above passes for a validator that walks no chain at all.
    both = _schema_declaring(5, {"5": "additive", "4": "additive", "3": "breaking"})
    assert report_schema.readable_from(both) == 3
    assert report_schema.version_verdict(unreachable, both)[0] == (
        report_schema.VERSION_READABLE
    )


def test_version_one_is_never_readable_however_the_chain_is_declared():
    """1 is not a contract, so no declaration can make it a subset of one.

    It is what every report written before anybody counted says -- 57 of the 71
    on disk on 2026-08-16, across at least three mutually incompatible schemas.
    A chain declared additive all the way down would otherwise let one claim
    about version 2 vouch for documents from schemas nobody recorded.
    """
    schema = _schema_declaring(3, {"3": "additive", "2": "additive"})
    assert report_schema.readable_from(schema) == 2
    assert (
        report_schema.version_verdict(dict(_example(), schema_version=1), schema)[0]
        == report_schema.VERSION_MISMATCH
    )
    # Paired: 2 itself is readable under that same declaration, so the floor is a
    # floor rather than the walk having failed.
    assert (
        report_schema.version_verdict(dict(_example(), schema_version=2), schema)[0]
        == report_schema.VERSION_READABLE
    )


def test_a_newer_report_stays_unvalidatable_whatever_the_older_steps_declared():
    """The declarations only run backwards. Nothing here holds a claim about a
    contract that did not exist when this copy shipped, and a widening chain
    behind us says nothing about the step in front."""
    schema = _schema_declaring(5, {"5": "additive", "4": "additive"})
    newer = dict(_example(), schema_version=6)
    state, sentence = report_schema.version_verdict(newer, schema)
    assert state == report_schema.VERSION_MISMATCH, sentence
    assert "Install" in sentence, sentence

    # Positive control against the same schema, for the same reason as above: a
    # refusal-only test passes against the pre-#416 validator, which refused
    # everything. The chain declared here reaches 3, so a version-3 report is read
    # while the version-6 one is not -- one fixture, both directions.
    older = dict(_example(), schema_version=3)
    assert report_schema.version_verdict(older, schema)[0] == (
        report_schema.VERSION_READABLE
    )


def test_the_shipped_schema_declares_a_relation_for_every_contract_it_records():
    """A bump that forgets the declaration fails safe and quietly. This is the loud half.

    Fail-safe is why the missing declaration is not itself a bug -- every
    in-flight report simply goes back to UNVALIDATABLE, which is where it was
    before #416. But silence is exactly how this field spent its whole life at
    `const: 1`, so the omission is a red suite rather than a shrug.
    """
    schema = _schema()
    declared = schema.get("x-schema-compatibility")
    assert isinstance(declared, dict), (
        "the schema declares no x-schema-compatibility, so no older report can "
        "ever be read and nothing says whether that was decided or forgotten"
    )
    known = set(report_schema.COMPAT_VALUES)
    for version in report_schema.CONTRACT_FINGERPRINTS:
        assert str(version) in declared, (
            "contract {} has a recorded fingerprint and no declared relation to "
            "the contract below it".format(version)
        )
        assert declared[str(version)] in known, declared[str(version)]
    assert str(_contract_version()) in declared, (
        "the current contract does not say whether it widened its predecessor"
    )


def test_the_chain_steps_to_the_previous_RECORDED_contract_not_to_the_number_below():
    """A gap in the numbering must not invent a predecessor.

    Found by review, unreachable today -- the numbering has been contiguous 2..5 --
    and wrong in both directions at once, which is why it is worth a test before it
    is reachable. Decrementing from a schema at 7 whose real predecessor is 5 reads
    a report claiming 6, a number no contract ever had and therefore a typo or a
    forged value, and refuses the genuine 5.
    """
    record = {2: "", 3: "", 4: "", 5: "", 7: ""}
    schema = _schema_declaring(7, {"7": "additive", "5": "breaking"})

    assert report_schema.readable_from(schema, record) == 5
    assert (
        report_schema.version_verdict(
            dict(_example(), schema_version=6), schema, record
        )[0]
        == report_schema.VERSION_MISMATCH
    ), "a number that was never a contract was read"
    assert (
        report_schema.version_verdict(
            dict(_example(), schema_version=5), schema, record
        )[0]
        == report_schema.VERSION_READABLE
    ), "the real predecessor was refused"


def test_a_compatibility_declaration_is_inside_the_contract_fingerprint():
    """The first version of #416 stripped it, by a false analogy with the version.

    x-schema-version is circular because the fingerprint RECORD IS KEYED BY IT.
    Nothing keys on the compatibility map, and it decides which documents this
    validator accepts -- so an edit to it with no bump is #221's own shape one layer
    up: two installed copies both announcing version 5, disagreeing about whether a
    version-4 report is `ok`. Must-fire, paired with the must-not-fire below it.
    """
    # Built rather than taken from the live schema's own declaration: the top of
    # the real chain moves with every bump (#518's own is 'breaking', where #411's
    # was 'additive'), and pinning this to whatever the live top link happens to
    # say today is exactly the coupling-to-current-state CLAUDE.md warns against.
    # Declaring every step from the current version down to FIRST_CONTRACT
    # additive is what actually exercises "widened", regardless of what the
    # shipped schema says on the day this runs.
    current = _contract_version()
    widened = _schema_declaring(
        current,
        {
            str(version): "additive"
            for version in range(report_schema.FIRST_CONTRACT + 1, current + 1)
        },
    )
    assert report_schema.readable_from(widened) == report_schema.FIRST_CONTRACT, (
        "the fixture does not actually widen anything, so the assertion below "
        "would pass for the wrong reason"
    )
    assert report_schema.contract_drift(widened) is not None, (
        "editing the compatibility map moved what this validator accepts and no "
        "fingerprint noticed"
    )

    reworded = _schema()
    reworded["x-honesty-compatibility"] = "Rewritten."
    assert report_schema.contract_drift(reworded) is None, (
        "the PROSE about the map is a narrative like every other one and must not "
        "demand a bump"
    )


def test_the_previous_contract_validates_through_the_command_line(tmp_path):
    """The whole issue, end to end, against the SHIPPED declarations.

    Both versions are derived rather than written down, so this keeps testing the
    real pair after the next bump instead of pinning 4 and 5 forever.
    """
    schema = _schema()
    oldest = report_schema.readable_from(schema)
    current = _contract_version()
    if oldest >= current:
        pytest.skip(
            "the shipped schema declares no additive step, so there is no older "
            "contract to read: x-schema-compatibility says {!r} for {}".format(
                schema.get("x-schema-compatibility", {}).get(str(current)), current
            )
        )

    older = _report_with_payload(tmp_path, name="older.pr.json")
    older["schema_version"] = oldest
    done = _run(str(_write_report(tmp_path, older, "older.json")))
    assert done.returncode == 0, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "ok"), done.stdout
    assert not _verdict_lines(done.stdout, "UNVALIDATABLE"), done.stdout
    assert str(oldest) in done.stdout and str(current) in done.stdout, done.stdout

    # Must-fire, and this is the pairing the issue asks for by name: one step
    # further back is a real narrowing -- `filed` was removed from the review
    # disposition at 3 -> 4 and `closes` became required -- and it has to keep
    # answering UNVALIDATABLE rather than riding in on the step above it.
    narrower = _report_with_payload(tmp_path, name="narrower.pr.json")
    narrower["schema_version"] = oldest - 1
    done = _run(str(_write_report(tmp_path, narrower, "narrower.json")))
    assert done.returncode == 2, done.stdout + done.stderr
    assert _verdict_lines(done.stdout, "UNVALIDATABLE"), done.stdout


# --- the guard on the bump ----------------------------------------------------
#
# A number nobody is required to change will not change; that is the whole history of
# this field. The fingerprint is taken over what a validator enforces and not over the
# prose, so rewording a description does not demand a bump while adding a required key
# does -- which is the line the policy draws, because `additionalProperties: false`
# makes every added key breaking in one direction.


def test_the_shipped_schema_matches_its_recorded_contract_fingerprint():
    assert report_schema.contract_drift(_schema()) is None


def test_an_unrecorded_version_fails_loudly_rather_than_finding_nothing_to_compare():
    """The trap #221 names by hand, and the reason this guard is worth having.

    A hash comparison whose natural failure mode is "no record, nothing to say"
    passes hardest at the moment it is needed: right after someone bumps the
    version. Both arms here are must-fire.
    """
    moved = dict(_schema())
    moved["x-schema-version"] = 99
    problem = report_schema.contract_drift(moved)
    assert problem and "99" in problem, problem

    assert report_schema.contract_drift(_schema(), record={}) is not None, (
        "an empty record must fail every version rather than pass every version"
    )


def test_enforcing_content_that_moved_without_a_bump_is_caught():
    changed = _schema()
    changed["required"] = [key for key in changed["required"] if key != "docs"]
    assert report_schema.contract_drift(changed) is not None


def test_a_property_named_like_an_annotation_is_still_part_of_the_contract():
    """The strip is by key name, and property names live in the same dicts.

    This schema has a property literally called `title`, under
    $defs/forge_payload/properties, and validate_pr_body refuses a payload whose
    title is empty. The first version of the fingerprint walked into that map and
    stripped it, so retyping or deleting a real constraint demanded no bump and
    the guard reported clean -- an under-fire, which is the direction a guard
    fails in silently. Both arms are must-fire.
    """
    forge = "forge_payload"
    retyped = _schema()
    retyped["$defs"][forge]["properties"]["title"] = {"type": "integer"}
    assert report_schema.contract_drift(retyped) is not None

    deleted = _schema()
    del deleted["$defs"][forge]["properties"]["title"]
    assert report_schema.contract_drift(deleted) is not None


def test_prose_does_not_demand_a_bump_but_the_enforcement_lists_do():
    """The must-not-fire half, and the line it draws, both pinned.

    Without a must-not-fire arm the guard would be satisfied by a hash over the
    whole file, which reddens every pull request that touches a sentence and
    trains the reflex of bumping the number to make CI green -- a number moved to
    silence a guard carries no more information than one that never moves.

    The second half is the deliberate over-fire, argued rather than assumed.
    x-enforced and x-enforced-on-disk read as prose and nothing in _walk consumes
    them, but they are the schema's own statement of what a validator refuses,
    paired one-to-one with the mutation table above. A change there is nearly
    always a contract change; the false positive is a rename, and the cost of an
    unnecessary bump is one recorded fingerprint, where the cost of a missed one
    is two copies claiming the same version for different contracts.
    """
    reworded = _schema()
    reworded["description"] = "Rewritten."
    reworded["properties"]["issue"]["description"] = "Also rewritten."
    reworded["x-honesty"] = "Rewritten too."
    reworded["x-convention"] = list(reworded["x-convention"]) + ["and another one"]
    assert report_schema.contract_drift(reworded) is None

    listed = _schema()
    listed["x-enforced"] = list(listed["x-enforced"]) + ["something-new"]
    assert report_schema.contract_drift(listed) is not None, (
        "the enforcement lists are inside the fingerprint on purpose; if that "
        "changes, change the sentence in x-honesty-versioning with it"
    )


# ------------------------- a request rendered as a completed action (#254)
#
# `disposition: filed` was a value an agent could write for a review finding it
# had judged out of its diff's scope. The word is past tense: read at the speed
# a maintainer reads a report -- states first, then items, most of them `fixed`
# -- it says *this has been filed*. It meant *this should be filed, by you, and
# nothing has happened yet*. Twice in one day it meant nobody filed it (#144's
# report, which surfaced only when the finding was rediscovered a day later and
# became #241, and #193's, which the tracker had never heard of).
#
# So the contract renders a request and a completed action identically, which is
# this repository's own defect class inside its own review format.
#
# The value is REMOVED rather than joined by a second one, and that is the
# judgment this change makes. An agent must not file: its publishing clause is
# unconditional -- do not push, do not open a pull request, do not comment on
# the issue -- and opening a tracker issue is publishing, under the maintainer's
# credentials, in the one place this plugin deliberately keeps agents out of
# (the triager holds the tracker and is confined to labels, never content). A
# vocabulary that lets an agent SAY `filed` makes a forbidden action spellable,
# and the two instances above are exactly reports that spelled it while nothing
# had been filed. So the enum carries no word for a completed filing at all, and
# a report still using the old one is refused rather than quietly reinterpreted.
#
# `report-for-filing` is not a new word: it is what `adjacent.action` has always
# used for the same act. One vocabulary across the report, present tense, and
# unambiguously a request addressed to somebody else.


def _finding_dispositions():
    return set(_schema()["$defs"]["finding"]["properties"]["disposition"]["enum"])


def test_a_review_finding_cannot_claim_a_completed_filing():
    """The must-not-fire half. Paired below with a report that uses the removed
    word, so an enum this test could not read would not pass for the wrong
    reason.
    """
    assert "filed" not in _finding_dispositions(), (
        "a past-tense disposition is back: an agent cannot file and a report "
        "saying it did is indistinguishable from one asking somebody to"
    )
    assert "report-for-filing" in _finding_dispositions(), (
        "the request state is gone, so a finding left for the maintainer has "
        "nowhere to go but `open` -- which says nothing about who owes what"
    )


def test_the_filing_vocabulary_is_the_same_word_in_both_surveys():
    """Two fields, one act. A second spelling is a second thing to grep for and
    a second thing to get wrong, and the maintainer reads both surveys.
    """
    actions = set(_schema()["$defs"]["adjacent"]["properties"]["action"]["enum"])
    assert "report-for-filing" in actions
    assert "report-for-filing" in _finding_dispositions()


def test_a_report_still_saying_filed_is_refused():
    """The must-fire half of the pair above.

    `"filed" not in enum` also passes against a schema whose `finding` def this
    test failed to find, or whose enum went empty. This one drives the
    validator: the old word has to be rejected, not merely absent from a list.
    """
    report = _example()
    report["review"]["findings"] = {
        "state": "checked",
        "items": [{"class": "correctness", "disposition": "filed", "text": "x"}],
    }
    errors = report_schema.validate(report)
    assert any("filed" in error for error in errors), (
        "the removed disposition is still accepted: {}".format(errors)
    )


def test_a_finding_left_for_filing_carries_its_reason():
    """The one thing worth enforcing once the word is unambiguous.

    A `report-for-filing` finding is work handed to the maintainer, and what
    they need in order to act is why the agent did not fix it. With no reason it
    is a sentence somebody has to reconstruct the judgment behind before they
    can open anything, which is how a request becomes a thing to do later.

    `adjacent` records the same judgment and is deliberately not held to the same
    contract -- it has no `reason` field, so its argument rides inside `text`
    unchecked. Asserted rather than left to prose, by the pair below.
    """
    report = _example()
    report["review"]["findings"] = {
        "state": "checked",
        "items": [
            {
                "class": "correctness",
                "disposition": "report-for-filing",
                "text": "the helper swallows OSError, so an unreadable tree reads as an empty one",
            }
        ],
    }
    errors = report_schema.validate(report)
    assert any("report-for-filing" in error for error in errors), (
        "a finding handed to the maintainer with no argument was accepted: {}".format(
            errors
        )
    )

    # Must-not-fire, same fixture: the reason supplied.
    report["review"]["findings"]["items"][0]["reason"] = (
        "fixing it means changing what three callers receive for an unreadable "
        "tree, which is a design decision this brief did not carry"
    )
    assert report_schema.validate(report) == []


def test_the_adjacent_survey_is_deliberately_not_held_to_the_same_contract():
    """The asymmetry the docstring above claims, asserted rather than described.

    Two fields record the same act under the same word, and only one carries an
    argument the validator refuses it without. That is a real difference and it is
    easy to state backwards -- so it is pinned here: `adjacent` has no `reason`
    slot at all, and an item carrying none is accepted. It is an asymmetry about
    `reason` and nothing wider: since #411 `adjacent` does carry the enforced
    `pr_anchor`, so "adjacent is the unchecked one" is too broad to write. If a `reason` is ever added there, this fails and whoever
    adds it decides in the same breath whether it is enforced, instead of
    leaving two surveys that look symmetrical and are not.
    """
    adjacent = _schema()["$defs"]["adjacent"]
    assert "reason" not in adjacent["properties"], (
        "adjacent grew a reason field; decide whether it is enforced and say so "
        "in _rule_finding's docstring, which currently states it is not"
    )
    assert adjacent["additionalProperties"] is False

    report = _example()
    report["adjacent"] = {
        "state": "checked",
        "items": [
            {
                "text": "the sibling helper has the same swallowed OSError",
                "file": None,
                "in_blast_radius": False,
                "action": "report-for-filing",
            }
        ],
    }
    assert report_schema.validate(report) == [], (
        "an adjacent item left for filing with no argument is refused, so the "
        "two surveys are symmetrical after all and the docstring is wrong"
    )


# --- the third receipt (#411) ---------------------------------------------------
#
# #393 gave an item three receipts and the enum encoded two, so a lane that decided
# "below the bar, this belongs in the pull request body" had to label it
# `report-for-filing` and disclaim it in prose. The maintainer read the label first
# and nearly filed the thing the item argued against filing -- the bar failing in
# the direction it was created to prevent.
#
# `below-bar` is deliberately not a verb. `filed` misread as an act the agent had
# performed (#254); `report-for-filing` misreads as an act the reader should perform.
# A phrase with no verb and no tense has no act in it to attribute either way.
#
# And it is CHECKED rather than declared. The receipt is a line in the pull request
# body, the report already names that file, and this validator already opens it -- so
# an item claiming the third receipt carries `pr_anchor`, a fragment it also wrote
# into the body, and the on-disk pass looks for it. Same standing as the `closes`
# check it borrows from: an absence detector, so a finding is strong and a pass is
# weak. A body containing the anchor and nothing else would pass, which is why the
# anchor has to be long enough to cost a phrase rather than a word.


def test_a_report_can_say_all_three_receipts(tmp_path):
    """The issue's test: one item of each kind, all three accepted.

    Before this change the third was unsayable, so a lane wrote the second label over
    it. All three in one report because that is the shape that proves the vocabulary
    is a set rather than a swap -- adding the third must not cost either of the two.
    """
    anchor = "the docstring above the helper is wider than the code under it"
    payload = _payload()
    payload["body"] = (
        "Splits on either separator.\n\n"
        "Below the filing bar and recorded here rather than as an issue: "
        + anchor
        + ". True, and no caller reaches it."
    )
    report = _report_with_payload(tmp_path, payload=payload, name="three.pr.json")
    report["adjacent"] = {
        "state": "checked",
        "items": [
            {
                "text": "The sibling helper had the same swallowed OSError.",
                "file": "scripts/example.py",
                "in_blast_radius": True,
                "action": "fixed",
            },
            {
                "text": "The scaffold writes the trio without checking the tree is readable.",
                "file": "scripts/scaffold.py",
                "in_blast_radius": False,
                "action": "report-for-filing",
            },
            {
                "text": "The docstring above the helper is wider than the code under it.",
                "file": "scripts/example.py",
                "in_blast_radius": False,
                "action": "below-bar",
                "pr_anchor": anchor,
            },
        ],
    }
    assert report_schema.validate(report) == []
    assert report_schema.validate_pr_body(report, base_dir=tmp_path) == []


def test_a_below_bar_item_whose_substance_is_not_in_the_body_is_refused(tmp_path):
    """Must-fire, with its control in the same fixture.

    The pair is the point: the absent half alone would pass against a checker that
    refuses every below-bar item, and the present half alone would pass against one
    that never looks. Only the body differs between them.
    """
    anchor = "the docstring above the helper is wider than the code under it"
    absent = _report_with_a_below_bar_item(
        tmp_path,
        body="Splits on either separator. Nothing here about anything else.",
        anchor=anchor,
        name="absent.pr.json",
    )
    assert report_schema.validate(absent) == [], (
        "the shape pass has an opinion about the body, which it must not: it never "
        "opens a file"
    )
    errors = report_schema.validate_pr_body(absent, base_dir=tmp_path)
    assert any("pr_anchor" in error for error in errors), (
        "a below-bar item whose receipt is nowhere in the body was accepted, so the "
        "third receipt is a promise rather than a guarantee: {}".format(errors)
    )

    present = _report_with_a_below_bar_item(
        tmp_path,
        body="Splits on either separator.\n\nBelow the bar: " + anchor + ".",
        anchor=anchor,
        name="present.pr.json",
    )
    assert report_schema.validate_pr_body(present, base_dir=tmp_path) == []


def test_a_wrapped_body_still_carries_the_anchor(tmp_path):
    """A body is prose somebody wrapped, and the anchor is one the agent quoted.

    Matching on raw text would make the check fire on where a line happened to break,
    which is a false finding about a receipt that is really there -- and a checker
    with false findings gets worked around rather than fixed.
    """
    anchor = "the docstring above the helper is wider than the code under it"
    report = _report_with_a_below_bar_item(
        tmp_path,
        body="Below the bar: the docstring above the helper\nis wider than the\ncode under it.",
        anchor=anchor,
        name="wrapped.pr.json",
    )
    assert report_schema.validate_pr_body(report, base_dir=tmp_path) == []

    # The same body with CRLF line endings, which is what a payload written on
    # Windows carries. `str.split()` with no argument splits on every whitespace
    # character, so the carriage returns collapse with the newlines -- observed here
    # rather than reasoned, because a checker that fired on one platform's line
    # endings would report a real receipt as missing on exactly one leg of the matrix.
    crlf = _report_with_a_below_bar_item(
        tmp_path,
        body=(
            "Below the bar: the docstring above the helper\r\n"
            "is wider than the\r\ncode under it."
        ),
        anchor=anchor,
        name="crlf.pr.json",
    )
    assert report_schema.validate_pr_body(crlf, base_dir=tmp_path) == []


def test_a_sentence_the_body_capitalises_is_still_the_receipt(tmp_path):
    """Found by writing the first real report against this check, not by reasoning.

    The body carried the sentence inside `**bold**`, where it opens a bullet and so
    starts with a capital; the anchor quoted it mid-sentence in lower case, and a
    case-sensitive containment refused a receipt that was plainly there. Folding can
    only turn a finding into a pass, so it costs the check nothing it could claim --
    and the pair below is what stops that being a licence: an anchor the body does
    not carry at all is still refused.
    """
    report = _report_with_a_below_bar_item(
        tmp_path,
        body="- **The docstring above the helper is wider than the code under it.**",
        anchor="the docstring above the helper is wider than the code under it",
        name="capitalised.pr.json",
    )
    assert report_schema.validate_pr_body(report, base_dir=tmp_path) == []

    # Must-fire, same fixture: folding case is not folding the sentence away.
    absent = _report_with_a_below_bar_item(
        tmp_path,
        body="- **THE DOCSTRING SAYS SOMETHING ELSE ENTIRELY ABOUT THE HELPER.**",
        anchor="the docstring above the helper is wider than the code under it",
        name="folded-away.pr.json",
    )
    assert report_schema.validate_pr_body(absent, base_dir=tmp_path)


def test_an_anchor_hidden_in_an_html_comment_is_not_a_receipt(tmp_path):
    """The receipt is a line somebody reads. A comment renders to nothing.

    Same reasoning as the closing-keyword check one function over: the question is
    what reaches the reader, not what is in the file.
    """
    anchor = "the docstring above the helper is wider than the code under it"
    report = _report_with_a_below_bar_item(
        tmp_path,
        body="Splits on either separator.\n\n<!-- " + anchor + " -->",
        anchor=anchor,
        name="hidden.pr.json",
    )
    assert report_schema.validate_pr_body(report, base_dir=tmp_path), (
        "an anchor visible to nobody was accepted as a receipt"
    )


def test_an_anchor_too_short_to_be_evidence_is_refused():
    """The floor, and the honest limit of it.

    Containment cannot tell substance from a pasted token, so what it buys is a cost:
    the anchor has to be a phrase. A word or two can appear in a body that never
    mentions the finding, at which point the check passes on nothing.
    """
    report = _example()
    report["adjacent"] = {
        "state": "checked",
        "items": [
            {
                "text": "The docstring is wider than the code under it.",
                "file": None,
                "in_blast_radius": False,
                "action": "below-bar",
                "pr_anchor": "the docstring",
            }
        ],
    }
    errors = report_schema.validate(report)
    assert any("pr_anchor" in error for error in errors), (
        "a two-word anchor was accepted: {}".format(errors)
    )

    # Must-not-fire, same fixture: a phrase long enough to have been written on purpose.
    report["adjacent"]["items"][0]["pr_anchor"] = (
        "the docstring above the helper is wider than the code under it"
    )
    assert report_schema.validate(report) == []


def test_the_third_receipt_is_spellable_in_both_surveys():
    """One act, one word, both surveys -- the same join #254 made for filing.

    A finding is below the bar or it is not; who noticed it does not change that. Two
    spellings would be two things to grep for and a second thing to get wrong, and the
    maintainer reads both surveys.
    """
    actions = set(_schema()["$defs"]["adjacent"]["properties"]["action"]["enum"])
    assert "below-bar" in actions
    assert "below-bar" in _finding_dispositions()


def test_the_two_older_receipts_did_not_move():
    """Adding a value must widen the vocabulary, never swap one out.

    An older report carries only the two, and this is the assertion that says so: a
    rename dressed as an addition fails here rather than in somebody's archive.
    """
    actions = set(_schema()["$defs"]["adjacent"]["properties"]["action"]["enum"])
    assert {"fixed", "report-for-filing"} <= actions
    assert {"fixed", "refused", "argued-down", "report-for-filing", "open"} <= (
        _finding_dispositions()
    )
