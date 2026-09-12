"""#1466: a pull request payload body carrying a literal backslash-quote.

Four developer lanes hand-typed a JSON payload where ordinary prose quoting a
short phrase verbatim -- `"15 of 19"` -- was double-escaped into
`\\"15 of 19\\"` inside the JSON source. Decoded, that leaves an actual
backslash character sitting directly in front of a quote character in the
parsed body string: not what anyone meant to write. `gh-pr-create` (a
supertool op, outside this repo) already refuses the shape correctly, but only
after the agent has already composed and attempted to publish the payload --
each refusal cost a resumed session, a re-derived fix, and a second create
call. This pins the mechanical, earlier gate: `report_schema.py`'s own
`validate_pr_body` pass, which every report already runs through before a
sub-manager ever calls `gh-pr-create`.

Same shape as `escaped_newline_body_errors` beside it (#685): an absence
detector, so a finding is strong and a pass is weak, and the working remedy for
a body that genuinely needs a literal backslash-quote is a code span, where a
forge renders it verbatim and this check does not look.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import report_schema  # noqa: E402
from test_agent_report_schema import _payload, _report_with_payload  # noqa: E402

BACKSLASH_QUOTE = chr(92) + chr(34)

#: The observed shape, rebuilt from the issue's own evidence: an agent meant
#: the plain prose quote `"15 of 19"` and instead wrote the JSON source with
#: one extra level of escaping, which decodes to a literal backslash sitting
#: in front of each quote.
DAMAGED_BODY = (
    "Ran the suite and confirmed {q}15 of 19{q} checks passed before the "
    "fix.\n\nCloses #1466\n"
).format(q=BACKSLASH_QUOTE)

HEALTHY_BODY = (
    'Ran the suite and confirmed "15 of 19" checks passed before the fix, '
    "quoting the literal escape `{q}` here inside a code span on purpose.\n\n"
    "Closes #1466\n"
).format(q=BACKSLASH_QUOTE)


def _body_errors(body):
    payload = _payload()
    payload["body"] = body
    return report_schema.escaped_quote_body_errors(payload)


def test_the_damaged_fixture_carries_the_observed_shape():
    """Control on the fixture. If it does not actually carry a literal
    backslash-quote, everything asserted about it below is evidence about
    something else."""
    assert BACKSLASH_QUOTE in DAMAGED_BODY


def test_the_check_fires_on_a_hand_typed_double_escape():
    errors = _body_errors(DAMAGED_BODY)
    assert errors, "a body with a literal backslash-quote outside code passed"
    assert "pr_body.payload.body" in errors[0]
    assert "backslash-quote" in errors[0] or "backslash" in errors[0]


def test_a_code_span_is_a_working_remedy_rather_than_an_unreachable_one():
    """Must-fire/must-not-fire pair. Without the must-fire half, the pass
    below could be a check that never looks at all."""
    naked = "One line of prose mentioning {q}a phrase{q} outside any code span.".format(
        q=BACKSLASH_QUOTE
    )
    assert _body_errors(naked) != [], (
        "the control did not fire, so the pair below proves nothing"
    )
    assert _body_errors(HEALTHY_BODY) == [], _body_errors(HEALTHY_BODY)


def test_an_ordinary_plain_quoted_body_passes():
    """The healthy case this whole check exists to leave alone: prose quoting
    a phrase the ordinary way, with no backslash anywhere."""
    plain = 'Ran the suite and confirmed "15 of 19" checks passed.\n\nCloses #1466\n'
    assert _body_errors(plain) == []


def test_a_lone_backslash_quote_at_the_end_of_a_windows_path_does_not_fire():
    """Found on review (#1466's own self-review): a single, unpaired
    backslash-quote is exactly what a quoted Windows path's trailing
    separator looks like right before the closing quote mark -- and has
    nothing to do with the double-escaped-JSON shape this check exists for.
    The real defect always doubles the escape on BOTH sides of a quoted
    phrase (see DAMAGED_BODY above); a lone occurrence must not fire."""
    windows = (
        'Set the install path to "C:{b}Windows{b}System32{b}" in the '
        "config.\n\nCloses #1466\n"
    ).format(b=chr(92))
    assert _body_errors(windows) == [], _body_errors(windows)

    # Must-fire control in the same fixture: a second, paired occurrence
    # elsewhere in the same body still fires, so the pass above is a
    # narrowing and not the check going quiet.
    paired = windows + "Also saw {q}odd behaviour{q} in the logs.\n".format(
        q=BACKSLASH_QUOTE
    )
    assert _body_errors(paired) != [], paired


def test_two_unrelated_windows_paths_on_one_line_do_not_fire():
    """Second-pass review finding: two lone backslash-quote sentinels can sit
    near each other without belonging to the same quoted phrase at all -- two
    separate Windows paths, each ending its own quoted segment. Requiring only
    a pair count, with no constraint on what sits between the two sentinels,
    still fired on this shape. The genuine defect's own quoted phrase never
    contains a bare, unescaped quote inside it, so the content between a real
    pair must never itself carry one."""
    two_paths = (
        'Moved the install directory from "C:{b}Old{b}" to "C:{b}New{b}".'
        "\n\nCloses #1466\n"
    ).format(b=chr(92))
    assert _body_errors(two_paths) == [], _body_errors(two_paths)

    # Must-fire control: a genuine single quoted phrase, double-escaped on
    # both sides, still fires -- so the pass above is a narrowing and not the
    # check going quiet.
    assert _body_errors(DAMAGED_BODY) != []


def test_the_check_runs_from_validate_pr_body_on_a_real_payload(tmp_path):
    """Wired, not merely defined. A checker nothing calls is this repository's
    own defect class one level up."""
    payload = _payload()
    payload["body"] = DAMAGED_BODY
    report = _report_with_payload(
        tmp_path, payload=payload, closes={"state": "closes", "issues": [1466]}
    )
    errors = report_schema.validate_pr_body(report, base_dir=tmp_path)
    assert any("backslash" in e for e in errors), errors
