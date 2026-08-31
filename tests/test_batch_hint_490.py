"""#490: 21.5% of tool turns are consecutive single-op read-only supertool
calls that one batched call would have collapsed, and prose asking agents to
batch (agents/developer.md:181, before this fix) measured at zero effect
across 612 transcripts and an A/B trial (see the issue's comments). This is
the hook that replaces the paragraph: it costs nothing on a clean run and
emits one line only when a real run is seen.

Three states throughout, on purpose (CLAUDE.md's own defect class): a streak
below threshold is silence because *no run was long enough*; an unrecognised
command is *could not classify* and must not silently count as either a clean
break or part of the streak; only a genuine streak of classified read-only
single-op calls fires.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import batch_hint  # noqa: E402
import spawn_guard  # noqa: E402


# The classification these tests exercise now derives from `supertool
# 'ops:roster'` rather than a hardcoded copy (#537) -- a real subprocess call
# out to that binary is neither necessary nor safe inside a unit test (a CI
# runner is not guaranteed to have it on PATH, and a test that silently
# depended on it would pass here and fail there for a reason with nothing to
# do with the code under test). Fix the roster every test in this file sees
# to a snapshot equivalent to the one #537 deleted, so these assertions keep
# meaning what they always meant.
_FIXED_ROSTER = {
    "write": [
        "append", "batch", "edit", "format", "format_staged", "gc",
        "git-checkout", "git-commit", "git-merge", "git-resolve", "paste",
        "rename", "replace", "replace_lines", "vim",
    ],
    "external": [
        "channel", "gh-batch-follow", "gh-batch-star", "gh-follow",
        "gh-issue-create", "gh-pr-create", "gh-pr-edit", "gh-pr-merge",
        "gh-star", "git-push", "radar", "unwatch", "watch",
    ],
    "read": [
        "around", "around_line", "between", "check", "cwd", "diag", "diff",
        "gh-branch", "gh-check", "gh-find-followable", "gh-find-starable",
        "gh-following", "gh-issue", "gh-issues", "gh-job", "gh-labels",
        "gh-pr", "gh-prs", "gh-run", "gh-starred", "git-blame",
        "git-conflicts", "git-diff", "git-diverge", "git-investigate",
        "git-status", "git-trail", "git-worktrees", "glob", "grep",
        "grep_around", "guard", "head", "help", "hover", "introduction",
        "ls", "map", "ops", "ops-compact", "output-format", "read",
        "registry", "replace_dry", "repo", "resolve", "stat", "tail",
        "tree", "validate", "validate_staged", "version", "watches", "wc",
        "workspace",
    ],
}


@pytest.fixture(autouse=True)
def _fixed_roster(monkeypatch):
    monkeypatch.setattr(batch_hint, "_ROSTER_CACHE", dict(_FIXED_ROSTER))


# ---------------------------------------------------------------------------
# classify_command: the three-way split a single command text resolves to.
# ---------------------------------------------------------------------------

def test_single_op_read_call_is_single_readonly():
    assert batch_hint.classify_command("supertool 'read:foo.py'") == "single_readonly"


def test_cd_prefix_does_not_defeat_classification():
    # 77% of real calls carry this prefix (harness resets cwd every call, #490
    # comment); stripping it is required or the hook never fires in practice.
    cmd = "cd /Users/x/worktree && supertool 'grep:foo:bar.py:10:2'"
    assert batch_hint.classify_command(cmd) == "single_readonly"


def test_already_batched_call_is_not_an_offender():
    assert batch_hint.classify_command("supertool 'read:a' 'wc:b'") == "not_offender"


def test_mutating_payload_call_is_not_an_offender():
    # edit:@-, paste:@- and batch:@- all take a stdin payload; the "@-" marker
    # is the mutation signal used throughout this repo's own conventions.
    assert batch_hint.classify_command("supertool 'edit:@-' <<'EOF'\nx\nEOF") == "not_offender"


def test_inline_argument_mutation_form_is_not_an_offender():
    # This repo documents a second mutation shape that never uses "@-" at
    # all -- `edit:::OLD:::NEW:::PATH` / `paste:::PATH:::CONTENT` -- so a
    # classifier keyed on the "@-" substring alone misses it entirely.
    assert batch_hint.classify_command("supertool 'edit:::OLD:::NEW:::path.py'") == "not_offender"
    assert batch_hint.classify_command("supertool 'paste:::path.py:::content'") == "not_offender"


def test_a_read_op_argument_containing_the_mutation_marker_text_is_still_readonly():
    # The opposite failure of the same substring check: a `grep` pattern
    # that happens to contain the literal text "@-" is a read, not a
    # mutation. Classification is by the op's own name, never by scanning
    # its argument for a marker that can appear anywhere by coincidence.
    assert batch_hint.classify_command("supertool 'grep:foo@-bar:file.py'") == "single_readonly"


def test_an_op_name_this_module_does_not_recognise_is_unknown():
    # Third state again: an op the roster grew to include after this
    # module's own static copy was last derived must not silently pass as
    # either a confident read or a confident mutation.
    assert batch_hint.classify_command("supertool 'some-future-op:x'") == "unknown"


def test_an_unrecognised_op_with_a_payload_marker_is_still_a_mutation():
    # The "@-" substring stays as a fallback signal for exactly the op names
    # this module has not yet been told about -- a new write op would still
    # be caught, just less precisely than one already in the roster copy.
    assert batch_hint.classify_command("supertool 'some-future-op:@-'") == "not_offender"


def test_non_supertool_command_is_not_an_offender():
    assert batch_hint.classify_command("python3 -m pytest tests/ -q") == "not_offender"


def test_chained_commands_are_not_an_offender():
    # a second command chained on is an ordering dependency this hook must not
    # fire on (the issue's own "must not fire" constraint).
    cmd = "supertool 'read:a' && rm a"
    assert batch_hint.classify_command(cmd) == "not_offender"


def test_unparseable_command_is_unknown_not_clean():
    # garbled quoting: cannot tell whether this is one op or several.
    cmd = "supertool 'read:a\'oops"
    assert batch_hint.classify_command(cmd) == "unknown"


# ---------------------------------------------------------------------------
# update_state: the streak, the threshold, and the third state's effect on it.
# ---------------------------------------------------------------------------

def test_fires_after_threshold_consecutive_single_readonly_calls():
    state = {"streak": 0, "unknown": 0, "fired": 0}
    msg = None
    for _ in range(batch_hint.THRESHOLD):
        state, msg = batch_hint.update_state(state, "single_readonly")
    assert msg is not None
    assert "#490" in msg
    assert state["streak"] == 0  # resets after firing so it doesn't repeat every call


def test_does_not_fire_below_threshold():
    state = {"streak": 0, "unknown": 0, "fired": 0}
    msg = None
    for _ in range(batch_hint.THRESHOLD - 1):
        state, msg = batch_hint.update_state(state, "single_readonly")
    assert msg is None


def test_not_offender_breaks_the_streak():
    state = {"streak": 0, "unknown": 0, "fired": 0}
    for _ in range(batch_hint.THRESHOLD - 1):
        state, _ = batch_hint.update_state(state, "single_readonly")
    state, msg = batch_hint.update_state(state, "not_offender")
    assert msg is None
    assert state["streak"] == 0


def test_a_mutation_after_a_short_streak_then_resuming_still_fires_eventually():
    # positive control paired with the negative one above: the mechanism does
    # still fire once a genuine streak reforms after a real break.
    state = {"streak": 0, "unknown": 0, "fired": 0}
    for _ in range(batch_hint.THRESHOLD - 1):
        state, _ = batch_hint.update_state(state, "single_readonly")
    state, msg = batch_hint.update_state(state, "not_offender")
    assert msg is None
    for _ in range(batch_hint.THRESHOLD):
        state, msg = batch_hint.update_state(state, "single_readonly")
    assert msg is not None


def test_unknown_call_does_not_silently_reset_a_live_streak():
    # third-state requirement: an unclassifiable call in the middle of a real
    # streak must not be read as "clean" and must not erase progress.
    state = {"streak": 0, "unknown": 0, "fired": 0}
    for _ in range(batch_hint.THRESHOLD - 1):
        state, _ = batch_hint.update_state(state, "single_readonly")
    state, msg = batch_hint.update_state(state, "unknown")
    assert msg is None
    assert state["streak"] == batch_hint.THRESHOLD - 1  # unchanged, not reset
    assert state["unknown"] == 1


def test_all_unknown_run_is_distinguishable_from_all_clean_run():
    # the defect class this repo is named after: two silences must not look
    # identical when their causes differ.
    clean_state = {"streak": 0, "unknown": 0, "fired": 0}
    for _ in range(5):
        clean_state, msg = batch_hint.update_state(clean_state, "not_offender")
    assert msg is None

    unknown_state = {"streak": 0, "unknown": 0, "fired": 0}
    for _ in range(5):
        unknown_state, msg = batch_hint.update_state(unknown_state, "unknown")
    assert msg is None

    assert clean_state["unknown"] == 0
    assert unknown_state["unknown"] == 5
    assert clean_state != unknown_state


# ---------------------------------------------------------------------------
# main(): the actual hook entry point, end to end, across process boundaries.
# ---------------------------------------------------------------------------

def _run_hook(tmp_path, session_id, command):
    # A fresh subprocess invocation of the hook script would otherwise derive
    # the roster itself, which means shelling out to the real `supertool`
    # binary (#537) -- not guaranteed to be on PATH in CI. Seed the disk
    # cache `roster()` reads before deriving, so these end-to-end tests never
    # depend on it being installed.
    roster_cache = Path(tmp_path) / "oss-batch-hint-roster.json"
    if not roster_cache.exists():
        roster_cache.write_text(json.dumps(_FIXED_ROSTER), encoding="utf-8")

    payload = json.dumps({
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })
    env = {"BATCH_HINT_STATE_DIR": str(tmp_path)}
    import os
    full_env = dict(os.environ)
    full_env.update(env)
    result = spawn_guard.run(
        [sys.executable, str(ROOT / "scripts" / "batch_hint.py")],
        subject="what the hook answers for this call, and so the whole streak it is part of",
        input=payload,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else {}


def test_hook_end_to_end_fires_only_on_the_threshold_call(tmp_path):
    session = "test-session-490"
    out1 = _run_hook(tmp_path, session, "supertool 'read:a.py'")
    out2 = _run_hook(tmp_path, session, "supertool 'grep:x:b.py'")
    out3 = _run_hook(tmp_path, session, "supertool 'wc:c.py'")

    def hint(out):
        return out.get("hookSpecificOutput", {}).get("additionalContext")

    assert hint(out1) is None
    assert hint(out2) is None
    assert hint(out3) is not None
    assert "#490" in hint(out3)


def test_hook_end_to_end_never_fires_on_a_run_it_could_not_classify(tmp_path):
    session = "test-session-490-unknown"
    for _ in range(6):
        out = _run_hook(tmp_path, session, "supertool 'read:a\'oops")
    assert out.get("hookSpecificOutput", {}).get("additionalContext") is None


def test_status_cli_makes_the_unknown_counter_observable(tmp_path):
    # The third state has to be *readable*, not just correctly kept
    # internally -- this is the read side the self-review asked for.
    session = "test-session-490-status"
    _run_hook(tmp_path, session, "supertool 'read:a\'oops")
    _run_hook(tmp_path, session, "supertool 'read:a\'oops")
    env = {**__import__("os").environ, "BATCH_HINT_STATE_DIR": str(tmp_path)}
    result = spawn_guard.run(
        [sys.executable, str(ROOT / "scripts" / "batch_hint.py"), "--status", session],
        subject="whether --status makes the unknown counter observable",
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["unknown"] == 2
    assert state["streak"] == 0
