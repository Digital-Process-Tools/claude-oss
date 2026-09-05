"""#698: `report_schema`'s `forge_payload` forbade `no_close`, the field
supertool's `gh-pr-create` requires to open a pull request that deliberately
closes nothing (a Part-of-#N pull request, or unrelated work). Every payload
carrying it validated INVALID by construction, which rewards deleting the key
and writing a false `Closes #N` instead -- measured on #697.

Two things are tested here, matching the issue's own two asks: that `no_close`
is now a legal key (the shape fix), paired with the positive control the issue
itself asks for (a genuinely unknown key still fails, so this is not merely
`additionalProperties: false` having been dropped); and the self-contradiction
catch -- `no_close: true` beside a body that still binds a closing keyword.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import report_schema  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "agent-report.schema.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _example():
    return json.loads(json.dumps(_schema()["examples"][0]))


def _report_with_payload(tmp_path, payload, closes, name="body.pr.json"):
    report = _example()
    target = tmp_path / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    report["pr_body"] = {"state": "written", "path": str(target), "closes": closes}
    return report


def test_no_close_true_with_a_non_closing_body_validates_clean(tmp_path):
    """The shape fix itself: a Part-of-#N payload carrying `no_close: true` --
    exactly the shape #697 needed and #698 says validated INVALID -- must pass.
    """
    payload = {
        "title": "t",
        "body": "Part of #695. Adds the sub-manager unit; the scheduler wiring "
        "that makes the cost saving real is out of scope.",
        "head": "fix/123",
        "base": "main",
        "no_close": True,
    }
    report = _report_with_payload(
        tmp_path,
        payload,
        closes={
            "state": "closes-nothing",
            "reason": "Part of #695; the wiring is a separate PR.",
        },
    )
    assert report_schema.validate_pr_body(report, base_dir=tmp_path) == []


def test_an_unrelated_unknown_key_is_still_refused(tmp_path):
    """Positive control the issue itself asks for: adding `no_close` must not be
    indistinguishable from `additionalProperties: false` having been dropped
    entirely. A payload with a genuinely unknown key must still fail.
    """
    payload = {
        "title": "t",
        "body": "Closes #1.",
        "head": "fix/1",
        "base": "main",
        "totally_unknown_field": True,
    }
    report = _report_with_payload(
        tmp_path,
        payload,
        closes={"state": "closes", "issues": [1]},
        name="unknown.pr.json",
    )
    errors = report_schema.validate_pr_body(report, base_dir=tmp_path)
    assert errors, "an unknown key must still be refused"


def test_no_close_true_beside_a_bound_closing_keyword_is_refused(tmp_path):
    """The contradiction the issue names as a second, separate hole: `no_close:
    true` and a body that still binds a closing keyword disagree about what
    merging this pull request does, and only the on-disk pass can see both.
    """
    payload = {
        "title": "t",
        "body": "Closes #999.",
        "head": "fix/123",
        "base": "main",
        "no_close": True,
    }
    report = _report_with_payload(
        tmp_path,
        payload,
        closes={"state": "closes", "issues": [999]},
        name="contradiction.pr.json",
    )
    errors = report_schema.validate_pr_body(report, base_dir=tmp_path)
    assert errors, "no_close: true beside a bound closing keyword must be refused"
    assert any("no_close" in e for e in errors)


def test_no_close_false_beside_a_bound_closing_keyword_is_fine(tmp_path):
    """Must-fire's pair: an ordinary closing pull request, no_close absent, must
    not be caught by the new rule -- it only fires on `no_close: true`.
    """
    payload = {
        "title": "t",
        "body": "Closes #1.",
        "head": "fix/123",
        "base": "main",
    }
    report = _report_with_payload(
        tmp_path,
        payload,
        closes={"state": "closes", "issues": [1]},
        name="ordinary.pr.json",
    )
    assert report_schema.validate_pr_body(report, base_dir=tmp_path) == []
