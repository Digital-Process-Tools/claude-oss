"""The default branch's own CI state, as a marker beside the repository name (#856,
and #914 for the actual data source).

Nothing on the status line said whether `main` itself is currently green -- the moment
right after this loop's own merge, when the branch has a fresh commit and no concluded
CI run yet, is exactly the case nothing on the line would flag. `gh-branch` answers this
in four states (GREEN, NOT GREEN either because a leg failed or because nothing has
concluded, NO RUN, UNKNOWN); this module reaches the same four states with two cheaper
calls -- check-runs AND the combined-status endpoint -- rather than `gh-branch`'s own
per-workflow bookkeeping, because the render is one glyph, not a table.

**#914's own root cause: a single-endpoint fixture cannot discover a single-endpoint
bug.** The prior version of this file stubbed `_run` with one fabricated JSON shape
per case (`{"state": "success", "total": 3}`), which the real combined-status endpoint
never produces on an Actions-only repository -- GitHub Actions writes check-runs, not
legacy commit statuses, so `total_count` there is `0` on every commit, always. The
suite asserted the mapping from an invented input to a glyph and never asked whether
the input occurs, which is exactly why it stayed green for the whole time the function
had exactly one reachable (and wrong) outcome in this repository.

So below: `_run` is stubbed per-call now, dispatched on which endpoint the command
actually names -- a fixture that could not pass a check-runs-shaped answer through the
combined-status code path by accident, the way the single shared stub used to. And at
the bottom, one test calls the real `gh` CLI against this repository's own real default
branch and compares the verdict against `gh-branch` (the supertool op that already gets
this right) on the same SHA, per the issue's own acceptance criterion -- skipped, not
failed, when the network or the tools it needs are unavailable.

Follows #550's own shape throughout: every "must not render confidently" assertion
carries a "must render" control in the same fixture, and the stale-must-fold-to-unknown
case is exercised beside the fresh-and-correct case rather than alone.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# --------------------------------------------------------- _gh_default_branch_state


def _dispatch(check_runs=None, status=None):
    """A `_run` stand-in that answers differently per endpoint, keyed off the
    command it was actually given -- never one fixed answer for both calls the
    function under test makes. `None` for either argument means "the forge did
    not answer this call" (mirrors `_run`'s own real return on a failed call),
    distinct from a JSON string answering with zero entries."""

    def _run(command, timeout=None):
        joined = " ".join(command)
        if "check-runs" in joined:
            return check_runs
        if "/status" in joined:
            return status
        raise AssertionError("unexpected command: {}".format(command))

    return _run


def _check_runs_json(entries):
    return json.dumps({"total": len(entries), "entries": entries})


def test_all_check_runs_passed_is_green(monkeypatch):
    """The demonstration case #914 was filed over: an Actions-only repo where the
    combined-status endpoint reports nothing (`total: 0`) but check-runs carries
    real, concluded, passing data."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json(
                [{"status": "completed", "conclusion": "success"}] * 13
            ),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "green"


def test_a_failed_check_run_is_bad(monkeypatch):
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json(
                [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "completed", "conclusion": "failure"},
                ]
            ),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "bad"


def test_legacy_status_failure_is_bad_even_with_no_check_runs_at_all(monkeypatch):
    """The other direction #914 names explicitly: an external CI posting legacy
    commit statuses with zero GitHub Actions check-runs must still be read."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json([]),
            status=json.dumps({"state": "failure", "total": 1}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "bad"


def test_error_state_is_also_bad(monkeypatch):
    """`error` is not a documented value of the COMBINED endpoint's top-level
    `state` (that enum is failure/pending/success) -- it is the per-entry
    spelling one level below what this function reads. This pins the
    defensive extra branch: an undocumented top-level `error` still reads as
    `bad` rather than falling through to `None`, the conservative direction
    to guess wrong in."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json([]),
            status=json.dumps({"state": "error", "total": 1}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "bad"


def test_a_queued_check_run_is_running(monkeypatch):
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json(
                [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "queued", "conclusion": None},
                ]
            ),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "running"


def test_pending_legacy_status_with_legs_reporting_is_running(monkeypatch):
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json([]),
            status=json.dumps({"state": "pending", "total": 2}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "running"


def test_both_sources_empty_is_no_run(monkeypatch):
    """#914's own acceptance criterion: `no-run` requires BOTH sources to report
    nothing -- not one of them, which is what the old single-endpoint reading
    could never tell apart from "the other source has real data"."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json([]),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "no-run"


def test_check_runs_empty_but_status_unanswered_is_none_not_no_run(monkeypatch):
    """The merge's own edge case: check-runs genuinely came back empty, but the
    combined-status call did not answer at all. That source could still carry
    legacy statuses this function never saw -- guessing `"no-run"` here would be
    exactly the "an absence this function produced rendered as an absence on the
    branch" mistake the whole issue is about, one level up."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(check_runs=_check_runs_json([]), status=None),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") is None


def test_no_answer_from_either_source_is_none(monkeypatch):
    monkeypatch.setattr(statusline, "_run", _dispatch(check_runs=None, status=None))
    assert statusline._gh_default_branch_state("owner/repo", "main") is None


def test_unparseable_answers_are_none(monkeypatch):
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(check_runs="not json", status="not json"),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") is None


def test_startup_failure_conclusion_is_bad(monkeypatch):
    """Review finding: GitHub's documented `conclusion` enum includes
    `startup_failure` (a run/job that failed to even start), and `gh-branch`
    -- the mechanism #914 says already gets this right, and the one the live
    test below compares against -- reads it as red (its own `FAILED_STATES`
    names it explicitly). The set this module read from omitted it, which
    would have been exactly the silent divergence #914's comparison test
    exists to catch."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json(
                [{"status": "completed", "conclusion": "startup_failure"}]
            ),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "bad"


def test_all_skipped_check_runs_is_still_green(monkeypatch):
    """Review finding: `gh-branch`'s own verdict treats a leg whose conclusion
    is `skipped`/`neutral`/`manual` as benign, not red and not pending -- so a
    commit whose only legs are skipped still concludes GREEN there (nothing
    failed, nothing is moving). A per-entry `elif conclusion == "success"`
    check would have missed this: a commit with skipped-only entries has no
    `"success"` entry either, and would have fallen through to `None`
    (unknown) instead of matching `gh-branch`'s own GREEN, the exact silent
    divergence #914's comparison test exists to catch."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=_check_runs_json(
                [{"status": "completed", "conclusion": "skipped"}] * 3
            ),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") == "green"


def test_check_runs_reading_is_none_when_the_page_is_truncated(monkeypatch):
    """Self-review finding on this issue (audit round): `gh api` does not
    auto-paginate, and the check-runs call named neither `--paginate` nor
    `per_page` -- so a commit carrying more check-runs than one page could
    have its later entries (a failure among them) silently invisible to the
    scan while `total` (read straight from `.total_count`) stayed correct.
    `total == 3` with only 2 entries returned is exactly what that truncation
    looks like from here: read as `None`, the same "could not look" answer
    `_gh_external_issue_count` already gives this shape one function over,
    never guessed at from the partial page that happened to arrive."""
    monkeypatch.setattr(
        statusline,
        "_run",
        _dispatch(
            check_runs=json.dumps(
                {
                    "total": 3,
                    "entries": [
                        {"status": "completed", "conclusion": "success"},
                        {"status": "completed", "conclusion": "success"},
                    ],
                }
            ),
            status=json.dumps({"state": "pending", "total": 0}),
        ),
    )
    assert statusline._gh_default_branch_state("owner/repo", "main") is None


def test_missing_repo_or_branch_never_calls_the_forge(monkeypatch):
    calls = []
    monkeypatch.setattr(statusline, "_run", lambda *a, **k: calls.append(1) or "{}")
    assert statusline._gh_default_branch_state(None, "main") is None
    assert statusline._gh_default_branch_state("owner/repo", None) is None
    assert calls == []


# --------------------------------------------------- live, against the real forge


def _gh_branch_verdict_word(text):
    """The literal state word `gh-branch`'s own `Verdict: ` line opens with --
    `"GREEN"`, `"NOT GREEN"`, `"NO RUN"` or `"UNKNOWN"` -- or `None` when no
    such line was found.

    Review finding on this issue: an earlier version of this comparison
    parsed the `Legs: N total: P passed, F failed, R pending` tally instead,
    which drops any leg bucketed as neither passed/failed/pending (a
    `cancelled`/`stale`/otherwise-unrecognised conclusion, rendered as an
    *extra* comma term such as `2 cancelled` -- supertool's own
    `presets/_checks.py:summarize()`). `gh-branch`'s real verdict treats
    those as red (`is_red()` -- unrecognised is red on purpose, only
    `SKIPPED`/`NEUTRAL`/`MANUAL` are carved out as benign), so a commit
    carrying one would have been misread as `"green"` by the tally-only
    parse while `gh-branch` itself said `NOT GREEN` -- a spurious mismatch
    the comparison would have blamed on this module's own (correct) `"bad"`.
    The `Verdict: ` line's own leading word is what `gh-branch` actually
    concluded, not a count this function would have to re-derive redness
    from by hand.

    `"NOT GREEN"` is checked before `"GREEN"` -- `branch.py`'s own module
    comment: "NOT GREEN contains GREEN -- anything comparing these as
    substrings cannot tell a header from a finding" -- so a naive
    shortest-first or unordered check would read a real `NOT GREEN` as a
    `GREEN` match.
    """
    match = re.search(r"^Verdict: (.+)$", text, re.MULTILINE)
    if not match:
        return None
    line = match.group(1)
    for word in ("NOT GREEN", "GREEN", "NO RUN", "UNKNOWN"):
        if line.startswith(word):
            return word
    return None


def test_gh_branch_verdict_word_tells_not_green_from_green():
    """Must-fire / must-not-fire pair for the substring trap the docstring
    names: `"NOT GREEN"` is matched as itself, never folded into `"GREEN"`
    by an unordered or shortest-first check."""
    assert _gh_branch_verdict_word("Verdict: GREEN - all clear") == "GREEN"
    assert (
        _gh_branch_verdict_word("Verdict: NOT GREEN - 1 leg did not pass")
        == "NOT GREEN"
    )


def test_gh_branch_verdict_word_reads_no_run_and_unknown():
    assert _gh_branch_verdict_word("Verdict: NO RUN - zero workflow runs") == "NO RUN"
    assert _gh_branch_verdict_word("Verdict: UNKNOWN - job list absent") == "UNKNOWN"


def test_gh_branch_verdict_word_is_none_without_a_verdict_line():
    assert _gh_branch_verdict_word("no such line here at all") is None


def test_gh_branch_verdict_word_is_not_fooled_by_an_extra_leg_bucket():
    """The exact review scenario: a `NOT GREEN` verdict on a commit whose
    `Legs:` tally carries an extra `cancelled` term the old tally-only parse
    would have silently ignored."""
    text = (
        "Verdict: NOT GREEN - 1 leg on abc1234 did not pass, in `tests`.\n"
        "Legs: 3 total: 2 passed, 0 failed, 0 pending, 1 cancelled\n"
    )
    assert _gh_branch_verdict_word(text) == "NOT GREEN"


def _gh_branch_verdict(repo, sha):
    """`gh-branch`'s own read on `sha`, folded to this module's four states.
    `None` when the op could not be run or produced no parseable verdict
    line -- a real "could not compare" state, never silently read as
    agreement.

    `"NOT GREEN"` alone does not say whether something failed or is merely
    still moving (`gh-branch`'s own docstring: "NOT GREEN -- a finding.
    Something failed, or something has not finished"). Disambiguated with
    this module's own `running` reading rather than by parsing prose further
    -- `running` is a plain `status in (queued, in_progress)` / `state ==
    "pending" and total > 0` check, no part of #914's own bug (the
    combined-status `total_count == 0` gap on an Actions-only repo), so
    using it here does not make the comparison circular on the thing this
    test exists to catch."""
    supertool_bin = shutil.which("supertool")
    if supertool_bin is None:
        return None
    try:
        result = subprocess.run(
            [supertool_bin, "gh-branch:{}".format(sha)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("utf-8", "replace")
    word = _gh_branch_verdict_word(text)
    if word == "GREEN":
        return "green"
    if word == "NO RUN":
        return "no-run"
    if word in (None, "UNKNOWN"):
        return None
    # word == "NOT GREEN"
    check_runs = statusline._reading_from_check_runs(repo, sha)
    status = statusline._reading_from_combined_status(repo, sha)
    running = (check_runs and check_runs["running"]) or (status and status["running"])
    return "running" if running else "bad"


def test_real_check_runs_reading_matches_gh_branch_on_this_repos_own_head():
    """The demonstration this issue was actually filed over: not a fabricated
    payload, but this repository's own real default-branch head, read through
    the real `gh` CLI, compared against `gh-branch` (the supertool op #914 says
    already gets this right) on the same SHA. Skipped -- never failed -- when
    `gh`/`supertool` are not on PATH or the network does not answer, because an
    environmental gap here is not a claim about the code (the same three-state
    discipline this whole module is about, applied to the test that checks it)."""
    if shutil.which("gh") is None:
        pytest.skip("gh is not on PATH; this test needs the real forge")
    if shutil.which("supertool") is None:
        pytest.skip("supertool is not on PATH; nothing to compare against")
    config = statusline.repo_config(str(REPO_ROOT))
    repo = config.get("repo")
    branch = config.get("default_branch")
    if not repo or not branch:
        pytest.skip("this checkout's .oss.json names no repo/default_branch")
    sha = statusline._run(
        ["gh", "api", "repos/{}/commits/{}".format(repo, branch), "--jq", ".sha"],
        timeout=25,
    )
    if not sha:
        pytest.skip("could not resolve the default branch's head SHA over the network")
    ours = statusline._gh_default_branch_state(repo, sha)
    if ours is None:
        pytest.skip("neither source answered for this SHA")
    theirs = _gh_branch_verdict(repo, sha)
    if theirs is None:
        pytest.skip("gh-branch did not produce a parseable verdict to compare against")
    assert ours == theirs, (
        "statusline read {!r} but gh-branch read {!r} for the same commit {} -- "
        "the two mechanisms have diverged again".format(ours, theirs, sha)
    )


# ------------------------------------------------------------- _default_branch_marker


def test_marker_maps_all_four_states_to_the_documented_glyph():
    symbols = statusline._symbols(ascii_only=False)
    assert statusline._default_branch_marker("green", symbols) == symbols["ok"]
    assert statusline._default_branch_marker("bad", symbols) == symbols["bad"]
    # NOT GREEN with nothing failed (running, or nothing concluded yet) shares one
    # glyph on purpose -- both mean "not settled, look again", never "something
    # is wrong right now", which is reserved for an actual failed leg.
    assert statusline._default_branch_marker("running", symbols) == symbols["run"]
    assert statusline._default_branch_marker("no-run", symbols) == symbols["run"]
    assert statusline._default_branch_marker("unknown", symbols) == symbols["unk"]


def test_marker_is_none_when_nothing_was_ever_asked():
    """A config declaring no default branch to compare against is a deliberate
    absence of the question, not an unanswered one -- render nothing, never `?`,
    matching the channel field's own convention (#613)."""
    symbols = statusline._symbols(ascii_only=False)
    assert statusline._default_branch_marker(None, symbols) is None


def test_marker_survives_the_ascii_fallback():
    symbols = statusline._symbols(ascii_only=True)
    assert statusline._default_branch_marker("green", symbols) == symbols["ok"]
    assert statusline._default_branch_marker("bad", symbols) == symbols["bad"]


# ---------------------------------------------------------------------- render()


def _facts(default_branch_state=None, **overrides):
    facts = {
        "model": "Opus",
        "percent": 10,
        "repo_name": "claude-oss",
        "branch": "main",
        "default_branch": "main",
        "version": "0.19.0",
        "board": {},
        "release": {},
        "tick": {"state": "none"},
        "last": "12:00",
        "plugins": [],
        "channel": None,
        "default_branch_state": default_branch_state,
    }
    facts.update(overrides)
    return facts


def test_render_puts_the_marker_beside_the_repo_name_when_green():
    line = statusline.render(_facts("green"), ascii_only=True)
    assert line.startswith("Opus . 10% | claude-oss" + statusline._symbols(True)["ok"])


def test_render_shows_bad_when_a_leg_failed():
    line = statusline.render(_facts("bad"), ascii_only=True)
    assert "claude-oss" + statusline._symbols(True)["bad"] in line


def test_render_omits_the_marker_when_nothing_was_asked():
    line = statusline.render(_facts(None), ascii_only=True)
    # No marker glyph glued onto the repo name -- plain "claude-oss" is followed
    # immediately by the separator/dot/version, never by ok/bad/run/unk.
    assert "claude-oss" + statusline._symbols(True)["ok"] not in line
    assert "claude-oss" + statusline._symbols(True)["bad"] not in line
    assert "claude-oss" + statusline._symbols(True)["run"] not in line
    assert "claude-oss" + statusline._symbols(True)["unk"] not in line
    assert line.split(" | ")[1].startswith("claude-oss ")


# --------------------------------------------------------------------- gather()


def _cache(default_branch_state, fetched_at, now, stale_after=None):
    document = {"repo": "owner/repo", "fetched_at": fetched_at, "prs": 0, "issues": 0}
    if default_branch_state is not None:
        document["default_branch_state"] = default_branch_state
    if stale_after is not None:
        document["stale_after"] = stale_after
    return document


def test_gather_reads_a_fresh_green_reading_through(tmp_path, monkeypatch):
    now = 1_000_000.0
    cache = _cache("green", now - 1, now)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(
        statusline, "_scan_transcript", lambda path, n: ([], False, None)
    )
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] == "green"


def test_gather_folds_a_stale_reading_to_unknown_even_though_it_says_green(
    tmp_path, monkeypatch
):
    """The must-not-render-confidently case. A reading older than `REFRESH_AFTER`
    must never render as a confident `ok`, no matter what it says (#515)."""
    now = 1_000_000.0
    cache = _cache("green", now - statusline.REFRESH_AFTER - 1, now)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: True)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(
        statusline, "_scan_transcript", lambda path, n: ([], False, None)
    )
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] == "unknown"


def test_gather_folds_to_unknown_when_stale_after_says_so_even_inside_the_interval(
    tmp_path, monkeypatch
):
    """The other half of #515/#516: `stale_after` (written by the merge/close hook,
    #516) can mark a reading stale before `REFRESH_AFTER` alone would -- exactly
    the moment this issue is about, right after this loop's own merge."""
    now = 1_000_000.0
    cache = _cache("green", now - 1, now, stale_after=now - 1)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(
        statusline,
        "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main"},
    )
    # board_is_due is the real function here (not stubbed), so `stale_after` is
    # actually what does the work rather than the stub answering for it.
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(
        statusline, "_scan_transcript", lambda path, n: ([], False, None)
    )
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] == "unknown"


def test_gather_is_none_when_no_default_branch_is_configured(tmp_path, monkeypatch):
    now = 1_000_000.0
    cache = _cache("green", now - 1, now)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "owner/repo"})
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})
    monkeypatch.setattr(
        statusline, "_scan_transcript", lambda path, n: ([], False, None)
    )
    facts = statusline.gather({}, ".", now=now)
    assert facts["default_branch_state"] is None
