#!/usr/bin/env python3
"""One agent's own token spend, measured from its transcript -- #1499.

`loop_cost_report.py` sums a whole projects directory after the fact. This
module answers the narrower question a lane asks while it is still running:
*what has this agent cost so far?* -- so a developer report or a handback
carries a measured `cost` block, not a recalled one.

## How an agent finds its own transcript

The harness exposes no context counter and no agent id to the agent itself.
What the agent does hold is a string only its own tool calls carried. The
search reads every `tool_use` block's input in every candidate transcript and
keeps the files whose input carries `--match` verbatim -- except `Agent` and
`Task` blocks, whose input is a brief describing *another* agent's work and
would otherwise make every lane's branch name ambiguous with its spawner.
Exactly one hit is a measurement; zero or several are not, and each says so.

A branch name or a worktree path is NOT unique: the sub-manager's own
`lane_setup.py` call names both before the lane exists. **The report path
is**: the lane chose it and wrote it, and nobody else names it until the
handback. So the intended call is `--into <report.json>` -- the report path
is the match string, and the block is written into the report's `cost` key
in the same step, so the lane never retypes a number.

Candidates are the session's own file (`<session>.jsonl`) and its spawns
(`<session>/subagents/agent-*.jsonl`) under every project directory, since a
spawn's transcript lives under the session that spawned it, not under the
worktree it ran in. `--session` defaults to `$CLAUDE_CODE_SESSION_ID`; with
no session known, every project directory's sessions are searched.

## What is measured

Only `type == "assistant"` records with a `message.usage`. `context` on one
call is `cache_read_input_tokens + cache_creation_input_tokens +
input_tokens`, the same sum `loop_cost_report.py` uses. The transcript is
appended after each call completes, so the call that runs this script is not
yet in it: `max_context` is exact for every call before this one.

## States

* `measured` -- exactly one transcript carries the string.
* `ambiguous` -- more than one does; `candidates` lists them. Pick a string
  only this agent's own calls could carry and run again.
* `no-match` -- every candidate was read and none carries it; `searched`
  says how many.
* `could-not-read` -- the projects directory is absent, not a directory, or
  could not be listed. Nothing was searched.

A malformed line is counted in `malformed`, never silently skipped.

Python 3.9 compatible.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_MEASURED = "measured"
STATE_AMBIGUOUS = "ambiguous"
STATE_NO_MATCH = "no-match"
STATE_COULD_NOT_READ = "could-not-read"

#: Tool-use blocks whose input describes another agent's work, never this one's.
SPAWN_TOOLS = ("Agent", "Task")

#: Decision 1 of #1499: 200k is the goal, 400k and past it is a defect.
DEFAULT_THRESHOLD = 400_000

NOTE = (
    "measured from the transcript, which is appended after each call "
    "completes; the call that ran agent_cost.py is not yet counted"
)


def default_projects_dir():
    return Path.home() / ".claude" / "projects"


def _usage_int(usage, key):
    value = usage.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _candidates(projects_dir, session):
    """``(paths, error)``: every transcript to search, or why none could be."""
    try:
        entries = sorted(os.listdir(str(projects_dir)))
    except FileNotFoundError:
        return None, "projects directory {} does not exist".format(projects_dir)
    except NotADirectoryError:
        return None, "{} is not a directory".format(projects_dir)
    except OSError as exc:
        return None, "projects directory {} could not be listed ({})".format(
            projects_dir, exc
        )
    found = []
    for entry in entries:
        project = projects_dir / entry
        try:
            names = os.listdir(str(project))
        except OSError:
            continue
        if session is not None:
            sessions = (
                [session] if session in names or session + ".jsonl" in names else []
            )
        else:
            sessions = sorted(name[:-6] for name in names if name.endswith(".jsonl"))
        for sid in sessions:
            own = project / (sid + ".jsonl")
            if own.is_file():
                found.append(own)
            sub = project / sid / "subagents"
            try:
                spawn_names = sorted(os.listdir(str(sub)))
            except OSError:
                continue
            for name in spawn_names:
                if name.endswith(".jsonl"):
                    found.append(sub / name)
    return found, None


def read_transcript(path, needle):
    """``(summary, matched)`` for one transcript; ``summary`` is ``None`` when
    the file could not be opened."""
    summary = {
        "turns": 0,
        "tool_calls": 0,
        "bash_calls": 0,
        "max_context": 0,
        "last_context": 0,
        "context_sent": 0,
        "output_tokens": 0,
        "malformed": 0,
    }
    matched = False
    try:
        handle = open(str(path), "r", encoding="utf-8", errors="replace")
    except OSError:
        return None, False
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                summary["malformed"] += 1
                continue
            if not isinstance(record, dict):
                summary["malformed"] += 1
                continue
            if record.get("type") != "assistant":
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    summary["tool_calls"] += 1
                    if block.get("name") == "Bash":
                        summary["bash_calls"] += 1
                    if block.get("name") in SPAWN_TOOLS:
                        continue
                    if needle in json.dumps(block.get("input"), ensure_ascii=False):
                        matched = True
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            context = (
                _usage_int(usage, "cache_read_input_tokens")
                + _usage_int(usage, "cache_creation_input_tokens")
                + _usage_int(usage, "input_tokens")
            )
            summary["turns"] += 1
            summary["context_sent"] += context
            summary["last_context"] = context
            summary["output_tokens"] += _usage_int(usage, "output_tokens")
            if context > summary["max_context"]:
                summary["max_context"] = context
    return summary, matched


def _agent_type(path):
    meta = path.with_name(path.name[: -len(".jsonl")] + ".meta.json")
    try:
        with open(str(meta), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return "unknown" if "subagents" in path.parts else "main-session"
    kind = data.get("agentType") if isinstance(data, dict) else None
    return kind if isinstance(kind, str) and kind else "unknown"


def _search(paths, needle):
    hits = []
    searched = 0
    for path in paths:
        summary, matched = read_transcript(path, needle)
        if summary is None:
            continue
        searched += 1
        if matched:
            hits.append((path, summary))
    return hits, searched


def measure(
    projects_dir,
    needle,
    session=None,
    threshold=DEFAULT_THRESHOLD,
    basename_fallback=False,
):
    """The measurement as one mapping; ``state`` is the first key to read.

    ``basename_fallback`` is for a needle that is a file path (`--into`): a
    lane that typed `$REPORT` or a relative path never put the full path into
    any tool input, and the basename is the next most specific string it did
    type. Off for a free-form `--match`, where `basename` of an arbitrary
    string is not a narrower question but a wider one.
    """
    projects_dir = Path(projects_dir)
    paths, error = _candidates(projects_dir, session)
    if error is not None:
        return {"state": STATE_COULD_NOT_READ, "why": error, "match": needle}
    hits, searched = _search(paths, needle)
    matched_on = "match"
    basename = os.path.basename(needle.rstrip("/\\"))
    if not hits and basename_fallback and basename and basename != needle:
        hits, searched = _search(paths, basename)
        matched_on = "basename"
    if not hits:
        return {"state": STATE_NO_MATCH, "match": needle, "searched": searched}
    if len(hits) > 1:
        return {
            "state": STATE_AMBIGUOUS,
            "match": needle,
            "searched": searched,
            "candidates": [str(path) for path, _ in hits],
        }
    path, summary = hits[0]
    result = {
        "state": STATE_MEASURED,
        "match": needle,
        "matched_on": matched_on,
        "transcript": str(path),
        "agent_type": _agent_type(path),
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "threshold": threshold,
        "over_threshold": summary["max_context"] >= threshold,
        "note": NOTE,
    }
    result.update(summary)
    return result


def render(result):
    state = result["state"]
    if state == STATE_MEASURED:
        return "\n".join(
            [
                "agent-cost: {}  {}  max_context={:,}  last={:,}  turns={}  "
                "bash={}  output={:,}{}{}".format(
                    state,
                    result["agent_type"],
                    result["max_context"],
                    result["last_context"],
                    result["turns"],
                    result["bash_calls"],
                    result["output_tokens"],
                    "  OVER {:,}".format(result["threshold"])
                    if result["over_threshold"]
                    else "",
                    "  (matched on basename)"
                    if result["matched_on"] == "basename"
                    else "",
                ),
                "transcript: {}".format(result["transcript"]),
            ]
            + (
                ["malformed lines: {}".format(result["malformed"])]
                if result["malformed"]
                else []
            )
        )
    if state == STATE_AMBIGUOUS:
        return "\n".join(
            [
                "agent-cost: {}  {} transcripts carry {!r}; name a string only "
                "this agent's own calls used".format(
                    state, len(result["candidates"]), result["match"]
                )
            ]
            + ["  " + path for path in result["candidates"]]
        )
    if state == STATE_NO_MATCH:
        return "agent-cost: {}  none of {} transcripts carries {!r}".format(
            state, result["searched"], result["match"]
        )
    return "agent-cost: {}  {}".format(state, result["why"])


def write_into(report_path, result):
    """Set ``cost`` in the JSON report at ``report_path``; returns an error
    string, or ``None`` when written."""
    try:
        with open(str(report_path), "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except FileNotFoundError:
        return "report {} does not exist".format(report_path)
    except (OSError, ValueError) as exc:
        return "report {} could not be read as JSON ({})".format(report_path, exc)
    if not isinstance(report, dict):
        return "report {} is not a JSON object".format(report_path)
    report["cost"] = result
    try:
        with open(str(report_path), "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        return "report {} could not be written ({})".format(report_path, exc)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--match",
        help="a string only this agent's own tool calls carried "
        "(default: the --into path)",
    )
    parser.add_argument(
        "--into",
        help="a JSON report to write the block into under `cost`; also the "
        "default --match, since the lane that wrote it is the only one naming it",
    )
    parser.add_argument(
        "--projects-dir",
        default=str(default_projects_dir()),
        help="Claude Code projects directory (default: ~/.claude/projects)",
    )
    parser.add_argument(
        "--session",
        default=os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
        help="session id to search under (default: $CLAUDE_CODE_SESSION_ID; "
        "unset searches every session)",
    )
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--json", action="store_true", help="print the block only")
    args = parser.parse_args(argv)
    needle = args.match or args.into
    if not needle:
        parser.error("one of --match or --into is required")
    result = measure(
        args.projects_dir,
        needle,
        args.session,
        args.threshold,
        basename_fallback=args.match is None,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result))
    if args.into:
        error = write_into(args.into, result)
        if error is not None:
            print("agent-cost: not written -- {}".format(error), file=sys.stderr)
            return 2
        print("written into {} under cost".format(args.into), file=sys.stderr)
    return {
        STATE_MEASURED: 0,
        STATE_AMBIGUOUS: 1,
        STATE_NO_MATCH: 1,
        STATE_COULD_NOT_READ: 2,
    }[result["state"]]


if __name__ == "__main__":
    sys.exit(main())
