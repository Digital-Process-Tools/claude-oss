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
        line.strip() for line in captured.splitlines() if line.strip().startswith("at:")
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
    # 15, not 30: a doubled paragraph break is two escapes and counts once,
    # because only the first of the pair is followed by something that is not a
    # letter or a digit. See the Windows-path test below for why that narrowing
    # exists at all.
    assert "15" in errors[0] and "4" in errors[0], errors[0]
    assert "pr_body.payload.body" in errors[0]


def test_a_windows_path_in_prose_is_not_read_as_a_doubled_escape():
    """Found by review, and it is the difference between an absence detector
    whose finding is strong and one nobody can trust.

    A backslash followed by an `n` is not an escape when the `n` merely begins
    the next path component -- and an unbackticked Windows path in a one-line
    body has zero real newlines, so a naive substring count refuses it outright.
    That is a body somebody legitimately wrote, in a repository that ships
    Windows-path fixes, and refusing it contradicts the docstring beside the
    check."""
    windows = (
        "Restores the fallback for C:{b}Users{b}nina{b}notes and "
        "C:{b}Users{b}noah{b}file so tests pass on Windows.".format(b=chr(92))
    )
    assert _body_errors(windows) == [], _body_errors(windows)

    # Must-fire in the same fixture: the same sentence with the escapes shaped
    # like line breaks rather than like path separators is still refused, so the
    # pass above is a narrowing and not the check going quiet.
    damaged = windows.replace(chr(92) + "n", chr(92) + "n ")
    assert _body_errors(damaged) != [], damaged


def test_only_line_break_shaped_escapes_are_counted():
    """Control on the narrowing itself. The fixture still carries 30 raw
    backslash-n substrings; what the check counts is the 15 that are shaped
    like line breaks. Without this, a reader cannot tell the narrowing from the
    counter being broken."""
    assert DAMAGED_BODY.count(BACKSLASH_N) == 30
    assert report_schema.count_line_break_escapes(DAMAGED_BODY) == 15
    windows = "C:{b}Users{b}nina{b}notes".format(b=chr(92))
    assert windows.count(BACKSLASH_N) == 2
    assert report_schema.count_line_break_escapes(windows) == 0


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

    spanned = (
        "One line of prose mentioning `{n}` `{n}` `{n}` inside code spans.".format(
            n=BACKSLASH_N
        )
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
    assert any("backslash-n" in e for e in errors), errors


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

    assert lines[0] and lines[1], "no `at:` receipt was printed at all: {}".format(
        lines
    )
    assert lines[0] != lines[1], (
        "two reports in two directories produced the same receipt, which is the "
        "silence #685 is about: {}".format(lines)
    )
    # Asserted on the trailing components rather than on the whole resolved
    # string, and joined with `os.sep` rather than a literal slash. Two reasons,
    # both cross-platform: `_one_line` folds every byte outside printable ASCII
    # to `?`, so a tmp root under a non-ASCII account name would fail a
    # whole-string containment test about nothing the receipt got wrong; and it
    # truncates at 300, which cuts the tail. Truncation is the right end to lose
    # for this receipt -- the head is the clone-or-worktree-root half #685 is
    # about -- but it makes a whole-string test brittle on a deep Windows temp
    # path for no gain.
    assert lines[0][0].endswith(os.sep.join(("wt", "reports", "report.json"))), lines[0]
    assert lines[1][0].endswith(os.sep.join(("clone", "reports", "report.json"))), (
        lines[1]
    )


def test_an_invalid_report_also_names_where_it_looked(tmp_path, capsys):
    """A receipt that only appears on the pass tells two directories apart
    exactly when nobody is comparing them."""
    path = tmp_path / "report.json"
    broken = _report_with_payload(tmp_path)
    broken["review"]["findings"] = {"state": "not-checked", "items": []}
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert report_schema.main([str(path)]) == 1
    lines = _at_lines(capsys.readouterr().out)
    assert lines, "no `at:` receipt under an INVALID verdict"
    stated = lines[0][len("at:") :].strip()
    assert os.path.isabs(stated), stated
    assert stated.endswith("report.json"), stated


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
    # The sentence must NOT itself open with "could not resolve": `main` renders
    # it under a `could-not-resolve --` prefix, and a helper that repeats the
    # prefix prints the words twice on the one line a reader is scanning.
    assert not text.lower().startswith("could not resolve"), text
    assert "absolute" in text, text

    # Positive control in the same fixture: the resolving arm still resolves,
    # so a `could-not-resolve` for everything would not pass this pair.
    ok_text, ok_state = report_schema.resolved_receipt(".")
    assert ok_state == "resolved"
    assert os.path.isabs(ok_text)


def test_main_on_an_unresolvable_path_blames_the_path_and_not_the_schema(capsys):
    """Adjacent to #685 and found while pinning the receipt: `inspect_file`
    guarded its read with `except OSError` alone, so a NUL-bearing report path
    raised `ValueError` out of `read_text` and landed in `main`'s
    `except ValueError`, which prints *the schema itself is unusable*. A report
    path crashing the check, reported as the maintainer's own configuration
    being broken -- a wrong answer delivered calmly, which is worse than the
    traceback it replaced.

    This is also the only route that exercises the composed `at:` line for the
    could-not-resolve state, which is why the two live in one test."""
    hostile = "reports/x" + chr(0) + ".json"
    try:
        Path(hostile).read_text(encoding="utf-8")
    except ValueError:
        pass
    except OSError:
        pytest.skip(
            "this interpreter raised OSError rather than ValueError for a "
            "NUL-bearing path, so the arm under test was not established here; "
            "untested: inspect_file's ValueError arm on {}".format(sys.platform)
        )
    else:
        pytest.skip(
            "this interpreter read a NUL-bearing path without raising; "
            "untested: inspect_file's ValueError arm on {}".format(sys.platform)
        )

    assert report_schema.main([hostile]) == 1
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "the schema itself is unusable" not in combined, combined
    assert "cannot read the report" in combined, combined

    lines = _at_lines(out.out)
    assert lines, "no `at:` receipt for a path that could not be resolved"
    assert lines[0].startswith("at: could-not-resolve -- "), lines[0]
    assert "could-not-resolve -- could not resolve" not in lines[0], lines[0]


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
