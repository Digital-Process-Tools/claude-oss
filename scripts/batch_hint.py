"""Batching hint hook (#490).

612 agent transcripts show turns issuing one tool call 99.996% of the time,
and 21.5% of all tool turns sit inside runs of consecutive single-op
read-only supertool calls -- exactly the case `supertool 'op1' 'op2'` already
collapses into one call, at zero cost, with no payload. A sentence in
`agents/developer.md` asking for this was tried and measured: 28 `batch:`
uses across 612 agents and a controlled A/B where the treatment arm (a full
cost model in the brief) came out 6% *more* expensive in single-op rate, not
less. Prose is charged on every turn whether or not it ever applies; a hook
is charged only at the moment it fires. This module is the hook.

It is wired as a PostToolUse hook (see hooks/hooks.json) rather than a
PreToolUse one on purpose: it must never block or deny the call in question
-- the issue is explicit that this is a hint, not the no-cut guard -- and
PostToolUse fires after the tool has already run, which makes "advisory
only" true by construction rather than by convention.

Three states, never two (CLAUDE.md's own defect class):

- a streak below THRESHOLD is silence because no run long enough was seen;
- an unparseable command is `unknown` and must neither break a live streak
  nor silently count as a "clean" one -- see `test_unknown_call_does_not_
  silently_reset_a_live_streak` and its sibling in the all-unknown test;
- only a genuine streak of classified single-op read-only calls fires.

What this deliberately does NOT try to detect, and why that is a bounded
risk rather than an omission: whether one call's argument depends on the
previous call's result. That is a data-flow question no static read of the
command text answers, and the issue names it explicitly as a "must not
fire" case. The mitigation is the mechanism itself -- this hook only ever
adds one line of advisory text and never blocks, so a false positive costs
a sentence the agent is free to ignore, not a denied command.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

THRESHOLD = 3
# Reasoning for 3, not 2 or 6 (recorded so a future change can argue with a
# number rather than a vibe): runs of length 2 are the single most common
# shape in the 612-transcript sample (456 of ~1,000+ runs) and are the
# lowest-value case to flag -- often a single incidental follow-up read, not
# a batchable plan seen in advance. Runs of length >=3 still carry 4,414 of
# the 5,326 "collapsible" turns (83%), so raising the bar to 3 removes most
# of the noisiest, lowest-value firings while keeping the great majority of
# the turns actually worth collapsing. This is a judgement call, not a
# measurement; the number to change first if it fires too often is this one.

_MUTATION_MARKER = "@-"  # edit:@-, paste:@-, batch:@- -- fallback for an op this
                          # module does not recognise by name (see below)
_CHAIN_OPERATORS = re.compile(r"(?<!\\)(&&|\|\||;)")
_CD_PREFIX = re.compile(r"^\s*cd\s+\S+\s*&&\s*")
_SUPERTOOL_CALL = re.compile(
    r"^(?:\./)?supertool\s+((?:'[^']*'\s*)+)$"
)
_QUOTED_ARG = re.compile(r"'([^']*)'")

# Derived from `supertool 'ops:roster'` (2026-08-22), which is the single
# authority for which ops write or reach outside this tree ("*"/"!") versus
# read ("unmarked") -- see that op's own text, quoted in CLAUDE.md, on why a
# second copy of this classification drifts. This module needs the answer to
# a different question than a permission grant does (batchable vs not, not
# read vs write access), so it keeps its own copy rather than shelling out to
# supertool on every single Bash call -- but it is a copy of a published
# classification, not a guess, and it is dated so staleness is visible.
# Re-derive with: supertool 'ops:roster'
_WRITE_OP_PREFIXES = frozenset({
    "append", "batch", "edit", "format", "format_staged", "gc",
    "git-checkout", "git-commit", "git-merge", "git-resolve", "paste",
    "rename", "replace", "replace_lines", "vim",
})
_EXTERNAL_OP_PREFIXES = frozenset({
    "channel", "gh-batch-follow", "gh-batch-star", "gh-follow",
    "gh-issue-create", "gh-pr-create", "gh-pr-edit", "gh-pr-merge",
    "gh-star", "git-push", "radar", "unwatch", "watch",
})
_READ_OP_PREFIXES = frozenset({
    "around", "around_line", "between", "check", "cwd", "diag", "diff",
    "gh-branch", "gh-check", "gh-find-followable", "gh-find-starable",
    "gh-following", "gh-issue", "gh-issues", "gh-job", "gh-labels",
    "gh-pr", "gh-prs", "gh-run", "gh-starred", "git-blame", "git-conflicts",
    "git-diff", "git-diverge", "git-investigate", "git-status", "git-trail",
    "git-worktrees", "glob", "grep", "grep_around", "guard", "head", "help",
    "hover", "introduction", "ls", "map", "ops", "ops-compact",
    "output-format", "read", "registry", "replace_dry", "repo", "resolve",
    "stat", "tail", "tree", "validate", "validate_staged", "version",
    "watches", "wc", "workspace",
})


def _op_verdict(op: str) -> str:
    """Classify one op string by its own name, not by scanning its argument.

    Fixes the false positive/negative pair a substring search on the whole
    op string produces: `'grep:foo@-bar:file.py'` is a read whose *pattern*
    happens to contain "@-" (false not_offender under a substring check),
    and `'edit:::OLD:::NEW:::path.py'` is this repo's inline-argument
    mutation form, which never contains "@-" at all (false single_readonly
    under the same check). Looking up the op's own name against the
    published roster gets both right.
    """
    prefix = op.split(":", 1)[0]
    if prefix in _WRITE_OP_PREFIXES or prefix in _EXTERNAL_OP_PREFIXES:
        return "not_offender"
    if prefix in _READ_OP_PREFIXES:
        return "single_readonly"
    # An op name this module does not recognise -- the roster grew since the
    # comment above was dated, or this is not really an op call at all. A
    # trailing payload marker is still a strong, self-contained signal that
    # this consumes stdin and mutates; anything else is genuinely unknown
    # rather than guessed at.
    if op.endswith(_MUTATION_MARKER):
        return "not_offender"
    return "unknown"


def _state_dir() -> Path:
    override = os.environ.get("BATCH_HINT_STATE_DIR")
    if override:
        return Path(override)
    import tempfile

    return Path(tempfile.gettempdir())


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "unknown-session"
    return _state_dir() / f"oss-batch-hint-{safe}.json"


def classify_command(command: str) -> str:
    """Return "single_readonly", "not_offender" or "unknown".

    "single_readonly" -- exactly one supertool invocation, exactly one op
    argument, and that op is not a mutating (`@-`-payload) one. A candidate
    to have been batched with whatever the next call turns out to be.

    "not_offender" -- classified with confidence and NOT a candidate: already
    multi-op, a mutation, chained with another command, or not a supertool
    call at all.

    "unknown" -- could not classify with confidence (unbalanced quoting and
    similar). Must never be treated as either of the above.
    """
    command = command.strip()
    if not command:
        return "unknown"

    # An unbalanced quote makes it impossible to say where one argument ends
    # and the next begins -- a data question, not a confident negative.
    if command.count("'") % 2 != 0:
        return "unknown"

    stripped = _CD_PREFIX.sub("", command, count=1)

    # Remove quoted spans before checking for chain operators, so a `&&`
    # or `;` *inside* an op argument (part of a shell one-liner op) is not
    # mistaken for real chaining. A chained command may depend on another
    # command's result, which is exactly the "could not be batched" case the
    # issue calls out by name -- so it is a confident not_offender, not
    # unknown.
    unquoted = _QUOTED_ARG.sub("", stripped)
    if _CHAIN_OPERATORS.search(unquoted):
        return "not_offender"

    if not re.search(r"(?:^|\s)(?:\./)?supertool(?:\s|$)", stripped):
        return "not_offender"  # confidently not a supertool call at all

    match = _SUPERTOOL_CALL.match(stripped)
    if not match:
        # Looks like it is trying to be a supertool call (the word is
        # there) but does not parse cleanly -- ambiguous, not a confident
        # negative. Must not silently count as batchable-and-clear either.
        # A heredoc-carrying payload call (edit:@- <<'EOF' ...) lands here
        # too, since the heredoc body -- and the quote the delimiter itself
        # opens, e.g. <<'EOF' -- defeats the strict single-line shape match.
        # Only trust the "take the first op" fallback when "<<" is actually
        # present -- otherwise a plain malformed/truncated command (a stray
        # trailing token after a closed quote, say) would read as a clean
        # single op instead of the "unknown" it actually is.
        if "<<" in stripped:
            first_op = re.search(r"(?:^|\s)(?:\./)?supertool\s+'([^']*)'", stripped)
            if first_op:
                return _op_verdict(first_op.group(1))
        return "unknown"

    ops = _QUOTED_ARG.findall(match.group(1))
    if not ops:
        return "unknown"
    if len(ops) > 1:
        return "not_offender"  # already batched -- exactly what this hook wants

    return _op_verdict(ops[0])


def update_state(state: dict, classification: str) -> tuple[dict, "str | None"]:
    """Advance (streak, unknown, fired) by one classified call.

    Returns the new state and a one-line message, or None when nothing
    fires this call. Firing resets the streak so the hint is not repeated
    on every subsequent call of an already-flagged run.
    """
    state = dict(state)
    message = None

    if classification == "single_readonly":
        state["streak"] = state.get("streak", 0) + 1
        if state["streak"] >= THRESHOLD:
            state["fired"] = state.get("fired", 0) + 1
            message = (
                f"{state['streak']} consecutive single-op read calls -- "
                f"`supertool 'op1' 'op2' ...` runs them in one call, no payload "
                f"needed (#490)."
            )
            state["streak"] = 0
    elif classification == "not_offender":
        state["streak"] = 0
    elif classification == "unknown":
        # Third state: leave the streak exactly as it was. An unclassifiable
        # call must not read as a clean break (which would silently forgive
        # a real run) and must not count toward the streak either (which
        # would fire on evidence we do not actually have).
        state["unknown"] = state.get("unknown", 0) + 1
    else:  # pragma: no cover -- defensive, classify_command has 3 outputs only
        raise ValueError(f"unrecognised classification: {classification!r}")

    return state, message


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"streak": 0, "unknown": 0, "fired": 0}


def _save_state(path: Path, state: dict) -> None:
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass  # best-effort; a lost streak is silence, never a false fire


def status(session_id: str) -> dict:
    """Read back one session's counters -- the third state made observable.

    `state["unknown"]` is written on every call this module could not
    classify, but nothing else in this repository reads it (#490's own
    audit: a counter nobody consumes is functionally invisible even though
    it is correctly kept). This is the read side, for a human -- or a
    future `doctor.py` check -- to actually look. It is deliberately not
    wired into `doctor.py` in this change: that is a decision about what
    the diagnostic surfaces repo-wide, out of scope for one hook.
    """
    return _load_state(_state_path(session_id))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--status":
        if len(argv) != 2:
            print("usage: batch_hint.py --status SESSION_ID", file=sys.stderr)
            return 2
        print(json.dumps(status(argv[1])))
        return 0

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    if payload.get("tool_name") not in (None, "Bash"):
        print(json.dumps({}))
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    session_id = payload.get("session_id")

    output: dict = {}
    if session_id and command:
        path = _state_path(session_id)
        state = _load_state(path)
        classification = classify_command(command)
        state, message = update_state(state, classification)
        _save_state(path, state)
        if message:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": message,
                }
            }

    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
