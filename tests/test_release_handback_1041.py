"""Classify a releaser's own final message -- #1041.

`agents/releaser.md` only defined three states (`released` / `refused` /
`could-not-run`). Observed three times in one release
(Digital-Process-Tools/claude-jit-context, 0.8.0): a releaser reaching a CI
wait has none of those three to report, and closed instead with prose
promising to resume -- a promise it cannot keep, since its context dies the
instant it reports. `agents/sub-manager.md` got exactly this fix at #818
(`TICK: paused` with `WAIT-DISPATCH:`/`WAIT-OBSERVABLE:`), classified by
`scripts/tick_handback.py`. No equivalent classifier existed for a
releaser's own report before this module -- this is that classifier, over a
`RELEASE:` header rather than a `TICK:` one, reusing `tick_handback.py`'s
own generic helpers (the enum normaliser, the single-match field finder,
the resume-promise pattern) rather than re-deriving them.

Every negative assertion here carries a positive control in the same
fixture, per this repo's own rule that a "must not fire" case is worthless
without a "must fire" case beside it.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release_handback.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import release_handback  # noqa: E402


def test_released_with_tag_classifies():
    verdict = release_handback.classify(
        "RELEASE: released\n"
        "VERSION: 0.26.0\n"
        "TAG: v0.26.0\n"
        "SURFACES: tagged and released\n"
    )
    assert verdict["state"] == "released"
    assert verdict["tag"] == "v0.26.0"


def test_released_missing_tag_is_could_not_classify():
    verdict = release_handback.classify("RELEASE: released\nVERSION: 0.26.0\n")
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "released"


def test_refused_with_gate_classifies():
    verdict = release_handback.classify(
        "RELEASE: refused\nGATE: 3, security audit\nfindings: two, non-blocking\n"
    )
    assert verdict["state"] == "refused"
    assert "3" in verdict["gate"]


def test_refused_missing_gate_is_could_not_classify():
    verdict = release_handback.classify("RELEASE: refused\nsome findings\n")
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "refused"


def test_could_not_run_with_reason_classifies():
    verdict = release_handback.classify(
        "RELEASE: could-not-run\nREASON: worktree could not be cut\n"
    )
    assert verdict["state"] == "could-not-run"


def test_could_not_run_missing_reason_is_could_not_classify():
    verdict = release_handback.classify("RELEASE: could-not-run\n")
    assert verdict["state"] == "could-not-classify"


def test_paused_with_both_wait_fields_classifies():
    """The new state this issue adds: a releaser mid-flight on a CI wait,
    naming the same two facts #818 gave the sub-manager."""
    verdict = release_handback.classify(
        "RELEASE: paused\n"
        "GATE: 1, default branch green\n"
        "WAIT-DISPATCH: merge commit 80fcb3a pushed to main\n"
        "WAIT-OBSERVABLE: CI concludes on 80fcb3a\n"
    )
    assert verdict["state"] == "paused"
    assert "80fcb3a" in verdict["wait_dispatch"]
    assert "concludes" in verdict["wait_observable"]


def test_positive_control_paused_is_not_could_not_run():
    """Negative-with-control: paused must not collapse onto could-not-run,
    which is this issue's own point -- a release mid-flight is not one that
    failed to start."""
    paused = release_handback.classify(
        "RELEASE: paused\nWAIT-DISPATCH: x\nWAIT-OBSERVABLE: y\n"
    )
    never_ran = release_handback.classify("RELEASE: could-not-run\nREASON: x\n")
    assert paused["state"] != never_ran["state"]


def test_paused_missing_wait_observable_is_could_not_classify():
    verdict = release_handback.classify("RELEASE: paused\nWAIT-DISPATCH: x\n")
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "paused"


def test_empty_message_is_returned_nothing_not_could_not_classify():
    verdict = release_handback.classify("")
    assert verdict["state"] == "returned-nothing"


def test_no_header_but_resume_promise_names_the_paused_shape():
    """#1041's own observed shape: no RELEASE: header, prose promising to
    resume once CI reports back. The reason should point at RELEASE: paused
    rather than only saying no header was found."""
    verdict = release_handback.classify(
        "Waiting for CI to conclude on the merge commit 80fcb3a before "
        "tagging. I'll resume once the background check notifies completion."
    )
    assert verdict["state"] == "could-not-classify"
    assert "paused" in verdict["reason"].lower()


def test_positive_control_ordinary_prose_with_no_header_gives_generic_reason():
    """Positive control for the promise-detection test above: prose that is
    NOT a resume promise gets the generic no-header reason, so the
    promise-specific wording is not firing on every headerless message."""
    verdict = release_handback.classify("no sentinel here at all, just notes")
    assert verdict["state"] == "could-not-classify"
    assert "no RELEASE: header" in verdict["reason"]


def test_two_headers_is_could_not_classify():
    verdict = release_handback.classify(
        "RELEASE: released\nTAG: v1\nRELEASE: refused\nGATE: 2\n"
    )
    assert verdict["state"] == "could-not-classify"


def test_unrecognised_state_is_could_not_classify():
    verdict = release_handback.classify("RELEASE: pending\nsome text\n")
    assert verdict["state"] == "could-not-classify"


def test_released_and_returned_nothing_do_not_render_identically():
    released = release_handback.classify("RELEASE: released\nTAG: v1\n")
    died = release_handback.classify(None)
    assert released["state"] != died["state"]


def _run(stdin_text, extra_args=()):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *extra_args],
        subject="the verdict and exit code release_handback.py's CLI produces",
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_exit_codes_are_all_distinct():
    released = _run("RELEASE: released\nTAG: v1\n")
    refused = _run("RELEASE: refused\nGATE: 3\n")
    could_not_run = _run("RELEASE: could-not-run\nREASON: x\n")
    paused = _run("RELEASE: paused\nWAIT-DISPATCH: x\nWAIT-OBSERVABLE: y\n")
    returned_nothing = _run("")
    could_not_classify = _run("no sentinel here at all")
    codes = {
        released.returncode,
        refused.returncode,
        could_not_run.returncode,
        paused.returncode,
        returned_nothing.returncode,
        could_not_classify.returncode,
    }
    assert "VERDICT: paused" in paused.stdout
    assert len(codes) == 6, (
        released.returncode,
        refused.returncode,
        could_not_run.returncode,
        paused.returncode,
        returned_nothing.returncode,
        could_not_classify.returncode,
    )
