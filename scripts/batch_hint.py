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
import subprocess
import sys
import time
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

# Derived from `supertool 'ops:roster'` itself, not a hand-copied snapshot
# of it (#537: a second copy of a published classification is exactly what
# CLAUDE.md's governing rule forbids -- the copy is the one that goes
# stale, and it goes stale in only one direction: an op whose class moves
# from read-only to write upstream stays misclassified read-only here
# forever, since nothing re-derives or checks a static copy). Measured at
# well under a tenth of a second (#537), so this module calls it once per
# process and caches the answer to disk for the many separate invocations
# one session makes -- the two options `_op_verdict`'s previous version
# never considered were "every call" (rejected, correctly, as too
# expensive) and "cache the derived answer" (never weighed at all).
_ROSTER_CACHE_NAME = "oss-batch-hint-roster.json"
_ROSTER_CACHE_TTL = 6 * 60 * 60  # seconds; the roster only moves with a supertool release
_ROSTER_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*[*!]?$")

_UNSET = object()  # in-process memo: distinct from "derived, and the answer is None"
_ROSTER_CACHE = _UNSET


def _parse_roster_text(text: str):
    """Parse `supertool 'ops:roster'`'s own printed answer into three name lists.

    Returns ``None`` when the text does not carry a recognisable roster block --
    this repo's own defect class applied to its own parser: a parse failure must
    fail toward "could not derive" (handled by the caller), never toward a
    confidently empty roster that would make every op look genuinely unclassified
    rather than "the derivation itself did not work".

    Locates the op-token block from the BOTTOM of the output, not by anchoring on
    the `>` preset-disclosure line the first version of this parser keyed on
    (self-review finding on #537): that line is `_preset_disclosure`'s own output
    upstream, printed only when a `.supertool.json` fails to list every shipped
    preset -- so on a fully-configured repo (the well-configured population this
    fix exists to serve) `ops:roster`'s real stdout carries no `>` line at all, and
    the first version returned ``None`` for a completely successful, fully
    parseable call. Scanning from the end for the trailing run of lines whose
    every whitespace-separated token matches an op-name shape does not depend on
    any particular line preceding the block -- disclosure line present or not.
    """
    lines = text.splitlines()
    block = []
    for line in reversed(lines):
        if not line.strip():
            if block:
                break  # a blank line above collected block lines ends the block
            continue  # trailing blank lines after the block are not part of it
        candidate_tokens = line.split()
        if not all(_ROSTER_LINE_RE.match(tok) for tok in candidate_tokens):
            break
        block.append(line)
    if not block:
        return None
    block.reverse()
    tokens = " ".join(block).split()
    if not tokens:
        return None
    write, external, read = set(), set(), set()
    for tok in tokens:
        if tok.endswith("*"):
            write.add(tok[:-1])
        elif tok.endswith("!"):
            external.add(tok[:-1])
        else:
            read.add(tok)
    if not (write or external or read):
        return None
    return {"write": sorted(write), "external": sorted(external), "read": sorted(read)}


def _derive_roster(timeout: float = 5.0):
    """Call `supertool 'ops:roster'` once and parse its answer, or ``None``.

    ``None`` covers every way this can fail to settle the question: the
    binary is not on PATH (`FileNotFoundError`), it errors out, it times out,
    or its output does not parse. All of those are the third state, not a
    guess in either direction -- see `_op_verdict`'s handling of it.

    `encoding="utf-8"` is pinned rather than left to `text=True`'s locale
    default (self-review finding on #537): this repo's own CLAUDE.md already
    names the trap -- a console's default codepage on Windows is typically
    cp1252, not UTF-8, and the roster's prose carries non-ASCII punctuation
    (an em dash). Pinning the decode avoids depending on whatever codepage the
    calling process happens to have; `UnicodeDecodeError` is still caught
    alongside the other two failure modes so a genuinely undecodable byte
    degrades to the same third state rather than crashing the hook.
    """
    try:
        proc = subprocess.run(
            ["supertool", "ops:roster"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    if proc.returncode != 0:
        return None
    return _parse_roster_text(proc.stdout)


def _roster_cache_path() -> Path:
    return _state_dir() / _ROSTER_CACHE_NAME


def _load_cached_roster(max_age: float = _ROSTER_CACHE_TTL):
    path = _roster_cache_path()
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return None
    if age > max_age:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in ("write", "external", "read")):
        return None
    return data


def _save_roster_cache(roster_data: dict) -> None:
    try:
        _roster_cache_path().write_text(json.dumps(roster_data), encoding="utf-8")
    except OSError:
        pass  # best-effort; worst case the next call derives it again


def roster():
    """The op classification: memoized in-process, then cached to disk, then derived.

    Returns the ``{"write": [...], "external": [...], "read": [...]}`` dict, or
    ``None`` when it could not be derived at all -- never a partial or a guessed
    one. A failed derivation is never written to the disk cache: caching ``None``
    would turn one transient failure (PATH not yet set up, a network hiccup) into
    a permanent one for the rest of the cache's TTL.
    """
    global _ROSTER_CACHE
    if _ROSTER_CACHE is not _UNSET:
        return _ROSTER_CACHE
    cached = _load_cached_roster()
    if cached is not None:
        _ROSTER_CACHE = cached
        return cached
    derived = _derive_roster()
    if derived is not None:
        _save_roster_cache(derived)
    _ROSTER_CACHE = derived
    return derived


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
    classes = roster()
    if classes is not None:
        if prefix in classes["write"] or prefix in classes["external"]:
            return "not_offender"
        if prefix in classes["read"]:
            return "single_readonly"
    # An op name not in the roster -- either the roster could not be derived
    # at all (third state: degrade to "no confident answer", never guess), or
    # this genuinely is not a recognised op. A trailing payload marker is
    # still a strong, self-contained signal that this consumes stdin and
    # mutates -- that heuristic does not depend on the roster and still
    # applies either way; anything else is genuinely unknown rather than
    # guessed at.
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
