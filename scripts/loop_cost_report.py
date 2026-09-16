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

A transcript's kind (`classify`) is read primarily off `attributionAgent` --
the `subagent_type` Claude Code itself records on every record of a spawned
agent's own transcript, present from spawn time and never guessed at. Known
values map directly: `oss:sub-manager` -> `sub-manager`, `oss:releaser` ->
`releaser`, `oss:scheduler-step` -> `scheduler-step`, `oss:tick-dispatch` ->
`tick-dispatch`, `oss:tick-review` -> `tick-review` (#1544 step 2),
`oss:tick-merge` -> `tick-merge`, `oss:tick-accounting` -> `tick-accounting`
(#1544 steps 3-4), `oss:developer` -> `developer`,
`oss:auditor`/`oss:release-auditor` -> `audit-review`; any other
declared agent (`Explore`, `general-purpose`, `oss:triager`, `oss:recon`,
`oss:doctor`, `claude-code-guide`, a forked session, ...) -> `other`, visible
in the table rather than silently folded into a neighbour. A file that is not
under `subagents/` is always `main-session`, regardless of what it carries.

`attributionAgent` is absent from transcripts recorded before this field
existed, and from a `main-session` transcript always (#1526) -- for those,
`classify` falls back to sniffing the first `type == "user"` record's prompt
for a literal phrase, in this order: `spawn token` -> `sub-manager`, `run one
release` -> `releaser`, `read and follow` -> `scheduler-step`, `issue`/`lane`
in the first 300 characters -> `developer`, `audit`/`review` in the first 200
characters -> `audit-review`, else `other`. This is the entire prior
behaviour, kept only as the fallback: a real sub-manager whose prompt lacked
`spawn token` fell through this chain to `other` -- worse, if the prompt
named an issue or a lane early (as every dispatch brief does), it fell
through to `developer` instead, inflating the very number used to argue the
lanes are the product (#1526). The declared attribution cannot drift this
way.

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
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402

STATE_MEASURED = "measured"
STATE_NOTHING = "nothing-in-window"
STATE_COULD_NOT_READ = "could-not-read"

KINDS = (
    "main-session",
    "sub-manager",
    "releaser",
    "scheduler-step",
    "tick-dispatch",
    "tick-review",
    "tick-merge",
    "tick-accounting",
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

#: `attributionAgent` -> `KINDS`, for the spawned agent kinds this loop names
#: a dedicated row for. Anything spawned but not listed here (`Explore`,
#: `general-purpose`, `oss:triager`, `oss:recon`, `oss:doctor`, a forked
#: session, ...) reads `other` rather than being guessed into a neighbour.
ATTRIBUTION_MAP = {
    "oss:sub-manager": "sub-manager",
    "oss:releaser": "releaser",
    "oss:scheduler-step": "scheduler-step",
    "oss:tick-dispatch": "tick-dispatch",
    "oss:tick-review": "tick-review",
    "oss:tick-merge": "tick-merge",
    "oss:tick-accounting": "tick-accounting",
    "oss:developer": "developer",
    "oss:auditor": "audit-review",
    "oss:release-auditor": "audit-review",
}


# --- per-issue attribution (#1618) --------------------------------------------------
#
# The join `measure` does not attempt: which issue(s) a transcript's spend
# belongs to. Three rules, tried in this order, per the issue's own
# "Attribution" section -- a prompt naming an issue number directly wins
# over a worktree/branch suffix (auditors) wins over a pull-request-to-issue
# map entry (tick-review/tick-merge); nothing matching any of the three is
# `RULE_UNATTRIBUTED`, reported as its own line rather than dropped.

RULE_PROMPT = "prompt-issue-number"
RULE_WORKTREE = "worktree-or-branch"
RULE_PR_MAP = "pr-to-issue-map"
RULE_UNATTRIBUTED = "unattributed"

#: How far past the word "issue"/"issues" to look for the number(s) it
#: names. Bounded the same way `classify`'s own prompt-sniff fallback is
#: bounded (its 300/200-char heads): an unrelated number deep in a long
#: prompt must not be swept in just because the word "issue" appeared
#: somewhere earlier in the same text.
_ISSUE_WORD_RE = re.compile(r"\bissues?\b\s*:?\s*", re.IGNORECASE)
_NUMBER_RE = re.compile(r"#?(\d{3,6})\b")
_ISSUE_WINDOW = 120

_WORKTREE_RE = re.compile(r"-wt/(\d+)\b")
_BRANCH_RE = re.compile(r"\bbranch\s+[\w./-]*?(\d+)\b", re.IGNORECASE)
_PR_PHRASE_RE = re.compile(r"pull request\s*#?(\d+)", re.IGNORECASE)
_BARE_PR_LIST_RE = re.compile(r"^(?:#?\d{1,6}(?:\s*,\s*)?)+$")
_BARE_PR_TOKEN_RE = re.compile(r"#?(\d{1,6})")


def _issue_numbers_from_prompt(text):
    """Every issue number the text names right after the word "issue"/
    "issues", in first-seen order -- covers all four phrasings #1618 cites
    (`Issue: 1477.`, `Issues: 1389, 1499, 1576.`, `Recon issues 1361 and
    1511 in the claude-oss repo`, `Issue #1566: ...`). ``[]`` when the word
    never appears, or names nothing that parses as a number.
    """
    if not text:
        return []
    match = _ISSUE_WORD_RE.search(text)
    if not match:
        return []
    window = text[match.end() : match.end() + _ISSUE_WINDOW]
    cuts = [i for i in (window.find("\n"), window.find(". ")) if i != -1]
    if cuts:
        window = window[: min(cuts)]
    numbers = []
    for token in _NUMBER_RE.findall(window):
        number = int(token)
        if number not in numbers:
            numbers.append(number)
    return numbers


def _issue_from_worktree_or_branch(text):
    """A worktree path (`claude-oss-wt/1583`) or a named branch
    (`branch fix/1583`) suffix, as one issue number -- the shape an
    `oss:auditor` prompt names instead of an issue number directly. ``None``
    when neither pattern matches.
    """
    if not text:
        return None
    match = _WORKTREE_RE.search(text)
    if match:
        return int(match.group(1))
    match = _BRANCH_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def _pr_numbers_from_prompt(text):
    """The pull request number(s) an `oss:tick-review`/`oss:tick-merge`
    prompt names -- ``[]`` when none found. Two shapes, tried in order: the
    phrase "pull request #N" (a caller that narrates), and -- the shape
    these two spawns' own prompts actually take, per `agents/tick-merge.md`
    ("Your prompt names exactly that pull request number and nothing else
    -- no board, no brief, no state file") and `agents/tick-review.md`
    ("Your prompt names exactly the pull request number(s) open this tick,
    and nothing else") -- **a bare number, or a comma-separated list of
    them, and nothing else in the whole prompt**. That second shape is
    deliberately narrow (`fullmatch`, not `search`): it must never read a
    number embedded in unrelated prose as a PR number, only a prompt that
    IS a number (list) and nothing more.
    """
    if not text:
        return []
    phrase_matches = _PR_PHRASE_RE.findall(text)
    if phrase_matches:
        return [int(n) for n in phrase_matches]
    stripped = text.strip()
    if stripped and _BARE_PR_LIST_RE.match(stripped):
        return [int(tok) for tok in _BARE_PR_TOKEN_RE.findall(stripped)]
    return []


def attribute_issues(first_prompt, pr_issue_map=None):
    """The issue number(s) one transcript's first prompt attributes to, and
    the rule that matched -- see the module docstring section above.
    Returns ``(issues, rule)``; ``issues`` is ``[]`` and ``rule`` is
    ``RULE_UNATTRIBUTED`` when nothing matched -- never dropped, per
    ``.claude/jit-context/paths/00-manual/counter-scripts-silent-gaps.md``.
    ``pr_issue_map``, when given, maps a PR number (``int``) to one issue
    number or a list of them; a PR number found with no map, or not present
    in the map given, is `RULE_UNATTRIBUTED` -- a map that was not asked for
    is not the same fact as "this PR closes no issue".
    """
    numbers = _issue_numbers_from_prompt(first_prompt)
    if numbers:
        return numbers, RULE_PROMPT
    worktree_issue = _issue_from_worktree_or_branch(first_prompt)
    if worktree_issue is not None:
        return [worktree_issue], RULE_WORKTREE
    if pr_issue_map:
        prs = _pr_numbers_from_prompt(first_prompt)
        if prs:
            issues = []
            for pr in prs:
                mapped = pr_issue_map.get(pr)
                if mapped is None:
                    mapped = pr_issue_map.get(str(pr))
                if not mapped:
                    continue
                for one in mapped if isinstance(mapped, list) else [mapped]:
                    number = int(one)
                    if number not in issues:
                        issues.append(number)
            if issues:
                return issues, RULE_PR_MAP
    return [], RULE_UNATTRIBUTED


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


def classify(first_prompt, subagent, attribution_agent=None):
    """The agent kind for one transcript -- see the module docstring for the
    two-tier order: the declared `attributionAgent` first, a fallback prompt
    sniff only when that is unavailable (#1526)."""
    if not subagent:
        return "main-session"
    if attribution_agent:
        return ATTRIBUTION_MAP.get(attribution_agent, "other")
    text = first_prompt or ""
    lowered = text.lower()
    if "spawn token" in lowered:
        return "sub-manager"
    if "run one release" in lowered:
        return "releaser"
    if "read and follow" in lowered:
        return "scheduler-step"
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
        "attribution_agent": None,
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
            if summary["attribution_agent"] is None:
                declared = record.get("attributionAgent")
                if isinstance(declared, str) and declared.strip():
                    summary["attribution_agent"] = declared
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
            kind = classify(
                summary["first_prompt"], subagent, summary["attribution_agent"]
            )
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


# --- per-issue report: the join and the two `gh` lookups it can use (#1618) --------


def _command_text(command):
    return " ".join(command)


def _decode_output(raw):
    """Decode a subprocess's bytes for display. Never raises -- the same
    fix as `scripts/oss_config.py`'s and `scripts/cohort_freeze.py`'s own
    `_decode_output` (#112), a third independent copy rather than an import
    for the same reason `cohort_freeze.py`'s docstring gives: reaching into
    another module for four lines would be a cross-module coupling none of
    these scripts otherwise has.
    """
    if raw is None:
        return ""
    if not isinstance(raw, bytes):
        return raw
    return raw.decode("utf-8", "replace")


def resolve_pr_issue_map(repo, pr_numbers, gh, run, timeout=25):
    """``{pr_number: [issue_number, ...]}`` via `gh pr view --json
    closingIssuesReferences`, one call per PR (`gh` has no batch form for
    this field). Returns ``(mapping, unresolved)`` -- ``unresolved`` is a
    list of ``{"pr": n, "why": str}``, one per PR that could not be
    resolved, never a silent drop: a PR that failed to resolve and one that
    genuinely closes no issue must not both vanish from ``mapping`` with
    nothing to tell them apart.
    """
    mapping = {}
    unresolved = []
    for pr in sorted(set(pr_numbers)):
        command = [
            gh,
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "number,closingIssuesReferences",
        ]
        try:
            done = run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError) as exc:
            unresolved.append(
                {
                    "pr": pr,
                    "why": "{} did not run ({})".format(_command_text(command), exc),
                }
            )
            continue
        stdout = _decode_output(done.stdout)
        stderr = _decode_output(done.stderr)
        if done.returncode != 0:
            message = (stderr or stdout or "").strip()
            unresolved.append(
                {
                    "pr": pr,
                    "why": "{} failed: {}".format(_command_text(command), message),
                }
            )
            continue
        try:
            data = json.loads(stdout)
        except (ValueError, TypeError):
            unresolved.append(
                {
                    "pr": pr,
                    "why": "{} printed text that is not JSON".format(
                        _command_text(command)
                    ),
                }
            )
            continue
        if not isinstance(data, dict):
            unresolved.append(
                {
                    "pr": pr,
                    "why": "{} printed something other than an object".format(
                        _command_text(command)
                    ),
                }
            )
            continue
        refs = data.get("closingIssuesReferences") or []
        numbers = [
            ref.get("number")
            for ref in refs
            if isinstance(ref, dict) and isinstance(ref.get("number"), int)
        ]
        mapping[pr] = numbers
    return mapping, unresolved


RESOLVED_ISSUES_JQ = ".[] | select(.pull_request == null) | {number, closed_at}"


def resolved_issues_in_window(repo, since_dt, gh, run, timeout=60):
    """Issue numbers closed at or after ``since_dt`` -- pull requests
    excluded server-side via `--jq`. `--paginate`, one compact JSON object
    per line, the same shape `cohort_freeze.fetch_issues` uses against this
    identical endpoint and for the identical reason: a raw `--paginate`
    array response cannot be concatenated safely across pages, while
    `--jq`-filtered lines can (#1618 self-review -- the first version of
    this function fetched one unpaginated page, so any tracker holding more
    than 100 closed issues silently truncated the window's own count, with
    `state` still reporting ``"ok"``). Returns ``(state, numbers, reason)``
    -- ``state`` is ``"ok"`` or ``"could-not-read"``, never a third thing,
    and never raises.
    """
    command = [
        gh,
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(repo),
        "-f",
        "state=closed",
        "-f",
        "per_page=100",
        "--jq",
        RESOLVED_ISSUES_JQ,
    ]
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (
            "could-not-read",
            [],
            "{} did not run ({})".format(_command_text(command), exc),
        )
    stdout = _decode_output(done.stdout)
    stderr = _decode_output(done.stderr)
    if done.returncode != 0:
        message = (stderr or stdout or "").strip()
        return (
            "could-not-read",
            [],
            "{} failed: {}".format(_command_text(command), message),
        )
    numbers = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return (
                "could-not-read",
                [],
                "a line of {} was not valid JSON: {!r}".format(
                    _command_text(command), line[:120]
                ),
            )
        if not isinstance(row, dict) or "number" not in row:
            return (
                "could-not-read",
                [],
                "a row from {} was missing number".format(_command_text(command)),
            )
        closed_at = row.get("closed_at")
        if not isinstance(closed_at, str):
            continue
        closed_dt = parse_since(closed_at)
        if closed_dt is None or closed_dt < since_dt:
            continue
        number = row.get("number")
        if isinstance(number, int):
            numbers.append(number)
    return "ok", sorted(set(numbers)), ""


def _empty_issue_agents():
    return {"agents": 0, "records": 0, "context_sent": 0, "rules": {}}


def _bump(bucket, kind, rule, summary):
    kind_bucket = bucket["kinds"].setdefault(kind, _empty_issue_agents())
    kind_bucket["agents"] += 1
    kind_bucket["records"] += summary["records"]
    kind_bucket["context_sent"] += summary["context_sent"]
    kind_bucket["rules"][rule] = kind_bucket["rules"].get(rule, 0) + 1
    bucket["records"] += summary["records"]
    bucket["context_sent"] += summary["context_sent"]


def measure_per_issue(
    projects_dir, since, repo_dir=None, pr_issue_map=None, resolved_issues=None
):
    """Spend joined to the issue(s) each transcript attributes to (#1618).

    Same three top-level ``state`` values as `measure` -- ``could-not-read``
    and ``nothing-in-window`` carry no per-issue breakdown, since nothing was
    read. On ``measured``, every transcript's spend lands in exactly one
    place: a bucket under ``issues``, keyed by its comma-joined issue
    numbers (`"1477"`, or `"1389,1499,1576"` for a lane that carries three --
    one composite bucket, never three separate ones, so a multi-issue lane's
    spend is never triple-counted), or ``unattributed`` when
    `attribute_issues` matched nothing. That is why totals reconcile:
    ``sum(bucket["context_sent"] for bucket in issues.values()) +
    unattributed["context_sent"]`` always equals the window total `measure`
    itself reports for the same arguments -- never a silent drop.

    ``resolved_issues``, when given, is the tracker's own denominator (see
    `resolved_issues_in_window`) -- carried through unchanged, ``None`` when
    it was not requested. ``None`` is not the same fact as "zero issues
    resolved"; a caller that wants the ratio has to check for it.
    """
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

    issues = {}
    unattributed = {"agents": 0, "records": 0, "context_sent": 0, "kinds": {}}
    malformed = []
    unreadable = []
    total_records = 0
    total_context = 0

    for entry in entries:
        if repo_dir is not None and entry != repo_dir:
            continue
        project_dir = projects_dir / entry
        if not project_dir.is_dir():
            continue
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
            kind = classify(
                summary["first_prompt"], subagent, summary["attribution_agent"]
            )
            matched, rule = attribute_issues(summary["first_prompt"], pr_issue_map)
            total_records += summary["records"]
            total_context += summary["context_sent"]
            if not matched:
                unattributed["agents"] += 1
                unattributed["records"] += summary["records"]
                unattributed["context_sent"] += summary["context_sent"]
                kind_bucket = unattributed["kinds"].setdefault(
                    kind, _empty_issue_agents()
                )
                kind_bucket["agents"] += 1
                kind_bucket["records"] += summary["records"]
                kind_bucket["context_sent"] += summary["context_sent"]
                kind_bucket["rules"][rule] = kind_bucket["rules"].get(rule, 0) + 1
                continue
            key = ",".join(str(n) for n in matched)
            bucket = issues.setdefault(
                key,
                {
                    "issue_numbers": matched,
                    "records": 0,
                    "context_sent": 0,
                    "kinds": {},
                },
            )
            _bump(bucket, kind, rule, summary)

    return {
        "state": STATE_MEASURED if total_records else STATE_NOTHING,
        "projects_dir": str(projects_dir),
        "since": since_dt.isoformat(),
        "repo_dir": repo_dir,
        "records": total_records,
        "context_sent": total_context,
        "issues": issues,
        "unattributed": unattributed,
        "resolved_issues": resolved_issues,
        "malformed_lines": len(malformed),
        "malformed": malformed,
        "unreadable": unreadable,
    }


def render_per_issue(result):
    lines = ["STATE: {}".format(result["state"])]
    if result["state"] == STATE_COULD_NOT_READ:
        lines.append("why: {}".format(result["why"]))
        return "\n".join(lines)
    if result["state"] == STATE_NOTHING:
        return "\n".join(lines)
    lines.append(
        "projects dir: {}  since: {}".format(result["projects_dir"], result["since"])
    )
    lines.append(
        "records: {}  context sent: {}  malformed lines: {}  unreadable: {}".format(
            _fmt(result["records"]),
            _fmt(result["context_sent"]),
            result["malformed_lines"],
            len(result["unreadable"]),
        )
    )
    resolved = result.get("resolved_issues")
    if resolved is None:
        lines.append("resolved issues (tracker): not-requested")
    else:
        numbers = resolved.get("numbers")
        count = (
            "{} issue(s)".format(len(numbers))
            if isinstance(numbers, list)
            else "no count"
        )
        lines.append(
            "resolved issues (tracker): {}  {}  {}".format(
                resolved.get("state"), count, resolved.get("reason") or ""
            )
        )
    for key in sorted(
        result["issues"],
        key=lambda k: result["issues"][k]["context_sent"],
        reverse=True,
    ):
        bucket = result["issues"][key]
        lines.append("")
        lines.append(
            "== issue {}  records {}  context sent {}".format(
                key, _fmt(bucket["records"]), _fmt(bucket["context_sent"])
            )
        )
        for kind, kind_bucket in bucket["kinds"].items():
            lines.append(
                "  {:<15} agents {:>3} records {:>6} context {:>14} rules {}".format(
                    kind,
                    kind_bucket["agents"],
                    _fmt(kind_bucket["records"]),
                    _fmt(kind_bucket["context_sent"]),
                    kind_bucket["rules"],
                )
            )
    lines.append("")
    lines.append(
        "unattributed  agents {}  records {}  context sent {}".format(
            result["unattributed"]["agents"],
            _fmt(result["unattributed"]["records"]),
            _fmt(result["unattributed"]["context_sent"]),
        )
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
    parser.add_argument(
        "--per-issue",
        action="store_true",
        help="report spend joined to the issue(s) resolved, not per project (#1618)",
    )
    parser.add_argument(
        "--pr-issue-map",
        default=None,
        help="a JSON file mapping PR number -> issue number(s), for attributing "
        "oss:tick-review/oss:tick-merge spend (build one with resolve_pr_issue_map)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="owner/name slug; with --per-issue, also reports the tracker's own "
        "count of issues closed in the window (the denominator)",
    )
    parser.add_argument("--gh", default=None, help="the gh executable (default: PATH)")
    args = parser.parse_args(argv)

    if parse_since(args.since) is None:
        result = {
            "state": STATE_COULD_NOT_READ,
            "why": "--since is not an ISO-8601 timestamp: {!r}".format(args.since),
        }
    elif args.per_issue:
        pr_issue_map = None
        if args.pr_issue_map:
            try:
                raw_map = json.loads(
                    Path(args.pr_issue_map).read_text(encoding="utf-8")
                )
                pr_issue_map = {int(k): v for k, v in raw_map.items()}
            except (OSError, ValueError, AttributeError) as exc:
                result = {
                    "state": STATE_COULD_NOT_READ,
                    "why": "--pr-issue-map {} could not be read: {}".format(
                        args.pr_issue_map, exc
                    ),
                }
                pr_issue_map = "unreadable"
        if pr_issue_map == "unreadable":
            pass  # result already set above
        else:
            resolved_issues = None
            if args.repo:
                gh = args.gh or gh_which.safe_which("gh")
                if not gh:
                    resolved_issues = {
                        "state": STATE_COULD_NOT_READ,
                        "numbers": None,
                        "reason": "gh is not on PATH",
                    }
                else:
                    state, numbers, reason = resolved_issues_in_window(
                        args.repo, parse_since(args.since), gh, subprocess.run
                    )
                    resolved_issues = {
                        "state": state,
                        "numbers": numbers,
                        "reason": reason,
                    }
            result = measure_per_issue(
                args.projects_dir,
                since=args.since,
                repo_dir=args.repo_dir,
                pr_issue_map=pr_issue_map,
                resolved_issues=resolved_issues,
            )
    else:
        result = measure(
            args.projects_dir,
            since=args.since,
            repo_dir=args.repo_dir,
            defect_at=args.defect_at,
        )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.per_issue:
        print(render_per_issue(result))
    else:
        print(render(result))
    return 2 if result["state"] == STATE_COULD_NOT_READ else 0


if __name__ == "__main__":
    sys.exit(main())
