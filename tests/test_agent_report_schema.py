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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import report_schema  # noqa: E402

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

    def class_verdict_unreached_without_why(report):
        report["review"]["classes"]["items"][0] = {
            "class": "platform",
            "state": "not-checked",
        }
        return report

    def test_phase_observed_without_result(report):
        report["tests"]["green"] = {"state": "observed"}
        return report

    def test_phase_skipped_without_reason(report):
        report["tests"]["red"] = {"state": "not-run"}
        return report

    def pr_body_written_without_path(report):
        report["pr_body"] = {"state": "written", "path": ""}
        return report

    def pr_body_absent_without_reason(report):
        report["pr_body"] = {"state": "not-written", "path": None}
        return report

    return {
        "required-keys": missing_required_key,
        "types": wrong_type,
        "no-unknown-keys": unknown_key,
        "enum-membership": bad_enum,
        "survey-not-checked-carries-a-reason": survey_not_checked_without_reason,
        "survey-not-checked-carries-no-items": survey_not_checked_carrying_items,
        "refusal-carries-text-and-argument": refusal_without_argument,
        "unreached-class-carries-a-why": class_verdict_unreached_without_why,
        "observed-test-phase-carries-a-result": test_phase_observed_without_result,
        "unobserved-test-phase-carries-a-reason": test_phase_skipped_without_reason,
        "written-pr-body-carries-a-path": pr_body_written_without_path,
        "unwritten-pr-body-carries-a-reason": pr_body_absent_without_reason,
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
    assert claimed == proven, "claimed but unproven: {}; proven but unclaimed: {}".format(
        sorted(claimed - proven), sorted(proven - claimed)
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
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_example()), encoding="utf-8")
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
    assert not missing, "agents/developer.md references files that do not exist: {}".format(missing)

# --- the same command line, in process ----------------------------------------
#
# The subprocess tests above prove the orchestrator's invocation works. Coverage
# cannot see inside a subprocess, so on those alone main() reads as dead code --
# this repo's own defect class, a measurement claiming an absence. Both routes
# exist on purpose, the same way doctor.py is driven twice.


def test_validate_file_reads_and_validates(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_example()), encoding="utf-8")
    assert report_schema.validate_file(path) == []


def test_validate_file_on_a_missing_file_reports_rather_than_returning_clean(tmp_path):
    errors = report_schema.validate_file(tmp_path / "absent.json")
    assert errors and "cannot read" in errors[0]


def test_validate_file_on_unparseable_json_reports_rather_than_returning_clean(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("{not json", encoding="utf-8")
    errors = report_schema.validate_file(path)
    assert errors and "not valid json" in errors[0]


def test_main_returns_zero_on_a_good_report(tmp_path, capsys):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_example()), encoding="utf-8")
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
    assert report_schema.main([str(path), "--schema", str(tmp_path / "absent.json")]) == 1
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

def test_output_survives_a_console_that_cannot_represent_the_report(tmp_path, monkeypatch):
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
