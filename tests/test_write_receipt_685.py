"""#685: two handbacks damaged in one session by an instruction that is true
and insufficient, and one of them misdiagnosed as a file that vanished.

Instance 1 -- a pull request payload whose ``body`` carried 30 literal
backslash-n sequences against 4 real newlines, because the author hand-built
JSON inside a TOML literal and doubled the escape. Opened unread it would have
rendered as one enormous line, every heading and paragraph break visible as a
backslash followed by an n.

Instance 2 -- a bare ``supertool`` call with no ``cd`` prefix ran from the
session's original cwd, so a report landed in the main clone rather than under
``worktree_root``. The lane that hit it second reported its note had *vanished*.
It had not vanished. Nothing anywhere named the directory anything was read
from or written to, so "the file is not there" and "I am not where I think I
am" render identically -- this repository's own defect class, landing in a
handback rather than in a checker.

Three things are pinned here, and each is paired with the control that stops it
passing for the wrong reason:

1. ``resolved_receipt`` -- every verdict names the absolute path it actually
   read, in two states, and a path it cannot resolve says so rather than
   echoing the argument back as though it had been resolved.
2. ``escaped_newline_body_errors`` -- an absence detector over the payload body,
   in the same sense as the closing-keyword check beside it: a finding is
   strong, a pass is weak, and the remedy for a body that genuinely means a
   backslash-n is a code span, which is what markdown wants anyway.
3. Both write-route documents state that the cwd move is per write call, not
   once. That is the sixth fact worth pinning across the pair (five live in
   ``tests/test_write_route_fact_parity_673.py``): the existing anchor in
   ``tests/test_content_invariants.py`` is satisfied by a document saying
   ``cd <worktree_root>`` exactly once, which is the wording both documents
   carried while instance 2 happened twice.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import report_schema  # noqa: E402
from test_agent_report_schema import _payload, _report_with_payload  # noqa: E402
from test_content_invariants import WRITE_ROUTE_DOCUMENTS, _collapse  # noqa: E402

BACKSLASH_N = chr(92) + "n"

#: The observed shape, rebuilt to the observed counts: 30 literal backslash-n
#: sequences and 4 real newlines. The three closing lines being on real
#: newlines while everything above them is not is the tell that this was one
#: half of a write escaping and the other half not, rather than a uniform
#: encoding choice.
_DAMAGED_PROSE = (BACKSLASH_N * 2).join(
    "Paragraph {} of a body whose line breaks were doubled on the way in.".format(n)
    for n in range(1, 17)
)
DAMAGED_BODY = _DAMAGED_PROSE + "\n\nCloses #685\nCloses #583\n"

HEALTHY_BODY = """## What

A body with real line breaks, several paragraphs, and one mention of a
newline escape sitting inside a code span where markdown wants it: `{n}`.

## Why

Because the check below counts, it does not read.

Closes #685
""".format(n=BACKSLASH_N)


def _body_errors(body):
    payload = _payload()
    payload["body"] = body
    return report_schema.escaped_newline_body_errors(payload)


def _at_lines(captured):
    return [
        line.strip()
        for line in captured.splitlines()
        if line.strip().startswith("at:")
    ]


# --- the doubled-escape detector ------------------------------------------


def test_the_counts_in_the_damaged_fixture_are_the_observed_ones():
    """Control on the fixture. If it does not actually carry the shape #685
    observed, everything asserted about it below is evidence about something
    else."""
    assert DAMAGED_BODY.count(BACKSLASH_N) == 30
    assert DAMAGED_BODY.count(chr(10)) == 4


def test_the_check_fires_on_the_observed_damage():
    errors = _body_errors(DAMAGED_BODY)
    assert errors, "a body with 30 literal escapes against 4 real newlines passed"
    assert "30" in errors[0] and "4" in errors[0], errors[0]
    assert "pr_body.payload.body" in errors[0]


def test_a_healthy_body_passes_and_the_check_is_not_vacuous():
    """The must-not-fire and its must-fire in one fixture. A detector that
    reported nothing because it never looked would satisfy the first half
    alone."""
    assert _body_errors(HEALTHY_BODY) == []
    assert _body_errors(DAMAGED_BODY) != []


def test_a_code_span_is_a_working_remedy_rather_than_an_unreachable_one():
    """The escape hatch has to be real, or the check is un-passable for a body
    that legitimately means a backslash-n -- which is the objection this
    repository raises against heuristics, and it is answered by the remedy
    being correct markdown rather than by a flag."""
    naked = "One line of prose mentioning {n} {n} {n} outside any code span.".format(
        n=BACKSLASH_N
    )
    assert _body_errors(naked) != [], (
        "the control did not fire, so the pair below proves nothing"
    )

    spanned = "One line of prose mentioning `{n}` `{n}` `{n}` inside code spans.".format(
        n=BACKSLASH_N
    )
    assert _body_errors(spanned) == []


def test_a_body_more_formatted_than_escaped_is_a_pass_and_the_pass_is_weak():
    """Stated as a test because it is the honest limit of the check: a body
    that is half damaged -- four stray escapes under thirty real line breaks --
    passes. This counts a ratio; it does not read the prose."""
    half = (chr(10) * 30) + (BACKSLASH_N * 4)
    assert _body_errors(half) == []


def test_the_check_runs_from_validate_pr_body_on_a_real_payload(tmp_path):
    """Wired, not merely defined. A checker nothing calls is this repository's
    own defect class one level up."""
    payload = _payload()
    payload["body"] = DAMAGED_BODY
    report = _report_with_payload(
        tmp_path, payload=payload, closes={"state": "closes", "issues": [685, 583]}
    )
    errors = report_schema.validate_pr_body(report, base_dir=tmp_path)
    assert any("literal" in e for e in errors), errors


# --- the receipt that names where it looked --------------------------------


def test_the_verdict_names_the_absolute_path_it_actually_read(tmp_path, capsys):
    """Two reports with the same basename in two directories -- exactly the
    instance-2 shape, where the lane believed it was writing under
    ``worktree_root`` and was writing in the main clone. The verdict lines must
    differ."""
    one = tmp_path / "wt" / "reports"
    two = tmp_path / "clone" / "reports"
    lines = []
    for directory in (one, two):
        directory.mkdir(parents=True)
        path = directory / "report.json"
        path.write_text(json.dumps(_report_with_payload(directory)), encoding="utf-8")
        assert report_schema.main([str(path)]) == 0
        lines.append(_at_lines(capsys.readouterr().out))

    assert lines[0] and lines[1], "no `at:` receipt was printed at all: {}".format(lines)
    assert lines[0] != lines[1], (
        "two reports in two directories produced the same receipt, which is the "
        "silence #685 is about: {}".format(lines)
    )
    assert str(one.resolve()) in lines[0][0]
    assert str(two.resolve()) in lines[1][0]


def test_an_invalid_report_also_names_where_it_looked(tmp_path, capsys):
    """A receipt that only appears on the pass tells two directories apart
    exactly when nobody is comparing them."""
    path = tmp_path / "report.json"
    broken = _report_with_payload(tmp_path)
    broken["review"]["findings"] = {"state": "not-checked", "items": []}
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert report_schema.main([str(path)]) == 1
    lines = _at_lines(capsys.readouterr().out)
    assert lines and str(tmp_path.resolve()) in lines[0], lines


def test_a_path_that_cannot_be_resolved_says_so_rather_than_echoing_it():
    """The third state, and the fixture is a measurement rather than a given:
    the condition is established by attempting the exact call the code under
    test makes, and skipped -- carrying what went untested -- when it did not
    take."""
    hostile = "reports/x" + chr(0) + ".json"
    try:
        Path(hostile).resolve()
    except (OSError, ValueError):
        pass
    else:
        pytest.skip(
            "this interpreter resolved a NUL-bearing path without raising, so the "
            "could-not-resolve condition was not established here; untested: "
            "resolved_receipt's could-not-resolve arm on {}".format(sys.platform)
        )
    text, state = report_schema.resolved_receipt(hostile)
    assert state == "could-not-resolve"
    assert "could not resolve" in text

    # Positive control in the same fixture: the resolving arm still resolves,
    # so a `could-not-resolve` for everything would not pass this pair.
    ok_text, ok_state = report_schema.resolved_receipt(".")
    assert ok_state == "resolved"
    assert os.path.isabs(ok_text)


# --- the sixth shared fact: the cwd move is per call -----------------------

#: Pinned as a phrase because that is the fact a paraphrase loses. "cd first,
#: once" and "cd on every write call" are one word apart and are the whole of
#: instance 2.
PER_CALL_ANCHOR = "every write call"

#: agents/developer.md's wording at the moment #685 was filed. Both documents
#: carried this shape; it satisfies the existing `cd <worktree_root>` anchor in
#: tests/test_content_invariants.py and says nothing about the cwd having to
#: hold at every later write.
PRIOR_ONCE_ONLY_WORDING = (
    "Run that write from the worktree root -- `cd <worktree_root>` first -- and "
    "the same for the report and the pull request payload below. These are the "
    "only writes this task makes outside every worktree, and supertool refuses a "
    "path outside the current working directory: `ERROR: path escapes cwd`."
)


def _says_per_call(text):
    return PER_CALL_ANCHOR in _collapse(text).lower()


def test_the_anchor_fires_on_the_wording_that_permitted_instance_two():
    """Must-fire. Without this the assertion below could be satisfied by an
    anchor that was already true of the text it was written against."""
    assert not _says_per_call(PRIOR_ONCE_ONLY_WORDING)


def test_both_write_route_documents_say_the_cwd_move_is_per_write_call():
    silent = [
        getattr(doc, "name", str(doc))
        for doc in WRITE_ROUTE_DOCUMENTS
        if not _says_per_call(doc.read_text(encoding="utf-8"))
    ]
    assert not silent, (
        "a write-route document tells an agent to `cd <worktree_root>` without "
        "saying the move has to hold at every write call. A shell cwd does not "
        "persist across an agent's calls, so a later bare supertool call runs "
        "from wherever the session actually is -- which is #685 instance 2, "
        "twice in one session: {}".format(silent)
    )
