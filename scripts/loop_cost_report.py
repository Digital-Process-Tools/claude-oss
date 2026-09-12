#!/usr/bin/env python3
"""Token spend re-derived from Claude Code transcripts -- #1499.

One overnight `/oss:run` consumed ~70% of the subscription quota, and the
figures that showed it -- per repository, per agent kind, per context band --
were summed by hand from `~/.claude/projects/<dir>/**/*.jsonl`. This module is
that measurement as a script, so the next run is compared against a number
rather than a memory, and so an agent whose context passed the defect threshold
is a listed finding rather than a table somebody once pasted into an issue.

## What is read

Every `*.jsonl` under a project directory: the session file itself
(`<session>.jsonl`) and its spawned agents (`<session>/subagents/agent-*.jsonl`).
Each line is one JSON record. Only records with `type == "assistant"` and a
`message.usage` are summed; **context at call time** is
`cache_read_input_tokens + cache_creation_input_tokens + input_tokens`, which
is what the API was sent on that call and what the quota is charged for.
`output_tokens` is kept separately.

A transcript's kind is read off its first `type == "user"` record, in this
order (`classify`): `spawn token` -> `sub-manager`, `run one release` ->
`releaser`, `read and follow` -> `scheduler-step`, a file that is not under
`subagents/` -> `main-session`, `issue`/`lane` in the first 300 characters ->
`developer`, `audit`/`review` in the first 200 characters -> `audit-review`,
else `other`. These are the phrases the loop's own spawn prompts carry today
(`commands/tick.md`, `commands/run.md`, `skills/manager/phases/dispatch.md`);
a spawn prompt that stops carrying its phrase lands in `other`, which is
visible in the table rather than silently folded into a neighbour.

## Three states, never two

* `measured` -- the directory was read and at least one assistant record
  falls after `--since`.
* `nothing-in-window` -- the directory was read, transcripts may well exist,
  and no record after `--since` was found. Not zeros under `measured`: a
  window nobody ran anything in and a window the reader could not see must
  render differently.
* `could-not-read` -- the projects directory is absent, is not a directory,
  or could not be listed. Nothing was measured.

A malformed line -- one that is not JSON, or not an object -- is counted and
reported with its file and line number. It is never skipped in silence: a
transcript that was half-read and one that was read whole must not sum to the
same confident total.

Python 3.9 compatible.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_MEASURED = "measured"
STATE_NOTHING = "nothing-in-window"
STATE_COULD_NOT_READ = "could-not-read"

KINDS = (
    "main-session",
    "sub-manager",
    "releaser",
    "scheduler-step",
    "developer",
    "audit-review",
    "other",
)

#: Context bands, in tokens sent on one call. Upper bounds are exclusive; the
#: last band is open.
BANDS = (
    ("<100k", 0, 100_000),
    ("100-200k", 100_000, 200_000),
    ("200-300k", 200_000, 300_000),
    ("300-400k", 300_000, 400_000),
    (">400k", 400_000, None),
)

DEFAULT_DEFECT_AT = 400_000


def default_projects_dir():
    return Path.home() / ".claude" / "projects"


def parse_since(text):
    """An ISO-8601 timestamp as an aware UTC datetime, or ``None`` if unparseable.

    `Z` is accepted as well as an explicit offset; a naive value is read as UTC,
    because the transcripts' own `timestamp` fields are all `Z`-suffixed.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    candidate = text.strip()
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_time(record):
    value = record.get("timestamp")
    return parse_since(value) if isinstance(value, str) else None


def _text_of(content):
    """The prose of a `message.content`, which is a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def classify(first_prompt, subagent):
    """The agent kind a transcript's first user prompt names -- see the module
    docstring for the order, which is the order the phrases are checked in."""
    text = first_prompt or ""
    lowered = text.lower()
    if "spawn token" in lowered:
        return "sub-manager"
    if "run one release" in lowered:
        return "releaser"
    if "read and follow" in lowered:
        return "scheduler-step"
    if not subagent:
        return "main-session"
    head_300 = lowered[:300]
    if "issue" in head_300 or "lane" in head_300:
        return "developer"
    head_200 = lowered[:200]
    if "audit" in head_200 or "review" in head_200:
        return "audit-review"
    return "other"


def band_of(context):
    for name, low, high in BANDS:
        if context >= low and (high is None or context < high):
            return name
    return BANDS[-1][0]


def _usage_int(usage, key):
    value = usage.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def read_transcript(path, since):
    """One transcript's summary: ``(summary, malformed)``.

    ``summary`` carries the sums over assistant records at or after ``since``,
    the max context, the record count and the first user prompt; ``malformed``
    is a list of ``(line_number, reason)`` for every line that was not a JSON
    object. A file that could not be opened returns ``(None, [(0, why)])`` --
    reported beside the malformed lines rather than dropped.
    """
    summary = {
        "records": 0,
        "context_sent": 0,
        "max_context": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "input": 0,
        "output": 0,
        "bands": {name: 0 for name, _, _ in BANDS},
        "first_prompt": None,
    }
    malformed = []
    try:
        handle = open(str(path), "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, [(0, "could not open: {}".format(exc))]
    with handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                malformed.append((number, "not JSON: {}".format(exc)))
                continue
            if not isinstance(record, dict):
                malformed.append((number, "not a JSON object"))
                continue
            kind = record.get("type")
            message = record.get("message")
            if kind == "user" and summary["first_prompt"] is None:
                text = (
                    _text_of(message.get("content"))
                    if isinstance(message, dict)
                    else ""
                )
                if text.strip():
                    summary["first_prompt"] = text
                continue
            if kind != "assistant" or not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            when = _record_time(record)
            if when is None or when < since:
                continue
            cache_read = _usage_int(usage, "cache_read_input_tokens")
            cache_creation = _usage_int(usage, "cache_creation_input_tokens")
            inp = _usage_int(usage, "input_tokens")
            out = _usage_int(usage, "output_tokens")
            context = cache_read + cache_creation + inp
            summary["records"] += 1
            summary["context_sent"] += context
            summary["cache_read"] += cache_read
            summary["cache_creation"] += cache_creation
            summary["input"] += inp
            summary["output"] += out
            summary["bands"][band_of(context)] += context
            if context > summary["max_context"]:
                summary["max_context"] = context
    return summary, malformed


def _transcripts(project_dir):
    """Every ``*.jsonl`` under one project directory, as ``(path, subagent)``.

    `os.walk` rather than `Path.rglob`: pathlib's globs swallow the
    `PermissionError` they meet while walking and yield nothing, which renders
    an unreadable tree as an empty one (#124/#383).
    """
    found = []
    for root, _dirs, files in os.walk(str(project_dir)):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = Path(root) / name
            subagent = "subagents" in path.relative_to(project_dir).parts
            found.append((path, subagent))
    return sorted(found)


def _empty_kind():
    return {
        "agents": 0,
        "records": 0,
        "context_sent": 0,
        "max_context": 0,
        "share": 0.0,
    }


def measure(projects_dir, since, repo_dir=None, defect_at=DEFAULT_DEFECT_AT):
    """The whole report as one mapping; ``state`` is the first key to read."""
    projects_dir = Path(projects_dir)
    since_dt = parse_since(since) if isinstance(since, str) else since
    if since_dt is None:
        return {
            "state": STATE_COULD_NOT_READ,
            "why": "--since is not an ISO-8601 timestamp: {!r}".format(since),
        }
    try:
        entries = sorted(os.listdir(str(projects_dir)))
    except FileNotFoundError:
        return {
            "state": STATE_COULD_NOT_READ,
            "why": "projects directory {} does not exist".format(projects_dir),
        }
    except NotADirectoryError:
        return {
            "state": STATE_COULD_NOT_READ,
            "why": "{} is not a directory".format(projects_dir),
        }
    except OSError as exc:
        return {
            "state": STATE_COULD_NOT_READ,
            "why": "projects directory {} could not be listed ({})".format(
                projects_dir, exc
            ),
        }

    projects = {}
    defects = []
    malformed = []
    unreadable = []
    total_records = 0
    for entry in entries:
        if repo_dir is not None and entry != repo_dir:
            continue
        project_dir = projects_dir / entry
        if not project_dir.is_dir():
            continue
        kinds = {}
        bands = {name: 0 for name, _, _ in BANDS}
        project_total = 0
        project_records = 0
        for path, subagent in _transcripts(project_dir):
            summary, bad = read_transcript(path, since_dt)
            rel = str(path.relative_to(projects_dir))
            for number, reason in bad:
                if number == 0:
                    unreadable.append({"transcript": rel, "why": reason})
                else:
                    malformed.append({"transcript": rel, "line": number, "why": reason})
            if summary is None or summary["records"] == 0:
                continue
            kind = classify(summary["first_prompt"], subagent)
            bucket = kinds.setdefault(kind, _empty_kind())
            bucket["agents"] += 1
            bucket["records"] += summary["records"]
            bucket["context_sent"] += summary["context_sent"]
            bucket["max_context"] = max(bucket["max_context"], summary["max_context"])
            for name in bands:
                bands[name] += summary["bands"][name]
            project_total += summary["context_sent"]
            project_records += summary["records"]
            if summary["max_context"] >= defect_at:
                first = (summary["first_prompt"] or "").strip().splitlines()
                defects.append(
                    {
                        "project": entry,
                        "transcript": rel,
                        "kind": kind,
                        "records": summary["records"],
                        "max_context": summary["max_context"],
                        "context_sent": summary["context_sent"],
                        "first_prompt": first[0] if first else "",
                    }
                )
        if project_records == 0:
            continue
        for bucket in kinds.values():
            bucket["share"] = (
                bucket["context_sent"] / project_total if project_total else 0.0
            )
        projects[entry] = {
            "records": project_records,
            "context_sent": project_total,
            "kinds": kinds,
            "bands": bands,
        }
        total_records += project_records

    defects.sort(key=lambda d: d["max_context"], reverse=True)
    return {
        "state": STATE_MEASURED if total_records else STATE_NOTHING,
        "projects_dir": str(projects_dir),
        "since": since_dt.isoformat(),
        "repo_dir": repo_dir,
        "defect_at": defect_at,
        "records": total_records,
        "projects": projects,
        "defects": defects,
        "malformed_lines": len(malformed),
        "malformed": malformed,
        "unreadable": unreadable,
    }


def _fmt(n):
    return "{:,}".format(n)


def render(result):
    lines = ["STATE: {}".format(result["state"])]
    if result["state"] == STATE_COULD_NOT_READ:
        lines.append("why: {}".format(result["why"]))
        return "\n".join(lines)
    lines.append(
        "projects dir: {}  since: {}  defect-at: {}".format(
            result["projects_dir"], result["since"], _fmt(result["defect_at"])
        )
    )
    lines.append(
        "records: {}  malformed lines: {}  unreadable transcripts: {}".format(
            _fmt(result["records"]),
            result["malformed_lines"],
            len(result["unreadable"]),
        )
    )
    for project, data in result["projects"].items():
        lines.append("")
        lines.append(
            "== {}  records {}  context sent {}".format(
                project, _fmt(data["records"]), _fmt(data["context_sent"])
            )
        )
        lines.append(
            "  {:<15} {:>7} {:>8} {:>18} {:>12} {:>6}".format(
                "kind", "agents", "records", "context sent", "max ctx", "share"
            )
        )
        for kind in KINDS:
            bucket = data["kinds"].get(kind)
            if bucket is None:
                continue
            lines.append(
                "  {:<15} {:>7} {:>8} {:>18} {:>12} {:>5.0%}".format(
                    kind,
                    bucket["agents"],
                    _fmt(bucket["records"]),
                    _fmt(bucket["context_sent"]),
                    _fmt(bucket["max_context"]),
                    bucket["share"],
                )
            )
        lines.append("  context sent by band at call time:")
        for name, _, _ in BANDS:
            sent = data["bands"][name]
            share = sent / data["context_sent"] if data["context_sent"] else 0.0
            lines.append("    {:<9} {:>18} {:>5.0%}".format(name, _fmt(sent), share))
    lines.append("")
    if result["defects"]:
        lines.append(
            "transcripts whose max context passed {} ({}):".format(
                _fmt(result["defect_at"]), len(result["defects"])
            )
        )
        for defect in result["defects"]:
            lines.append(
                "  {:>12}  {:<15} {:>5} records  {}  {}".format(
                    _fmt(defect["max_context"]),
                    defect["kind"],
                    defect["records"],
                    defect["transcript"],
                    defect["first_prompt"][:100],
                )
            )
    else:
        lines.append(
            "no transcript passed {} max context.".format(_fmt(result["defect_at"]))
        )
    for item in result["malformed"]:
        lines.append(
            "malformed: {} line {}: {}".format(
                item["transcript"], item["line"], item["why"]
            )
        )
    for item in result["unreadable"]:
        lines.append("unreadable: {}: {}".format(item["transcript"], item["why"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Token spend per project, agent kind and context band, from "
        "Claude Code transcripts (#1499)."
    )
    parser.add_argument(
        "--projects-dir",
        default=str(default_projects_dir()),
        help="Claude Code projects directory (default: ~/.claude/projects)",
    )
    parser.add_argument(
        "--since",
        required=True,
        help="ISO-8601 timestamp, UTC; e.g. 2026-09-11T13:00:00Z",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="only this project directory name; the name starts with a dash, so "
        "write it as --repo-dir=-Users-example-Documents-claude-oss",
    )
    parser.add_argument(
        "--defect-at",
        type=int,
        default=DEFAULT_DEFECT_AT,
        help="list every transcript whose max context reached this (default 400000)",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    if parse_since(args.since) is None:
        result = {
            "state": STATE_COULD_NOT_READ,
            "why": "--since is not an ISO-8601 timestamp: {!r}".format(args.since),
        }
    else:
        result = measure(
            args.projects_dir,
            since=args.since,
            repo_dir=args.repo_dir,
            defect_at=args.defect_at,
        )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render(result))
    return 2 if result["state"] == STATE_COULD_NOT_READ else 0


if __name__ == "__main__":
    sys.exit(main())
