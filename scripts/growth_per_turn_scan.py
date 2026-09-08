#!/usr/bin/env python3
"""Growth-per-turn scan, developer agents only, before/after PR #454 -- #455.

#314 measured *what* an agent's per-turn context growth is: its own body
found tool results accounting for roughly half of it, with the remainder
being the agent's own emitted text between tool calls -- a real, cited
measurement, not this module's own claim, and **not** a claim about how much
of that remainder is narration specifically versus tool-call payload; #454's
own "Not claimed" clause is explicit that it does not attempt that split
(self-review finding, #455). #454 acted on the narration half anyway:
`agents/developer.md` gained an instruction that prose belongs in the
report, not between tool calls. Neither issue ran the measurement that would
say whether that instruction actually changed anything -- #454's own lane
correctly declined it, because at the time it merged no post-fix developer
transcripts existed yet to compare against. This module is that comparison,
run once enough of them do.

## What "growth per turn" means here

Per transcript, this reads every `assistant` record's `message.usage` and
sums `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`
-- the total context the model had in front of it on that turn, not merely
what changed since the last one (see `_context_size`). `growth_per_turn` is
then `(final_context - turn1_context) / (turns - 1)`: the average per-turn
increase across the whole run, the same quantity #314's own body measured
directly rather than a proxy. A single-assistant-turn transcript has no delta
to compute and contributes no reading (`None`), the same way `transcript_
refusals.py` leaves an empty aggregate rather than fabricating a zero.

**Why growth per turn and never total tokens**: #314 says so explicitly --
total moves with how hard the issue was, and a scan that cannot separate
those two would credit or blame the instruction for whatever the population
of issues dispatched after it happened to cost. Growth per turn is scaled by
the run's own length, so a harder issue that ran longer is not, by that fact
alone, read as more or less improved.

**Attribution to before/after #454**: a transcript's own *last* record
timestamp (ISO8601, UTC, `Z`-suffixed) is compared against `DEFAULT_SPLIT_AT`
-- #454's own `merged_at`, `2026-08-22T11:05:29Z`, read from the forge
(`gh-pr:454:status`) rather than guessed. The *last* timestamp, not the
first, because the instruction governs what a lane writes as it runs, and a
lane spanning the merge moment would have started under the old brief and
finished under the new one -- attributing by its own conclusion is the
closer reading of "was this lane run under the new instruction". A lane that
straddles the boundary is a real edge case this reading does not resolve
perfectly, and is named as a judgement call rather than hidden as a fact.
Comparison is via `_timestamp_key`, not a bare string compare: two
Z-suffixed ISO8601 timestamps of the *same* fractional-second precision do
sort lexicographically, but `DEFAULT_SPLIT_AT` carries none while a real
transcript timestamp carries milliseconds, and a naive compare gets that
pair backwards (self-review finding, #455 -- see `_timestamp_key`'s own
docstring for the mechanism). No datetime parsing, no timezone arithmetic;
just a precision-safe key.

**Population**: `--agent oss:developer` by default, matching the literal
`attributionAgent` value `transcript_refusals.py` already established for
this repository's developer lanes (see that module's own `--agent` help
text). Passing `--agent ''`/`None` widens the population to every subagent;
kept available for comparison, never the default.

## The three states -- #455's own requirement, never two

- `measured` -- both sides carry at least one transcript with a computable
  `growth_per_turn` (turns >= 2). Medians and the delta are reported.
- `no-post-fix-transcripts` -- the after-split population has zero
  transcripts with a computable growth reading. **This must never render as
  "no improvement"**: it means the input to the comparison does not exist
  yet, not that a comparison was made and found nothing. The before side is
  still reported in full alongside it -- but "in full" is not a promise that
  it has a growth reading either: `before.growth_samples` can itself be 0 in
  the degenerate case where every matched pre-split transcript was a single
  turn (self-review finding, #455). Read `growth_samples`, on either side,
  rather than assuming a non-empty `transcript_count` means one.
- `could-not-read` -- nothing could be measured at all: no transcript files
  found under the given root(s), every file that was found failed to parse,
  or the agent filter matched zero transcripts. Distinct from
  `no-post-fix-transcripts`, which is specifically about the after side
  being empty while the before side and the population as a whole are fine.

## Not claimed

Same boundary #314 itself states, restated here because a bare median number
invites exactly the reading #314 warns against: a lower `growth_per_turn`
after #454 is not, on its own, evidence the instruction produced equally
good work. It is evidence about token growth only. Whether terse narration
after the fix still does the job #314 says nothing measures here either.

## Reused rather than reimplemented

`transcript_refusals.discover_transcripts` and `.default_transcripts_root`
are reused as-is: `os.walk`-based discovery that reports an unreadable
directory rather than silently treating it as empty, and the same
derive-don't-hardcode root guess (`Path.home()` plus an encoded cwd). This
module adds only what that one does not compute: per-turn context growth and
the before/after split.

Python 3.9 compatible -- this project's CI runs 3.9 through 3.12.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript_refusals as tr  # noqa: E402

EXIT_MEASURED = 0
EXIT_USAGE = 2
EXIT_NO_POST_FIX = 3
EXIT_COULD_NOT_READ = 4

STATE_MEASURED = "measured"
STATE_NO_POST_FIX = "no-post-fix-transcripts"
STATE_COULD_NOT_READ = "could-not-read"

#: transcript_refusals.py's own --agent help text names this as the
#: attributionAgent value for a developer lane; #455 asks for developer
#: agents only.
DEFAULT_AGENT_FILTER = "oss:developer"

#: PR #454 (issue #314) merged at this UTC timestamp -- the commit that
#: shipped the "prose belongs in the report, not between tool calls"
#: instruction this scan measures the effect of. Read from the forge
#: (`gh-pr:454:status` -> merged_at) when this scan was built, not guessed;
#: see the module docstring for why the *last* record timestamp of a
#: transcript, not the first, is what gets compared against it.
DEFAULT_SPLIT_AT = "2026-08-22T11:05:29Z"

#: The three usage fields that together are the context size a turn had in
#: front of it -- reused tokens (cache_read), newly cached tokens
#: (cache_creation) and uncached new tokens (input). See _context_size.
_CONTEXT_USAGE_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _context_size(usage):
    """Total context tokens one assistant turn had in front of it: cache_read
    (reused from a prior turn), cache_creation (newly cached this turn) and
    input (uncached new) all count -- together they are what the model
    actually read that turn, not merely what changed since the last one.
    Missing or non-numeric fields count as 0 rather than raising."""
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in _CONTEXT_USAGE_KEYS:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total += value
    return total


def _usage_is_unusable(usage):
    """True when a *present* usage dict carries none of the three context
    fields as a number. `_context_size` folds this case into a plain `0`,
    which renders identically to a turn whose context genuinely was zero --
    so this is tracked separately (self-review finding, #455) rather than
    left silent."""
    return not any(
        isinstance(usage.get(key), (int, float)) for key in _CONTEXT_USAGE_KEYS
    )


def _timestamp_key(ts):
    """A comparison key for a Z-suffixed ISO8601 UTC timestamp that stays
    correct across differing fractional-second precision. A bare string
    compare is not safe once precision differs: `'.'` (0x2E) sorts below
    `'Z'` (0x5A) in ASCII, so `"...29.500Z"` (500ms *after* the second)
    compares *less than* `"...29Z"` (the bare second, no fraction) --
    `DEFAULT_SPLIT_AT` has no fractional component while every real
    transcript timestamp does (self-review finding, #455). Splits the
    whole-second prefix (fixed width, so plain string comparison is safe
    there) from the fractional part, and right-pads a missing or shorter
    fraction with zeros so every key compares at the same precision."""
    if ts.endswith("Z"):
        ts = ts[:-1]
    whole, _, frac = ts.partition(".")
    return whole, frac.ljust(9, "0")


def analyze_growth(path):
    """One transcript's growth-per-turn reading. Never raises -- an
    unreadable or unparsable file comes back as `{"ok": False, ...}`,
    matching transcript_refusals.analyze_transcript's own split: a file this
    could not read must never render like one that was read and simply had
    nothing to say (CLAUDE.md's own defect class, #455)."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "path": str(path),
            "reason": "{0}: {1}".format(type(exc).__name__, exc),
        }

    agent = None
    last_timestamp = None
    turns = 0
    turns_with_unusable_usage = 0
    first_context = None
    last_context = None
    parsed_records = 0
    non_blank_lines = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        non_blank_lines += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        parsed_records += 1

        if agent is None:
            candidate = record.get("attributionAgent")
            if isinstance(candidate, str) and candidate:
                agent = candidate

        ts = record.get("timestamp")
        if isinstance(ts, str) and ts:
            last_timestamp = ts

        if record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        turns += 1
        if _usage_is_unusable(usage):
            turns_with_unusable_usage += 1
        context = _context_size(usage)
        if first_context is None:
            first_context = context
        last_context = context

    if non_blank_lines and parsed_records == 0:
        # Every line failed to parse -- a file this could not read, never a
        # transcript that was read and simply had zero turns. Same split as
        # transcript_refusals.analyze_transcript's own unreadable-file case.
        return {
            "ok": False,
            "path": str(path),
            "reason": "no valid JSON record in {0} non-blank line(s)".format(
                non_blank_lines
            ),
        }

    growth_per_turn = None
    if turns >= 2 and first_context is not None and last_context is not None:
        growth_per_turn = (last_context - first_context) / (turns - 1)

    return {
        "ok": True,
        "path": str(path),
        "agent": agent or "unknown",
        "last_timestamp": last_timestamp,
        "turns": turns,
        "turns_with_unusable_usage": turns_with_unusable_usage,
        "turn1_context": first_context,
        "final_context": last_context,
        "growth_per_turn": growth_per_turn,
    }


def _median(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return statistics.median(values)


def _summarize_side(analyses):
    """One side (before/after) of the split. `transcript_count` is every
    matched transcript on this side; `growth_samples` is the subset that
    actually contributed a `growth_per_turn` reading (turns >= 2) -- the two
    differ whenever a side includes a single-turn lane, and the gap is a
    finding worth keeping visible rather than silently absorbed into a
    smaller population."""
    growth = [
        a["growth_per_turn"] for a in analyses if a["growth_per_turn"] is not None
    ]
    turns = [a["turns"] for a in analyses]
    timestamps = [a["last_timestamp"] for a in analyses if a["last_timestamp"]]
    return {
        "transcript_count": len(analyses),
        "growth_samples": len(growth),
        "median_growth_per_turn": _median(growth),
        "median_turns": _median(turns),
        "turns_with_unusable_usage": sum(
            a.get("turns_with_unusable_usage", 0) for a in analyses
        ),
        "window": {
            "first_timestamp": min(timestamps) if timestamps else None,
            "last_timestamp": max(timestamps) if timestamps else None,
        },
    }


def run(roots, agent_filter=DEFAULT_AGENT_FILTER, split_at=DEFAULT_SPLIT_AT):
    """The whole scan over `roots`. Returns the report dict; never raises."""
    files, unreadable_dirs = tr.discover_transcripts(roots)

    if not files:
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "no transcript files found under the given root(s)",
            "roots_searched": [str(r) for r in roots],
            "unreadable_dirs": unreadable_dirs,
            "agent_filter": agent_filter,
            "split_at": split_at,
        }

    parsed = []
    unreadable_files = []
    for path in files:
        result = analyze_growth(path)
        if result["ok"]:
            parsed.append(result)
        else:
            unreadable_files.append(
                {"path": result["path"], "reason": result["reason"]}
            )

    if not parsed:
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "no transcript file could be read ({0} found, all "
            "unreadable)".format(len(files)),
            "roots_searched": [str(r) for r in roots],
            "transcripts_found": len(files),
            "transcripts_parsed": 0,
            "unreadable_files": unreadable_files,
            "unreadable_dirs": unreadable_dirs,
            "agent_filter": agent_filter,
            "split_at": split_at,
        }

    matched = [a for a in parsed if agent_filter is None or a["agent"] == agent_filter]

    if not matched:
        return {
            "state": STATE_COULD_NOT_READ,
            "reason": "no transcripts matched agent_filter={0!r}".format(agent_filter),
            "roots_searched": [str(r) for r in roots],
            "transcripts_found": len(files),
            "transcripts_parsed": len(parsed),
            "unreadable_files": unreadable_files,
            "unreadable_dirs": unreadable_dirs,
            "agent_filter": agent_filter,
            "split_at": split_at,
        }

    split_key = _timestamp_key(split_at)
    before = [
        a
        for a in matched
        if a["last_timestamp"] is not None
        and _timestamp_key(a["last_timestamp"]) < split_key
    ]
    after = [
        a
        for a in matched
        if a["last_timestamp"] is not None
        and _timestamp_key(a["last_timestamp"]) >= split_key
    ]
    no_timestamp = [a for a in matched if a["last_timestamp"] is None]

    before_summary = _summarize_side(before)
    after_summary = _summarize_side(after)

    state = (
        STATE_NO_POST_FIX if after_summary["growth_samples"] == 0 else STATE_MEASURED
    )

    delta = None
    if (
        state == STATE_MEASURED
        and before_summary["median_growth_per_turn"] is not None
        and after_summary["median_growth_per_turn"] is not None
    ):
        delta = (
            after_summary["median_growth_per_turn"]
            - before_summary["median_growth_per_turn"]
        )

    return {
        "state": state,
        "agent_filter": agent_filter,
        "split_at": split_at,
        "roots_searched": [str(r) for r in roots],
        "transcripts_found": len(files),
        "transcripts_parsed": len(parsed),
        "transcripts_matched_agent_filter": len(matched),
        "transcripts_no_timestamp": len(no_timestamp),
        "unreadable_files": unreadable_files,
        "unreadable_dirs": unreadable_dirs,
        "before": before_summary,
        "after": after_summary,
        "median_growth_per_turn_delta": delta,
    }


def _build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else ""
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="Directory to search recursively for *.jsonl transcripts. "
        "Repeatable. Default: transcript_refusals.default_transcripts_root().",
    )
    parser.add_argument(
        "--agent",
        default=DEFAULT_AGENT_FILTER,
        help="Filter to one attributionAgent value. Default: {0}. Pass an "
        "empty string to include every agent.".format(DEFAULT_AGENT_FILTER),
    )
    parser.add_argument(
        "--split-at",
        default=DEFAULT_SPLIT_AT,
        help="ISO8601 UTC timestamp (Z-suffixed) to split before/after on. "
        "Default: PR #454's own merged_at, {0}.".format(DEFAULT_SPLIT_AT),
    )
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indent (0 for compact)."
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    roots = (
        [Path(r) for r in args.root] if args.root else [tr.default_transcripts_root()]
    )
    agent_filter = args.agent if args.agent else None
    report = run(roots, agent_filter=agent_filter, split_at=args.split_at)
    indent = args.indent if args.indent > 0 else None
    print(json.dumps(report, indent=indent, sort_keys=True))
    if report["state"] == STATE_MEASURED:
        return EXIT_MEASURED
    if report["state"] == STATE_NO_POST_FIX:
        return EXIT_NO_POST_FIX
    return EXIT_COULD_NOT_READ


if __name__ == "__main__":
    sys.exit(main())
