#!/usr/bin/env python3
"""Count refused tool calls across agent transcripts -- #313, step 1 only.

#313's own body proposed a jit-context rule for the largest refusal class. The
first comment on that issue corrects the arithmetic: a rule fires at
``PreToolUse``, so it occupies the same turn the refusal it replaces already
occupied. It does not remove a turn. What it can buy -- fewer wrong remedies,
less re-sent payload -- is only worth building against a measurement, and the
issue says so in its own words: "the scan is about thirty lines of Python and
is the deliverable that matters more than the rule." This is that scan. The
rule itself is out of scope here; see the developer report for #313.

## What this counts, and why each field is here

Per transcript: which model answered (from ``message.model`` on each assistant
turn, **never inferred from anything else** -- a model override that silently
did not apply and a model that behaved identically must not render alike);
turn counts split by shape (carries a ``tool_use`` block, or none -- and a
turn with none is split again into thinking-only and text-only, because a
turn that thought and said nothing is a different cost than one that spoke);
tool calls and, for calls that invoke ``supertool``, an ops-per-call count;
runs of *consecutive* single-op read calls, because that is the batching #313's
last comment measured as the largest lever and the only one visible from
adjacency rather than from a single call; refusal counts by class, matched on
the tool_result text; and the three token fields the issue asked for, summed
per transcript.

## The third state, because that is the whole point of this repository

A directory with no transcripts and a directory full of transcripts that
refused nothing must not render the same way. ``run()`` returns
``state: "no-transcripts-found"`` for the first and ``state: "measured"`` with
an **empty** ``refusal_totals`` dict for the second -- ``{}`` is a real
finding ("nothing refused"), ``None`` is the absence of a finding
("nothing was looked at"). The same split holds one level down: a transcript
file this script could not open or parse is named in ``unreadable_files``,
never silently subtracted from ``transcripts_found``, and a directory this
script could not list is named in ``unreadable_dirs`` -- because
``Path.rglob`` swallows ``PermissionError`` while walking and would otherwise
answer "no transcripts here" for a subtree it was never able to enter (see
this repo's own CLAUDE.md for the instance that bit `doctor.py`). This module
therefore walks with ``os.walk(onerror=...)`` rather than ``rglob``.

The same split decides what ``--agent`` may subtract, and it may subtract
nothing: ``transcripts_parsed`` is every file the parser read, counted before
the filter, so ``transcripts_found - transcripts_parsed`` is always exactly
``len(unreadable_files)`` and never a count of files that were simply not asked
about (#374). What the filter matched is its own number,
``transcripts_matched_agent_filter`` -- ``None`` when no filter was applied,
an integer when one was, and ``0`` meaning it matched nothing, which is a
finding rather than a silence. ``agent_filter`` echoes the filter itself, so a
filtered run is legible as one now that its found and parsed counts agree.

## Where transcripts are found -- a mechanism, not a fact about one repository

``~/.claude/projects/<encoded-cwd>/**/subagents/*.jsonl`` is one machine's
layout, not a fact this repository's code is allowed to hardcode (see
CLAUDE.md's governing rule). So the default root is *derived*:
``Path.home()`` plus an encoding of the given ``cwd`` (default
``os.getcwd()``) with ``/`` and ``.`` replaced by ``-``, matching a mapping
**observed** against real directory names on the machine this was built on
(``/Users/x/Documents/claude-oss`` -> ``-Users-x-Documents-claude-oss``,
including the doubled dash a dot produces). It is a reasoned, not a
guaranteed, encoding: nothing here asserts it is Claude Code's published
contract, and a caller who already knows a different path passes ``--root``
or ``--glob`` and this guess is never consulted.

## Reading the transcript itself

Every subagent transcript line is a JSON record. An assistant record's
``message.content`` is a list of typed blocks (``text``, ``thinking``,
``tool_use``); a user record answering a tool call carries
``message.content`` with ``tool_result`` blocks, whose ``content`` field is
the string a refusal's own text lives in (confirmed against real transcripts,
not assumed from the guard's own docstring, because the guard's prose and its
actual runtime shape are not guaranteed to be the same document). Refusal
classification is a first-match ordered list of substrings taken from the
five classes #313's body names plus the generic residual it also names
("a plain op ``ERROR:``"), in an order chosen so the more specific patterns
(the jit-context block, the no-cut block) are tried before the residual
catches anything with ``ERROR:`` in it.

## Batchability, and why only ``read``/``grep``/``glob``/``map``/``around``/
## ``between``/``tree`` count as "read"

That set is not invented here -- it is exactly the set this repository's own
`agents/*.md` briefs already name as the ops to batch ("Batch 6-7 ops per
call -- read, grep, glob, map, around, between, tree"). Anything else is
treated as a write for the purposes of a call's read-only/write-only/mixed
classification, which is a heuristic and is documented as one: it does not
call out to supertool's own ``ops:roster`` to ask, because a live dependency
call is not something a unit test can rely on, and the set above is already
the authority this repository itself has been using.

Python 3.9 compatible -- this project's CI runs 3.9 through 3.12.
"""

import argparse
import json
import os
import re
import stat
import statistics
import sys
from pathlib import Path

EXIT_MEASURED = 0
EXIT_NO_TRANSCRIPTS = 3
EXIT_USAGE = 2

STATE_MEASURED = "measured"
STATE_NO_TRANSCRIPTS = "no-transcripts-found"

#: Ops this repository's own briefs already name as the ones to batch. See the
#: module docstring -- this is not an invented classification.
READ_OPS = frozenset({"read", "grep", "glob", "map", "around", "between", "tree"})

#: (class name, substring to match) in priority order -- more specific patterns
#: first, so the generic "plain-op-error" residual only catches what nothing
#: else claimed. Substrings taken verbatim from real refusal text, not from a
#: guard's own docstring, which is not guaranteed to match its runtime output.
_REFUSAL_PATTERNS = (
    ("path-escapes-cwd", "path escapes cwd"),
    ("raw-command-guard", "is replaced by supertool"),
    ("no-cut", "Do not cut a supertool op's output"),
    ("unavailable-here", "unavailable here, not unknown"),
    ("jit-context-block", "# JIT Context:"),
    ("plain-op-error", "ERROR:"),
)

# A call boundary (start of string, or after ; & | or a newline -- a
# newline is bash's own default statement separator and this repository's
# own agent briefs model multi-line command blocks as the norm, so a
# supertool call on any line after the first was silently missed until this
# was added; found by review), then zero or more leading env-var assignments
# (SUPERTOOL_ALLOW_OUTSIDE_CWD=1 supertool ...), then the executable -- bare
# `supertool`, `./supertool`, or a full path ending in `/supertool`, because
# a developer agent invokes all three shapes and the first version of this
# pattern only matched the first two, silently dropping 1,429 of 10,295 real
# supertool-mentioning Bash calls (13.9%) -- nearly all single-op writes
# reached through an absolute path or SUPERTOOL_ALLOW_OUTSIDE_CWD=1, which
# skewed every ops-per-call and single-op-share figure computed from the
# narrower pattern. Measured while building this script, against this
# repository's own transcripts.
_SUPERTOOL_CALL_RE = re.compile(
    r"(?:^|[;&|\n]\s*)"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:\S*/)?supertool(?:\.exe)?\s+"
    r"((?:(?:'[^']*'|\"[^\"]*\")\s*)+)"
)
# Single- or double-quoted args -- a git-commit call's message is routinely
# double-quoted and spans multiple physical lines; the character class here
# matches a newline without DOTALL, so a multi-line quoted body is still one
# op, not several.
_QUOTED_ARG_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def classify_refusal(text):
    """Which refusal class `text` (a tool_result's own content) belongs to, or
    None when it is not a refusal at all -- the must-not-fire half of #313's
    own pairing requirement."""
    if not text:
        return None
    for name, pattern in _REFUSAL_PATTERNS:
        if pattern in text:
            return name
    return None


def parse_supertool_calls(command):
    """Every `supertool '...' '...'` invocation in a Bash command string, each
    as the list of its quoted op strings. A command with no supertool call
    returns []; a command chaining several returns one list per invocation."""
    if not command:
        return []
    calls = []
    for match in _SUPERTOOL_CALL_RE.finditer(command):
        ops = [single or double for single, double in _QUOTED_ARG_RE.findall(match.group(1))]
        if ops:
            calls.append(ops)
    return calls


def _op_name(op):
    return op.split(":", 1)[0].strip().lower()


def _call_class(ops):
    kinds = {_op_name(op) in READ_OPS for op in ops}
    if kinds == {True}:
        return "read-only"
    if kinds == {False}:
        return "write-only"
    return "mixed"


def _content_text(block_content):
    """A tool_result's `content` field is a string in the ordinary case, but
    the transport also allows a list of content blocks. Flatten either shape
    to one string for substring matching -- never raise on the shape."""
    if isinstance(block_content, str):
        return block_content
    if isinstance(block_content, list):
        parts = []
        for item in block_content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def analyze_transcript(path):
    """Read one transcript file. Never raises -- an unreadable or unparsable
    file comes back as `{"ok": False, "reason": ...}` so the caller can name
    it separately from a transcript that was read and found clean."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "path": str(path), "reason": "{0}: {1}".format(type(exc).__name__, exc)}

    turns = 0
    turns_with_tool = 0
    turns_thinking_only = 0
    turns_text_only = 0
    turns_other_no_tool = 0
    tool_calls = 0
    ops_per_call = []
    calls_by_class = {"read-only": 0, "write-only": 0, "mixed": 0}
    call_kinds = []  # ordered "single-read" / "other", across every tool call
    refusals = {}
    models_seen = set()
    agent = None
    tokens = {"cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 0}
    parse_errors = 0
    non_blank_lines = 0
    parsed_records = 0

    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        non_blank_lines += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if not isinstance(record, dict):
            continue
        parsed_records += 1

        rtype = record.get("type")
        if agent is None:
            candidate = record.get("attributionAgent")
            if isinstance(candidate, str) and candidate:
                agent = candidate

        if rtype == "assistant":
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            turns += 1
            model = message.get("model")
            if isinstance(model, str) and model:
                models_seen.add(model)

            usage = message.get("usage")
            if isinstance(usage, dict):
                for key in tokens:
                    value = usage.get(key)
                    if isinstance(value, (int, float)):
                        tokens[key] += value

            content = message.get("content")
            blocks = content if isinstance(content, list) else []
            block_types = {b.get("type") for b in blocks if isinstance(b, dict)}
            has_tool_use = "tool_use" in block_types

            if has_tool_use:
                turns_with_tool += 1
            elif block_types == {"thinking"}:
                turns_thinking_only += 1
            elif block_types == {"text"}:
                turns_text_only += 1
            else:
                turns_other_no_tool += 1

            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_calls += 1
                command = ""
                if block.get("name") == "Bash":
                    command = (block.get("input") or {}).get("command", "")
                supertool_calls = parse_supertool_calls(command)
                if not supertool_calls:
                    call_kinds.append("other")
                    continue
                for ops in supertool_calls:
                    ops_per_call.append(len(ops))
                    call_class = _call_class(ops)
                    calls_by_class[call_class] += 1
                    if len(ops) == 1 and _op_name(ops[0]) in READ_OPS:
                        call_kinds.append("single-read")
                    else:
                        call_kinds.append("other")

        elif rtype == "user":
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                text = _content_text(block.get("content"))
                cls = classify_refusal(text)
                if cls is not None:
                    refusals[cls] = refusals.get(cls, 0) + 1

    if non_blank_lines and parsed_records == 0:
        # Every line failed to parse -- this is not a transcript with zero
        # activity, it is a file this script could not read. Reported
        # separately (see discover_transcripts / run), never folded into
        # "read, found nothing" -- the same split CLAUDE.md documents for
        # test_unwired_scripts_253.py's own unreadable-file handling.
        return {
            "ok": False,
            "path": str(path),
            "reason": "no valid JSON record in {0} non-blank line(s) ({1} parse error(s))".format(
                non_blank_lines, parse_errors
            ),
        }

    run_lengths = []
    current = 0
    for kind in call_kinds:
        if kind == "single-read":
            current += 1
        else:
            if current:
                run_lengths.append(current)
            current = 0
    if current:
        run_lengths.append(current)

    reads_in_runs = sum(length for length in run_lengths if length >= 2)
    turns_removable = sum(length - 1 for length in run_lengths if length >= 2)

    if not models_seen:
        model = "unknown"
    elif len(models_seen) == 1:
        model = next(iter(models_seen))
    else:
        model = "mixed:" + ",".join(sorted(models_seen))

    return {
        "ok": True,
        "path": str(path),
        "agent": agent or "unknown",
        "model": model,
        "turns": turns,
        "turns_with_tool": turns_with_tool,
        "turns_thinking_only": turns_thinking_only,
        "turns_text_only": turns_text_only,
        "turns_other_no_tool": turns_other_no_tool,
        "tool_calls": tool_calls,
        "ops_per_call": ops_per_call,
        "calls_by_class": calls_by_class,
        "single_read_run_lengths": run_lengths,
        "reads_in_runs": reads_in_runs,
        "turns_removable": turns_removable,
        "refusals": refusals,
        "tokens": tokens,
        "parse_errors": parse_errors,
    }


def discover_transcripts(roots):
    """Every `*.jsonl` file under any of `roots`, walked with `os.walk` rather
    than `Path.rglob` -- rglob swallows PermissionError while walking a
    subtree and returns nothing for it, which renders identically to "no
    transcripts here" for a directory this process was never able to enter.
    Returns (files, unreadable_dirs); the second is never folded into the
    first coming up empty."""
    files = []
    unreadable_dirs = []

    for root in roots:
        root = Path(root)
        # `Path.exists()`/`Path.is_file()` are not the "never raises"
        # promise they look like -- both are built on `os.stat`, wrapped in
        # a `try/except OSError: return False` that only re-raises a chosen
        # list of errnos, and the list differs across interpreter versions
        # (CLAUDE.md documents the same trap for `_read_config` in
        # scripts/release_delta.py). On some versions a root whose own path
        # cannot be traversed (a parent directory with no execute bit) raises
        # PermissionError out of exists() uncaught; on others exists()
        # swallows it and answers False, which renders identically to a root
        # that plainly does not exist. `os.stat` itself -- the primitive
        # neither wrapper is built to second-guess -- raises consistently,
        # so it is used directly here instead of either pathlib method, and
        # the failure is reported the same way os.walk's own onerror already
        # reports an unreadable subtree: named, not silently folded into
        # "absent". Found by audit.
        try:
            root_mode = os.stat(str(root)).st_mode
        except FileNotFoundError:
            # The ordinary case -- a guessed or stale root simply is not
            # there. Not a failure to report: every default-guess run where
            # the guess misses would otherwise spam `unreadable_dirs`.
            continue
        except OSError as exc:
            unreadable_dirs.append({"path": str(root), "reason": str(exc)})
            continue

        if stat.S_ISREG(root_mode):
            if root.suffix == ".jsonl":
                files.append(root)
            continue
        if not stat.S_ISDIR(root_mode):
            continue

        def _onerror(exc, _root=root):
            unreadable_dirs.append({"path": getattr(exc, "filename", None) or str(_root), "reason": str(exc)})

        for dirpath, _dirnames, filenames in os.walk(str(root), onerror=_onerror):
            for name in filenames:
                if name.endswith(".jsonl"):
                    files.append(Path(dirpath) / name)

    return files, unreadable_dirs


def _median(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return statistics.median(values)


def _histogram(counts, buckets=(1, 2, 3, 4, 5)):
    hist = {str(b): 0 for b in buckets}
    hist["{0}+".format(buckets[-1] + 1)] = 0
    for value in counts:
        placed = False
        for b in buckets:
            if value == b:
                hist[str(b)] += 1
                placed = True
                break
        if not placed:
            hist["{0}+".format(buckets[-1] + 1)] += 1
    return hist


def _summarize_group(analyses):
    turns = [a["turns"] for a in analyses]
    tool_calls = [a["tool_calls"] for a in analyses]
    text_only = [a["turns_text_only"] for a in analyses]
    refusal_totals = {}
    for a in analyses:
        for cls, count in a["refusals"].items():
            refusal_totals[cls] = refusal_totals.get(cls, 0) + count
    refusals_per_100_turns = [
        (sum(a["refusals"].values()) / a["turns"]) * 100 for a in analyses if a["turns"]
    ]
    all_ops = [n for a in analyses for n in a["ops_per_call"]]
    single_op = sum(1 for n in all_ops if n == 1)
    single_op_share = (single_op / len(all_ops)) if all_ops else None
    all_runs = [length for a in analyses for length in a["single_read_run_lengths"]]

    return {
        "count": len(analyses),
        "median_turns": _median(turns),
        "median_tool_calls": _median(tool_calls),
        "median_text_only_turns": _median(text_only),
        "median_refusals_per_100_turns": _median(refusals_per_100_turns),
        "refusal_totals": refusal_totals,
        "ops_per_call_histogram": _histogram(all_ops),
        "single_op_share": single_op_share,
        "single_read_run_length_histogram": _histogram(all_runs),
        "reads_in_runs": sum(a["reads_in_runs"] for a in analyses),
        "turns_removable": sum(a["turns_removable"] for a in analyses),
        "token_totals": {
            key: sum(a["tokens"][key] for a in analyses)
            for key in ("cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
        },
    }


def run(roots, agent_filter=None, detail=False):
    """The whole scan over `roots`. Returns the report dict; never raises."""
    files, unreadable_dirs = discover_transcripts(roots)

    if not files:
        return {
            "state": STATE_NO_TRANSCRIPTS,
            "roots_searched": [str(r) for r in roots],
            "unreadable_dirs": unreadable_dirs,
            "transcripts_found": 0,
            "agent_filter": agent_filter,
            "refusal_totals": None,
        }

    parsed = []
    unreadable_files = []
    for path in files:
        result = analyze_transcript(path)
        if result["ok"]:
            parsed.append(result)
        else:
            unreadable_files.append({"path": result["path"], "reason": result["reason"]})

    # `transcripts_parsed` counts every file the parser actually read, and is
    # therefore taken *before* the agent filter (#374). Filtering first made one
    # number answer two different questions depending on whether `--agent` was
    # passed: three clean transcripts with a filter matching one reported
    # `found: 3, parsed: 1, unreadable_files: []`, in which `found - parsed`
    # reads as two parse failures and the third state a reader would check to
    # disprove that is empty. The invariant this restores is
    # `found - parsed == len(unreadable_files)`, unconditionally.
    #
    # Making the two agree is only half of it, and on its own it would be the
    # worse fix: it also erases the fact that a filter ran, so a filtered run
    # and an unfiltered one over the same directory would render identically
    # apart from aggregates nobody compares. The filtered subset therefore gets
    # a count of its own, in three states rather than two --
    # `transcripts_matched_agent_filter` is `None` when no filter was applied
    # (there was no question to answer), an integer when one was, and `0` is a
    # real finding meaning the filter matched nothing.
    analyses = parsed
    matched_agent_filter = None
    if agent_filter is not None:
        analyses = [a for a in parsed if a["agent"] == agent_filter]
        matched_agent_filter = len(analyses)

    by_agent = {}
    for a in analyses:
        agent_bucket = by_agent.setdefault(a["agent"], {"count": 0, "_analyses": [], "by_model": {}})
        agent_bucket["count"] += 1
        agent_bucket["_analyses"].append(a)
        model_bucket = agent_bucket["by_model"].setdefault(a["model"], [])
        model_bucket.append(a)

    for agent_bucket in by_agent.values():
        by_model = {}
        for model, model_analyses in agent_bucket["by_model"].items():
            by_model[model] = _summarize_group(model_analyses)
        agent_bucket["by_model"] = by_model
        del agent_bucket["_analyses"]

    refusal_totals = {}
    for a in analyses:
        for cls, count in a["refusals"].items():
            refusal_totals[cls] = refusal_totals.get(cls, 0) + count

    report = {
        "state": STATE_MEASURED,
        "roots_searched": [str(r) for r in roots],
        "transcripts_found": len(files),
        "transcripts_parsed": len(parsed),
        "agent_filter": agent_filter,
        "transcripts_matched_agent_filter": matched_agent_filter,
        "unreadable_files": unreadable_files,
        "unreadable_dirs": unreadable_dirs,
        "refusal_totals": refusal_totals,
        "by_agent": by_agent,
        "overall": _summarize_group(analyses),
    }
    if detail:
        report["transcripts"] = analyses
    return report


def default_transcripts_root(cwd=None):
    """Where this machine's transcripts for `cwd` (default: the real cwd) are
    expected to live -- a derivation, not a fact baked into this file. See the
    module docstring for the encoding and how confident it is.

    `cwd` is taken as given, never resolved against the filesystem: a caller
    passing a synthetic example path (as the test pinning this encoding does)
    gets that path encoded, not an OSError from a path that does not exist.
    """
    cwd = str(cwd) if cwd is not None else os.getcwd()
    return Path.home() / ".claude" / "projects" / _encode_cwd_segment(cwd)


# The character class covers `/`, `.`, `\` and `:`, and each one earned its
# place the hard way:
#
# `/` and `.` are the originally observed encoding (see the module
# docstring). `\` was missing in the first version of this function --
# os.getcwd() on Windows returns a backslash-separated path, so the default
# guess silently pointed nowhere on Windows and a real absence there
# rendered identically to `no-transcripts-found` (found by audit).
#
# `:` was missing in the fix for the bug above, and it is not cosmetic: a
# Windows cwd almost always starts with a drive letter (C:\Users\...), so
# the segment this produces almost always started with "C:" before this
# fix -- and PureWindowsPath / WindowsPath treats a component of the shape
# "<letter>:..." as a drive-relative path, not an ordinary name, so joining
# it onto an existing path SILENTLY DROPS everything already joined and
# reparses from that component instead. Confirmed against the actual
# PR-358 CI failure line, which already shows the drive letter missing
# from the rendered path on a real Windows runner, not merely a stray
# backslash -- and reproduced locally with PureWindowsPath before this fix:
# joining ".../projects" with the unescaped "C:-Users-..." segment silently
# produced ".../projects/-Users-..." with "C:" gone entirely, which would
# also silently collide two different drives' transcript directories onto
# the same encoded name. Colon is also simply illegal in a Windows path
# component, so leaving it in was never going to name a real directory even
# without the drive-reparsing.
#
# Factored out of default_transcripts_root so a test can exercise the
# encoding against a PureWindowsPath directly, without needing a real
# Windows machine or monkeypatching Path.home().
def _encode_cwd_segment(cwd):
    return re.sub(r"[/.\\\\:]", "-", cwd)


def _build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--root", action="append", default=[], help="Directory to search recursively for *.jsonl transcripts. Repeatable.")
    parser.add_argument("--agent", default=None, help="Filter to one attributionAgent value, e.g. oss:developer.")
    parser.add_argument("--detail", action="store_true", help="Include a full per-transcript row list in the output.")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (0 for compact).")
    return parser


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    roots = [Path(r) for r in args.root] if args.root else [default_transcripts_root()]
    report = run(roots, agent_filter=args.agent, detail=args.detail)
    indent = args.indent if args.indent > 0 else None
    print(json.dumps(report, indent=indent, sort_keys=True))
    return EXIT_MEASURED if report["state"] == STATE_MEASURED else EXIT_NO_TRANSCRIPTS


if __name__ == "__main__":
    sys.exit(main())
