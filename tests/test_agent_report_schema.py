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
        "docs-target-left-alone-carries-a-why": docs_target_left_alone_without_why,
        "docs-target-unread-carries-a-why": docs_target_unread_without_why,
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
    assert not missing, "agents/developer.md references files that do not exist: {}".format(missing)

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


def test_validate_file_on_unparseable_json_reports_rather_than_returning_clean(tmp_path):
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


def _report_with_payload(tmp_path, payload=None, name="body.pr.json", write=True):
    report = _example()
    target = tmp_path / name
    if write:
        if isinstance(payload, str):
            target.write_text(payload, encoding="utf-8")
        else:
            target.write_text(
                json.dumps(_payload() if payload is None else payload), encoding="utf-8"
            )
    report["pr_body"] = {"state": "written", "path": str(target)}
    return report


def test_a_written_payload_the_forge_can_consume_is_accepted(tmp_path):
    report = _report_with_payload(tmp_path)
    assert report_schema.validate(report) == []
    assert report_schema.validate_pr_body(report) == []


def test_shape_validation_never_opens_the_file(tmp_path):
    """validate() stays a shape checker. The split is why both can be trusted."""
    report = _report_with_payload(tmp_path, write=False)
    assert report_schema.validate(report) == []
    assert report_schema.validate_pr_body(report), "the missing file must be caught somewhere"


def test_a_report_that_wrote_no_body_has_nothing_to_open():
    report = _example()
    report["pr_body"] = {"state": "not-written", "path": None, "reason": "no code changed"}
    assert report_schema.validate_pr_body(report) == []


def _disk_mutations(tmp_path):
    """One case per name in x-enforced-on-disk. Each must be rejected."""
    return {
        "pr-body-file-exists": _report_with_payload(tmp_path, write=False),
        "pr-body-file-parses": _report_with_payload(
            tmp_path, payload="# A markdown body, which is what the forge refuses"
        ),
        "pr-body-payload-shape": _report_with_payload(
            tmp_path,
            payload={"title": "t", "body": "b", "head": "fix/123", "base": "main", "titel": "typo"},
        ),
        "pr-body-title-and-body-are-non-empty": _report_with_payload(
            tmp_path, payload={"title": "  ", "body": "b", "head": "fix/123", "base": "main"}
        ),
        "pr-body-head-matches-the-report-branch": _report_with_payload(
            tmp_path, payload={"title": "t", "body": "b", "head": "fix/999", "base": "main"}
        ),
    }


@pytest.mark.parametrize("name", sorted(_schema()["x-enforced-on-disk"]))
def test_each_on_disk_property_rejects_a_payload_that_breaks_it(name, tmp_path):
    report = _disk_mutations(tmp_path)[name]
    assert report_schema.validate_pr_body(report), "{} accepted a payload that breaks it".format(name)


def test_every_on_disk_claim_has_a_case_that_proves_it(tmp_path):
    claimed = set(_schema()["x-enforced-on-disk"])
    proven = set(_disk_mutations(tmp_path))
    assert claimed == proven, "claimed but unproven: {}; proven but unclaimed: {}".format(
        sorted(claimed - proven), sorted(proven - claimed)
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


def test_a_forge_payload_handed_to_the_report_validator_is_refused_by_name(tmp_path, capsys):
    errors = report_schema.validate_file(_payload_only(tmp_path))
    assert len(errors) == 1, "a payload should get one sentence, not a wall: {}".format(errors)
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


def test_a_schema_that_stopped_defining_the_payload_declines_rather_than_guesses(tmp_path):
    """The third state. Unable to classify is not the same as classified as a report.

    Declining leaves the shape pass to answer, which it does loudly. Guessing
    either way would be a confident verdict about a question nothing looked at.
    """
    schema = _schema()
    schema["$defs"]["forge_payload"] = {"type": "object"}
    assert report_schema._is_forge_payload(_payload(), schema) is False
    assert report_schema._is_forge_payload(_payload(), _schema()) is True


# --- the call the skill documents, run rather than read -----------------------


SKILL_PATH = REPO_ROOT / "skills" / "manager" / "SKILL.md"

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
